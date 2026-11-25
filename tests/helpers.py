"""Database helpers shared by integration and fault-injection tests."""

import time
import uuid


def insert_job(
    conn,
    status="PENDING",
    worker_id=None,
    attempt=0,
    max_attempts=3,
    lease_interval=None,
    idempotency_key=None,
):
    """
    Insert a job and return its id.

    Defaults describe a freshly submitted job: PENDING, no owner,
    no lease, attempt 0. Override them to build other states.

    lease_interval is a Postgres interval relative to NOW(),
    e.g. '30 seconds' for a live lease or '-1 second' for an
    expired one. None means no lease.

    idempotency_key defaults to a random UUID; pass one when the
    test needs to know it (claim_job doesn't return it).
    """
    if idempotency_key is None:
        idempotency_key = str(uuid.uuid4())

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jobs (
                idempotency_key,
                payload,
                status,
                worker_id,
                attempt,
                max_attempts,
                lease_expires_at
            )
            VALUES (%s, '{}', %s, %s, %s, %s, NOW() + %s::interval)
            RETURNING id
            """,
            (
                idempotency_key,
                status,
                worker_id,
                attempt,
                max_attempts,
                lease_interval,
            ),
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


def expire_lease(conn, job_id):
    """Backdate the lease so it has already expired (simulates a stalled worker)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET lease_expires_at = NOW() - interval '1 second'
            WHERE id = %s
            """,
            (job_id,),
        )


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
