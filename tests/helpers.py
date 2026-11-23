"""Database helpers shared by integration and fault-injection tests."""

import uuid


def insert_job(
    conn,
    status="PENDING",
    worker_id=None,
    attempt=0,
    max_attempts=3,
    lease_interval=None,
):
    """
    Insert a job and return its id.

    Defaults describe a freshly submitted job: PENDING, no owner,
    no lease, attempt 0. Override them to build other states.

    lease_interval is a Postgres interval relative to NOW(),
    e.g. '30 seconds' for a live lease or '-1 second' for an
    expired one. None means no lease.
    """
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
                str(uuid.uuid4()),
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
