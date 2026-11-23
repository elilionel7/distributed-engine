import threading
import time
import uuid

from engine.workers.recover_expired_job import recover_expired_jobs


def insert_leased_job(
    conn, attempt, max_attempts, lease_interval, status="RUNNING"
):
    """
    Insert a job owned by worker-1 with a lease (RUNNING by default).

    lease_interval is a Postgres interval relative to NOW(),
    e.g. '-1 second' for an expired lease or '30 seconds' for a live one.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jobs (
                idempotency_key,
                payload,
                status,
                attempt,
                max_attempts,
                worker_id,
                lease_expires_at
            )
            VALUES (
                %s, '{}', %s, %s, %s, 'worker-1',
                NOW() + %s::interval
            )
            RETURNING id
            """,
            (str(uuid.uuid4()), status, attempt, max_attempts, lease_interval),
        )
        return cur.fetchone()[0]


def get_job_state(conn, job_id):
    """Return (status, worker_id, lease_expires_at, attempt) for one job."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, worker_id, lease_expires_at, attempt
            FROM jobs
            WHERE id = %s
            """,
            (job_id,),
        )
        return cur.fetchone()


def test_expired_job_with_attempts_remaining_becomes_pending(
    clean_jobs, conn_a
):
    # Arrange: insert a RUNNING job with an expired lease.
    job_id = insert_leased_job(
        conn_a, attempt=1, max_attempts=3, lease_interval="-1 second"
    )

    # Act: call recover_expired_jobs(conn_a).
    result = recover_expired_jobs(conn_a)

    # Assert: verify the persisted state.
    assert result == {"retried": 1, "failed": 0}

    status, worker_id, lease_expires_at, attempt = get_job_state(conn_a, job_id)

    assert status == "PENDING"
    assert worker_id is None
    assert lease_expires_at is None
    assert attempt == 1  # recovery doesn't consume an attempt


def test_expired_job_with_no_attempts_remaining_becomes_failed(
    clean_jobs, conn_a
):
    job_id = insert_leased_job(
        conn_a,
        attempt=3,
        max_attempts=3,
        lease_interval="-1 second",
    )

    result = recover_expired_jobs(conn_a)

    assert result == {"retried": 0, "failed": 1}

    status, worker_id, lease_expires_at, attempt = get_job_state(conn_a, job_id)

    assert status == "FAILED"
    assert worker_id is None
    assert lease_expires_at is None
    assert attempt == 3


def test_recovery_does_not_touch_job_with_valid_lease(
    clean_jobs, conn_a
):
    job_id = insert_leased_job(
        conn_a,
        attempt=1,
        max_attempts=3,
        lease_interval="30 seconds",
    )
    state_before = get_job_state(conn_a, job_id)

    result = recover_expired_jobs(conn_a)

    assert result == {"retried": 0, "failed": 0}

    # The row is exactly as it was: still RUNNING, still owned by
    # worker-1, same lease and attempt.
    assert get_job_state(conn_a, job_id) == state_before

    status, worker_id, lease_expires_at, attempt = state_before
    assert status == "RUNNING"
    assert worker_id == "worker-1"
    assert lease_expires_at is not None
    assert attempt == 1


def test_recovery_ignores_completed_jobs(clean_jobs, conn_a):
    # Arrange: insert a COMPLETED job.
    # complete_job() clears the lease, but this row keeps an expired
    # one on purpose: even if a lease were ever left behind, the
    # status = 'RUNNING' filter must keep recovery from re-running it.
    job_id = insert_leased_job(
        conn_a,
        attempt=1,
        max_attempts=3,
        lease_interval="-1 second",
        status="COMPLETED",
    )

    # Capture its state before recovery.
    state_before = get_job_state(conn_a, job_id)

    # Act: run recover_expired_jobs().
    result = recover_expired_jobs(conn_a)

    # Assert: no jobs recovered and state unchanged.
    assert result == {"retried": 0, "failed": 0}
    assert get_job_state(conn_a, job_id) == state_before
    assert state_before[0] == "COMPLETED"


def test_recovery_is_idempotent(clean_jobs, conn_a):
    job_id = insert_leased_job(
        conn_a,
        attempt=1,
        max_attempts=3,
        lease_interval="-1 second",
    )

    first = recover_expired_jobs(conn_a)
    state_after_first = get_job_state(conn_a, job_id)

    second = recover_expired_jobs(conn_a)

    # The first run recovers the job; the second finds nothing to do.
    assert first == {"retried": 1, "failed": 0}
    assert second == {"retried": 0, "failed": 0}

    # The second run didn't change the row.
    assert get_job_state(conn_a, job_id) == state_after_first
    assert state_after_first == ("PENDING", None, None, 1)


def wait_until_blocked_on_lock(
    monitor_conn,
    backend_pid,
    blocker_pid,
    timeout=1.5,
):
    """
    Poll until backend_pid is waiting on a lock held by blocker_pid.

    Checking the blocker (not just "waiting on some lock") proves the
    contention is the one the test set up, not an unrelated session.

    The timeout must stay below conn_b's lock_timeout (2s), or B gives
    up waiting before we can observe it.
    """
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        row = monitor_conn.execute(
            """
            SELECT wait_event_type, pg_blocking_pids(pid)
            FROM pg_stat_activity
            WHERE pid = %s
            """,
            (backend_pid,),
        ).fetchone()

        if (
            row is not None
            and row[0] == "Lock"
            and blocker_pid in row[1]
        ):
            return

        time.sleep(0.01)

    raise AssertionError(
        f"Backend {backend_pid} never blocked "
        f"on backend {blocker_pid}"
    )


def test_concurrent_recovery_recovers_job_exactly_once(
    clean_jobs, conn_a, conn_b, conn_monitor
):
    job_id = insert_leased_job(
        conn_a,
        attempt=1,
        max_attempts=3,
        lease_interval="-1 second",
    )

    # Recovery B blocks on A's row lock, so it must run in a thread;
    # on the main thread it would wait forever for a commit that the
    # main thread could never reach.
    outcome_b = {}

    def run_recovery_b():
        try:
            outcome_b["result"] = recover_expired_jobs(conn_b)
        except Exception as exc:  # surfaced in the main thread below
            outcome_b["error"] = exc

    thread_b = threading.Thread(target=run_recovery_b)
    pid_a = conn_a.info.backend_pid
    pid_b = conn_b.info.backend_pid

    try:
        # Hold A's transaction open so its row lock outlives
        # recover_expired_jobs()'s own (now nested) transaction.
        with conn_a.transaction():
            result_a = recover_expired_jobs(conn_a)

            thread_b.start()

            # Prove B really reached the locked row and is waiting.
            # Without this, B might start after A commits and the test
            # would pass without exercising the contention at all.
            wait_until_blocked_on_lock(conn_monitor, pid_b, blocker_pid=pid_a)

        # Leaving the block commits A and releases the lock.
        # B's UPDATE re-checks its WHERE clause against the committed
        # row (now PENDING), so it should skip it.

    finally:
        # Always wait for B if it was started, even when an assertion
        # above failed, so no thread outlives the test.
        if thread_b.ident is not None:
            thread_b.join(timeout=5)

    assert not thread_b.is_alive(), "Recovery B never finished"

    if "error" in outcome_b:
        raise outcome_b["error"]

    assert result_a == {"retried": 1, "failed": 0}
    assert outcome_b["result"] == {"retried": 0, "failed": 0}

    # Recovered exactly once: back to PENDING, attempt unchanged.
    assert get_job_state(conn_a, job_id) == ("PENDING", None, None, 1)
