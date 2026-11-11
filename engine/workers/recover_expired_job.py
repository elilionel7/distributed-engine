def recover_expired_jobs(conn):
    """
    Find RUNNING jobs with expired leases.

    Jobs with attempts remaining go back to PENDING
    so another worker can claim them. Jobs that have
    used all their attempts become FAILED.

    Return counts of retried and failed jobs.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET
                    status = CASE
                        WHEN attempt < max_attempts THEN 'PENDING'
                        ELSE 'FAILED'
                    END,
                    worker_id = NULL,
                    lease_expires_at = NULL
                WHERE status = 'RUNNING'
                    AND lease_expires_at <= NOW()
                RETURNING id, status, attempt;
                """
            )
            rows = cur.fetchall()

    retried = sum(1 for _, status, _ in rows if status == 'PENDING')
    failed = sum(1 for _, status, _ in rows if status == 'FAILED')

    return {"retried": retried, "failed": failed}
