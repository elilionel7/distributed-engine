from engine.workers.claim_job import claim_job
from engine.workers.complete_job import complete_job
from engine.workers.recover_expired_job import recover_expired_jobs
from tests.helpers import expire_lease, get_job_state, insert_job


def record_job_effect(conn, job_id, idempotency_key, worker_id, attempt):
    """
    Simulate a NON-idempotent job handler's side effect.

    Inserts unconditionally: running it twice for the same job
    produces two effects, just like charging a card twice.

    No transaction of its own: on an autocommit connection the effect
    is final as soon as it happens. Wrap the call in conn.transaction()
    to simulate a crash before the effect commits.

    Returns the id of the new job_effects row.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_effects (
                idempotency_key,
                job_id,
                worker_id,
                attempt
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (idempotency_key, job_id, worker_id, attempt),
        )
        return cur.fetchone()[0]


def count_job_effects(conn, job_id):
    """Return the number of effects produced by this job."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM job_effects WHERE job_id = %s",
            (job_id,),
        )
        return cur.fetchone()[0]


def record_job_effect_idempotent(
    conn, job_id, idempotency_key, worker_id, attempt
):
    """
    Simulate an IDEMPOTENT job handler's side effect.

    Relies on the UNIQUE idempotency_key: a retry with the same key
    inserts nothing. Under READ COMMITTED, a concurrent insert of the
    same key waits for the other transaction, then skips if it committed.

    Returns True if the effect was performed now, False if it had
    already happened. False is success, not failure: the caller
    should still complete the job.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_effects (
                idempotency_key,
                job_id,
                worker_id,
                attempt
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            (idempotency_key, job_id, worker_id, attempt),
        )
        return cur.fetchone() is not None


def get_job_effects(conn, job_id):
    """Return (idempotency_key, worker_id, attempt) for each effect, oldest first."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT idempotency_key, worker_id, attempt
            FROM job_effects
            WHERE job_id = %s
            ORDER BY id
            """,
            (job_id,),
        )
        return cur.fetchall()


def test_job_can_execute_twice_after_worker_crash(
    clean_jobs, job_effects_table, conn_a, conn_b
):
    """
    Documents the at-least-once gap: leases, fencing and recovery
    protect the jobs row, but NOT an external side effect performed
    before the crash. A non-idempotent handler runs twice.
    """
    key = "charge-customer-42"
    job_id = insert_job(conn_a, idempotency_key=key)

    claimed_a = claim_job(conn_a, "worker-A")

    assert claimed_a["id"] == job_id
    assert claimed_a["attempt"] == 1

    # Worker A executes the job.
    record_job_effect(conn_a, job_id, key, "worker-A", claimed_a["attempt"])

    # The side effect is committed: another connection can see it.
    assert count_job_effects(conn_b, job_id) == 1

    # Worker A crashes before complete_job().
    conn_a.close()

    # The jobs table has no idea the effect happened.
    assert get_job_state(conn_b, job_id)[:2] == ("RUNNING", "worker-A")

    # No heartbeats, so the lease expires and recovery requeues the job.
    expire_lease(conn_b, job_id)
    assert recover_expired_jobs(conn_b) == {"retried": 1, "failed": 0}
    assert get_job_state(conn_b, job_id) == ("PENDING", None, None, 1)

    # Worker B claims the job as attempt 2 and executes it again.
    claimed_b = claim_job(conn_b, "worker-B")

    assert claimed_b["id"] == job_id
    assert claimed_b["attempt"] == 2

    record_job_effect(conn_b, job_id, key, "worker-B", claimed_b["attempt"])

    # From the engine's point of view, everything worked.
    assert complete_job(conn_b, job_id, "worker-B", claimed_b["attempt"]) is True

    status, worker_id, lease_expires_at, attempt = get_job_state(conn_b, job_id)
    assert status == "COMPLETED"
    assert worker_id == "worker-B"
    assert lease_expires_at is None  # complete_job clears the lease
    assert attempt == 2

    # But the side effect happened twice: same key, two attempts.
    assert count_job_effects(conn_b, job_id) == 2
    assert get_job_effects(conn_b, job_id) == [
        (key, "worker-A", 1),
        (key, "worker-B", 2),
    ]


def test_idempotent_handler_prevents_duplicate_side_effects(
    clean_jobs, unique_job_effects_table, conn_a, conn_b
):
    """
    Same crash lifecycle as the test above, but the handler is
    idempotent: the retry recognises the effect and skips it,
    giving exactly-once effects despite at-least-once execution.
    """
    key = "charge-customer-42"
    job_id = insert_job(conn_a, idempotency_key=key)

    claimed_a = claim_job(conn_a, "worker-A")

    assert claimed_a["id"] == job_id
    assert claimed_a["attempt"] == 1

    # Worker A executes the job: the effect happens and commits.
    performed = record_job_effect_idempotent(
        conn_a, job_id, key, "worker-A", claimed_a["attempt"]
    )

    assert performed is True
    assert count_job_effects(conn_b, job_id) == 1

    # Worker A crashes before complete_job().
    conn_a.close()

    # Lease expires, recovery requeues, Worker B claims attempt 2.
    expire_lease(conn_b, job_id)
    assert recover_expired_jobs(conn_b) == {"retried": 1, "failed": 0}
    assert get_job_state(conn_b, job_id) == ("PENDING", None, None, 1)

    claimed_b = claim_job(conn_b, "worker-B")

    assert claimed_b["id"] == job_id
    assert claimed_b["attempt"] == 2

    # Worker B executes again with the SAME key: nothing is inserted.
    performed_again = record_job_effect_idempotent(
        conn_b, job_id, key, "worker-B", claimed_b["attempt"]
    )

    assert performed_again is False

    # "Already done" counts as success, so B completes the job.
    assert complete_job(conn_b, job_id, "worker-B", claimed_b["attempt"]) is True

    status, worker_id, lease_expires_at, attempt = get_job_state(conn_b, job_id)
    assert status == "COMPLETED"
    assert worker_id == "worker-B"
    assert lease_expires_at is None  # complete_job clears the lease
    assert attempt == 2

    # Exactly one effect, and it's Worker A's original one.
    assert count_job_effects(conn_b, job_id) == 1
    assert get_job_effects(conn_b, job_id) == [(key, "worker-A", 1)]
