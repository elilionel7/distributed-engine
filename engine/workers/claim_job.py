from psycopg.rows import dict_row


def claim_job(conn, worker_id, lease_seconds=30):
    """
    Atomically claim one pending job.

    The lease lasts `lease_seconds`; the worker must
    renew it before then or the job can be recovered.

    Returns:
        Claimed job as a dict with keys
        id, payload, attempt, lease_expires_at,
        or None if no job is available.
    """

    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                WITH next_job AS (
                    SELECT id
                    FROM jobs
                    WHERE status = 'PENDING'
                        AND attempt < max_attempts
                    ORDER BY created_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE jobs
                SET
                    status = 'RUNNING',
                    worker_id = %s,
                    attempt = attempt + 1,
                    lease_expires_at =
                        NOW() + make_interval(secs => %s)
                WHERE id = (SELECT id FROM next_job)
                RETURNING
                    id,
                    payload,
                    attempt,
                    lease_expires_at;
                """,
                (worker_id, lease_seconds)
            )

            job = cur.fetchone()

    return job
