import os

import psycopg
import pytest


def database_url():
    return os.environ["TEST_DATABASE_URL"]


@pytest.fixture
def rollback_conn():
    """
    Single connection for tests that never need to commit.

    Everything runs inside an outer transaction that is always
    rolled back, so worker functions' conn.transaction() blocks
    become savepoints and nothing is left in the database.
    """
    connection = psycopg.connect(database_url())

    try:
        with connection.transaction(force_rollback=True):
            yield connection
    finally:
        connection.close()


@pytest.fixture
def clean_jobs():
    """
    Empty the jobs table before and after the test.

    Test database only. Request it FIRST in the test's parameters
    so its teardown runs after conn_a/conn_b have closed; otherwise
    TRUNCATE could wait on their locks.
    """
    with psycopg.connect(database_url(), autocommit=True) as admin:
        admin.execute("TRUNCATE jobs")
        yield
        admin.execute("TRUNCATE jobs")


@pytest.fixture
def conn_a():
    """Autocommit connection for worker A in concurrency tests."""
    with psycopg.connect(database_url(), autocommit=True) as connection:
        yield connection


@pytest.fixture
def conn_b():
    """Autocommit connection for worker B in concurrency tests."""
    with psycopg.connect(database_url(), autocommit=True) as connection:
        # If SKIP LOCKED were missing, B would block forever.
        # Fail fast instead of hanging the test run.
        connection.execute("SET lock_timeout = '2s'")
        yield connection


@pytest.fixture
def conn_monitor():
    """
    Autocommit connection for observing other sessions
    (e.g. checking pg_stat_activity to see whether a connection
    is waiting on a lock). Never used to run worker code.
    """
    with psycopg.connect(database_url(), autocommit=True) as connection:
        yield connection
