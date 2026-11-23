from engine.workers.claim_job import claim_job
from engine.workers.complete_job import complete_job
from engine.workers.fail_job import fail_job
from engine.workers.recover_expired_job import recover_expired_jobs
from engine.workers.renew_lease import renew_lease
from tests.helpers import expire_lease, get_job_state, insert_job


def lease_is_live(conn, job_id):
    """True if the job's lease is still in the future according to Postgres."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT lease_expires_at > NOW() FROM jobs WHERE id = %s",
            (job_id,),
        )
        return cur.fetchone()[0]


def test_stale_attempt_cannot_complete_reclaimed_job(clean_jobs, conn_a):
    job_id = insert_job(conn_a)

    # 1. Worker A claims the job at attempt 1.
    first_claim = claim_job(conn_a, "worker-A")

    assert first_claim["id"] == job_id
    assert first_claim["attempt"] == 1

    # 2. Its lease expires.
    expire_lease(conn_a, job_id)

    # 3. Recovery returns the job to PENDING.
    assert recover_expired_jobs(conn_a) == {"retried": 1, "failed": 0}
    assert get_job_state(conn_a, job_id) == ("PENDING", None, None, 1)

    # 4. The same worker ID claims it again at attempt 2.
    second_claim = claim_job(conn_a, "worker-A")

    assert second_claim["id"] == job_id
    assert second_claim["attempt"] == 2

    # The new lease is valid, so if the stale call below is rejected,
    # only the attempt check can be responsible (same worker,
    # RUNNING, live lease).
    assert lease_is_live(conn_a, job_id)

    state_before = get_job_state(conn_a, job_id)

    # 5. The old execution tries to complete using attempt 1.
    completed = complete_job(
        conn_a, job_id, "worker-A", first_claim["attempt"]
    )

    # 6. PostgreSQL rejects the stale completion without changing the job.
    assert completed is False
    assert get_job_state(conn_a, job_id) == state_before

    state_b = state_before
    assert state_b[0] == "RUNNING"
    assert state_b[1] == "worker-A"
    assert state_b[2] is not None
    assert state_b[3] == 2

    # Control: the current attempt can still complete,
    # so the fence blocks only the stale token.
    assert complete_job(
        conn_a, job_id, "worker-A", second_claim["attempt"]
    ) is True

    final_state = get_job_state(conn_a, job_id)

    assert final_state[0] == "COMPLETED"
    assert final_state[1] == "worker-A"  # kept as a record of who finished it
    assert final_state[2] is None  # a completed job holds no lease
    assert final_state[3] == 2


def test_stale_attempt_cannot_fail_reclaimed_job(clean_jobs, conn_a):
    # Arrange: worker-A holds a live lease on attempt 2 of 3.
    job_id = insert_job(
        conn_a,
        status="RUNNING",
        worker_id="worker-A",
        attempt=2,
        max_attempts=3,
        lease_interval="30 seconds",
    )

    # Same worker, RUNNING, live lease: only the attempt
    # check can reject the stale request below.
    assert lease_is_live(conn_a, job_id)

    state_before = get_job_state(conn_a, job_id)

    # Act: the stale attempt-1 execution reports a failure.
    failed = fail_job(conn_a, job_id, "worker-A", 1)

    # Assert: rejected, and the job is unchanged.
    assert failed is False
    assert get_job_state(conn_a, job_id) == state_before

    status, worker_id, lease_expires_at, attempt = state_before
    assert status == "RUNNING"
    assert worker_id == "worker-A"
    assert lease_expires_at is not None
    assert attempt == 2


def test_stale_attempt_cannot_renew_lease(clean_jobs, conn_a):
    job_id = insert_job(
        conn_a,
        status="RUNNING",
        worker_id="worker-A",
        attempt=2,
        max_attempts=3,
        lease_interval="30 seconds",
    )

    assert lease_is_live(conn_a, job_id)

    state_before = get_job_state(conn_a, job_id)

    # Act: the stale attempt-1 execution tries to extend the lease.
    # A much longer lease than the current one means a wrongly
    # accepted renewal would visibly move lease_expires_at.
    renewed = renew_lease(
        conn_a, job_id, "worker-A", 1, lease_seconds=300
    )

    # Assert: rejected, and the lease deadline did not move.
    assert renewed is False
    assert get_job_state(conn_a, job_id) == state_before

    status, worker_id, lease_expires_at, attempt = state_before
    assert status == "RUNNING"
    assert worker_id == "worker-A"
    assert lease_expires_at is not None
    assert attempt == 2