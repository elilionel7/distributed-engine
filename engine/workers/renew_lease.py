def renew_lease(conn, job_id, worker_id, attempt, lease_seconds=30):
    """
    Extend a job's lease to `lease_seconds` from now,
    only if the worker still owns it.

    Return True if renewed, False otherwise.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET lease_expires_at = NOW() + make_interval(secs => %s)
                WHERE id = %s
                    AND status = 'RUNNING'
                    AND worker_id = %s
                    AND attempt = %s
                    AND lease_expires_at > NOW()
                RETURNING id;
                """,
                (lease_seconds, job_id, worker_id, attempt)
            )
            result = cur.fetchone()

    return result is not None
