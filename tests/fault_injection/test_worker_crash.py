import pytest

from engine.workers.claim_job import claim_job
from engine.workers.recover_expired_job import recover_expired_jobs
from tests.helpers import expire_lease, get_job_state, insert_job


def test_worker_crash_before_claim_commit(clean_jobs, conn_a, conn_b):
    # Committed immediately (conn_a is autocommit), so it survives
    # the rollback below. Only the claim is inside the transaction.
    job_id = insert_job(conn_a)

    # Worker A claims inside an outer transaction. claim_job()'s own
    # conn.transaction() becomes a savepoint, so nothing commits yet.
    with pytest.raises(RuntimeError):
        with conn_a.transaction():
            claimed = claim_job(conn_a, "worker-A")

            assert claimed["id"] == job_id
            assert claimed["attempt"] == 1

            # Simulate worker crash before the claim commits.
            raise RuntimeError("Worker crashed")

    # The transaction was rolled back. Inspect from conn_b to prove
    # this is the state other connections see, not just Worker A's.
    assert get_job_state(conn_b, job_id) == ("PENDING", None, None, 0)

    # Worker B can now claim the job.
    claimed_b = claim_job(conn_b, "worker-B")

    assert claimed_b["id"] == job_id
    assert claimed_b["attempt"] == 1  # A's crashed claim didn't consume an attempt

    status, worker_id, lease_expires_at, attempt = get_job_state(conn_b, job_id)
    assert status == "RUNNING"
    assert worker_id == "worker-B"
    assert lease_expires_at is not None
    assert attempt == 1


def test_worker_crash_after_claim_commit(clean_jobs, conn_a, conn_b):
    job_id = insert_job(conn_a)

    # 1. Worker A claims the job and commits (conn_a is autocommit).
    claimed_a = claim_job(conn_a, "worker-A")

    assert claimed_a["id"] == job_id
    assert claimed_a["attempt"] == 1

    # 2-3. Worker A crashes before completing: its connection is gone,
    # so it can never complete, fail or renew (no more heartbeats).
    conn_a.close()

    # The claim was committed, so the crash does NOT undo it.
    # Unlike a crash before commit, the job stays RUNNING and owned
    # by the dead worker until something else intervenes.
    status, worker_id, lease_expires_at, attempt = get_job_state(conn_b, job_id)
    assert status == "RUNNING"
    assert worker_id == "worker-A"
    assert lease_expires_at is not None
    assert attempt == 1

    # While the lease is still live, recovery must leave the job alone:
    # it can't tell a crashed worker from a slow one yet.
    assert recover_expired_jobs(conn_b) == {"retried": 0, "failed": 0}
    assert get_job_state(conn_b, job_id)[:2] == ("RUNNING", "worker-A")

    # ...and Worker B can't take it either.
    assert claim_job(conn_b, "worker-B") is None

    # 4. With no heartbeats, the lease runs out.
    # Backdate it instead of sleeping for the full lease.
    expire_lease(conn_b, job_id)

    # 5. Recovery returns the job to PENDING, keeping the attempt count.
    assert recover_expired_jobs(conn_b) == {"retried": 1, "failed": 0}
    assert get_job_state(conn_b, job_id) == ("PENDING", None, None, 1)

    # 6. Worker B claims the recovered job as a new attempt.
    claimed_b = claim_job(conn_b, "worker-B")

    assert claimed_b["id"] == job_id
    assert claimed_b["attempt"] == 2  # A's committed claim did consume an attempt

    status, worker_id, lease_expires_at, attempt = get_job_state(conn_b, job_id)
    assert status == "RUNNING"
    assert worker_id == "worker-B"
    assert lease_expires_at is not None
    assert attempt == 2
