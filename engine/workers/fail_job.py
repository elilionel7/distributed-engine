
def fail_job(conn, job_id, worker_id, attempt):
    """
    Record a failed execution attempt.

    Return True if the failure was recorded,
    False if ownership was lost.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET
                    status = CASE
                        WHEN attempt >= max_attempts
                            THEN 'FAILED'
                        ELSE 'PENDING'
                    END,
                    worker_id = NULL,
                    lease_expires_at = NULL
                WHERE id = %s
                    AND status = 'RUNNING'
                    AND worker_id = %s
                    AND attempt = %s
                    AND lease_expires_at > NOW()
                RETURNING id;
                """,
                (job_id, worker_id, attempt)
            )

            result = cur.fetchone()

    return result is not None
