import uuid

from engine.workers.fail_job import fail_job


def test_fail_job_requeues_when_attempts_remain(rollback_conn):
    with rollback_conn.cursor() as cur:
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
                %s,
                '{}',
                'RUNNING',
                2,
                3,
                'worker-1',
                NOW() + INTERVAL '30 seconds'
            )
            RETURNING id
            """,
            (str(uuid.uuid4()),),
        )

        job_id = cur.fetchone()[0]

    recorded = fail_job(rollback_conn, job_id, "worker-1", 2)

    assert recorded is True

    with rollback_conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, worker_id, lease_expires_at, attempt
            FROM jobs
            WHERE id = %s
            """,
            (job_id,),
        )

        status, worker_id, lease_expires_at, attempt = cur.fetchone()

    assert status == "PENDING"
    assert worker_id is None
    assert lease_expires_at is None
    assert attempt == 2


def test_fail_job_marks_failed_at_max_attempts(rollback_conn):
    # 1. Insert a RUNNING job on its last attempt
    with rollback_conn.cursor() as cur:
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
                %s,
                '{}',
                'RUNNING',
                3,
                3,
                'worker-1',
                NOW() + INTERVAL '30 seconds'
            )
            RETURNING id
            """,
            (str(uuid.uuid4()),),
        )

        job_id = cur.fetchone()[0]

    # 2. Report the failure
    recorded = fail_job(rollback_conn, job_id, "worker-1", 3)

    assert recorded is True

    # 3. Query the updated job
    with rollback_conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, worker_id, lease_expires_at, attempt
            FROM jobs
            WHERE id = %s
            """,
            (job_id,),
        )

        status, worker_id, lease_expires_at, attempt = cur.fetchone()

    # 4. Assert the job is permanently failed
    assert status == "FAILED"
    assert worker_id is None
    assert lease_expires_at is None
    assert attempt == 3
