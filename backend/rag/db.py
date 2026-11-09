"""PostgreSQL connection pool. Rows come back as dicts; the schema is created on first use."""
import atexit
import datetime as dt
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

SCHEMA_LOCK = 72_017_001  # advisory lock id, so processes don't create the schema at the same time


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def init_schema(database_url: str):
    sql = Path(__file__).with_name("schema.sql").read_text()
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK,))
        try:
            conn.execute(sql)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK,))


@lru_cache
def pool() -> ConnectionPool:
    url = get_settings().database_url
    init_schema(url)
    p = ConnectionPool(url, min_size=1, max_size=10, kwargs={"row_factory": dict_row, "autocommit": True},
                       open=True)
    atexit.register(p.close)  # scripts end cleanly instead of warning about pool threads
    return p


@contextmanager
def connection():
    with pool().connection() as conn:
        yield conn


def iso(value):
    """Timestamps as ISO strings in API responses."""
    return value.isoformat() if isinstance(value, dt.datetime) else value
