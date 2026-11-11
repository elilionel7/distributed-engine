def complete_job(conn, job_id, worker_id, attempt):
    """
    Mark a job as COMPLETED only if
    the caller still owns a valid lease.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = 'COMPLETED'
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