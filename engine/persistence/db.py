import os
import psycopg


def get_test_connection():
    database_url = os.environ["TEST_DATABASE_URL"]

    if database_url.rsplit("/", 1)[-1].split("?", 1)[0] != "distributed_engine_test":
        raise ValueError("Refusing to connect to a non-test database")

    return psycopg.connect(database_url)