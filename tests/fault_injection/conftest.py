import os

import psycopg
import pytest


@pytest.fixture
def job_effects_table():
    """
    Create a job_effects table for the test and drop it afterward.

    Each row stands in for an external side effect (e.g. a charge).
    idempotency_key is deliberately NOT unique, so tests can show
    duplicate side effects from a non-idempotent handler.

    No foreign key to jobs: clean_jobs runs TRUNCATE jobs, which
    Postgres refuses on a table referenced by a foreign key.

    Request it FIRST in the test's parameters (like clean_jobs) so its
    teardown runs after conn_a/conn_b have closed; otherwise DROP TABLE
    could wait on their locks.
    """
    with psycopg.connect(
        os.environ["TEST_DATABASE_URL"], autocommit=True
    ) as admin:
        # Clear out a table left behind by an interrupted run.
        admin.execute("DROP TABLE IF EXISTS job_effects")
        admin.execute(
            """
            CREATE TABLE job_effects (
                id BIGSERIAL PRIMARY KEY,
                idempotency_key TEXT NOT NULL,
                job_id UUID NOT NULL,
                worker_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

        try:
            yield
        finally:
            admin.execute("DROP TABLE IF EXISTS job_effects")

