import uuid

from engine.workers.claim_job import claim_job


def insert_pending_job(conn, created_at=None):
    """Insert a PENDING job. created_at defaults to NOW()."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jobs (idempotency_key, payload, created_at)
            VALUES (%s, '{}', COALESCE(%s, NOW()))
            RETURNING id
            """,
            (str(uuid.uuid4()), created_at),
        )
        return cur.fetchone()[0]


def get_job_state(conn, job_id):
    """Return (status, worker_id, attempt) for one job."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, worker_id, attempt FROM jobs WHERE id = %s",
            (job_id,),
        )
        return cur.fetchone()


def test_only_one_worker_claims_a_single_job(clean_jobs, conn_a, conn_b):
    job_id = insert_pending_job(conn_a)

    # Hold A's transaction open so its row lock is still held
    # while B tries to claim.
    with conn_a.transaction():
        job_a = claim_job(conn_a, "worker-A")
        job_b = claim_job(conn_b, "worker-B")

        assert job_a is not None
        assert job_a["id"] == job_id
        assert job_b is None

    # A's transaction has committed; the job belongs to A.
    assert get_job_state(conn_b, job_id) == ("RUNNING", "worker-A", 1)


def test_workers_claim_different_jobs(clean_jobs, conn_a, conn_b):
    job_1 = insert_pending_job(conn_a)
    job_2 = insert_pending_job(conn_a)

    with conn_a.transaction():
        claimed_a = claim_job(conn_a, "worker-A")

        # Worker A's transaction is still open.
        # Worker B should skip the locked job.
        claimed_b = claim_job(conn_b, "worker-B")

        assert claimed_a is not None
        # B got a job while A still held its lock: it skipped
        # the locked row instead of waiting for it.
        assert claimed_b is not None

        # Together the workers claimed exactly the two jobs,
        # with no job claimed twice.
        assert {claimed_a["id"], claimed_b["id"]} == {job_1, job_2}

    # Both claims are committed, each owned by the worker that claimed it.
    assert get_job_state(conn_b, claimed_a["id"]) == ("RUNNING", "worker-A", 1)
    assert get_job_state(conn_b, claimed_b["id"]) == ("RUNNING", "worker-B", 1)


def test_claim_job_takes_oldest_pending_job_first(clean_jobs, conn_a):
    # Insert the NEWER job first, so the test can't pass just
    # because of insertion order.
    newer_job = insert_pending_job(conn_a, created_at="2026-01-01 12:00:00+00")
    older_job = insert_pending_job(conn_a, created_at="2026-01-01 11:00:00+00")

    first = claim_job(conn_a, "worker-A")
    second = claim_job(conn_a, "worker-A")

    assert first["id"] == older_job
    assert second["id"] == newer_job
