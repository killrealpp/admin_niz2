from contextlib import contextmanager
import logging
from pathlib import Path
import time
from typing import Generator

import psycopg2
from psycopg2 import pool
from psycopg2 import InterfaceError
from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import RealDictCursor

from app.core.config import get_settings
from app.services.dialog.performance import trace_span

logger = logging.getLogger(__name__)
_connection_pool: pool.ThreadedConnectionPool | None = None


def _connect_kwargs() -> dict:
    settings = get_settings()
    sslrootcert = Path(settings.db_sslrootcert).expanduser()
    return {
        "host": settings.db_host,
        "port": settings.db_port,
        "dbname": settings.db_name,
        "user": settings.db_user,
        "password": settings.db_password,
        "sslmode": settings.db_sslmode,
        "sslrootcert": str(sslrootcert),
        "target_session_attrs": settings.db_target_session_attrs,
        "connect_timeout": settings.db_connect_timeout,
        "cursor_factory": RealDictCursor,
    }


def connect() -> PgConnection:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with trace_span("db.connect"):
                return psycopg2.connect(**_connect_kwargs())
        except psycopg2.OperationalError as exc:
            last_error = exc
            logger.warning("Database connection attempt failed attempt=%s error=%s", attempt + 1, exc)
            if attempt == 2:
                raise
            with trace_span("db.connect_retry_sleep"):
                time.sleep(1 + attempt)
    raise last_error or RuntimeError("Database connection failed")


def _get_pool() -> pool.ThreadedConnectionPool | None:
    global _connection_pool
    settings = get_settings()
    if not settings.db_pool_enabled:
        return None
    if _connection_pool is None:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with trace_span("db.pool.init"):
                    _connection_pool = pool.ThreadedConnectionPool(
                        max(1, settings.db_pool_min),
                        max(settings.db_pool_min, settings.db_pool_max),
                        **_connect_kwargs(),
                    )
                break
            except psycopg2.OperationalError as exc:
                last_error = exc
                logger.warning("Database pool init failed attempt=%s error=%s", attempt + 1, exc)
                if attempt == 2:
                    logger.warning("Database pool init failed, falling back to direct connections")
                    return None
                with trace_span("db.connect_retry_sleep"):
                    time.sleep(1 + attempt)
        if _connection_pool is None:
            raise last_error or RuntimeError("Database pool init failed")
    return _connection_pool


def _checkout_connection() -> tuple[PgConnection, bool]:
    db_pool = _get_pool()
    if not db_pool:
        return connect(), False
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with trace_span("db.pool.checkout"):
                conn = db_pool.getconn()
                if conn.closed:
                    db_pool.putconn(conn, close=True)
                    raise psycopg2.OperationalError("Database pool returned a closed connection")
                return conn, True
        except psycopg2.OperationalError as exc:
            last_error = exc
            logger.warning("Database pool checkout failed attempt=%s error=%s", attempt + 1, exc)
            if attempt == 2:
                raise
            with trace_span("db.connect_retry_sleep"):
                time.sleep(1 + attempt)
    raise last_error or RuntimeError("Database pool checkout failed")


def _release_connection(conn: PgConnection, pooled: bool) -> None:
    if not pooled:
        conn.close()
        return
    db_pool = _get_pool()
    if not db_pool:
        conn.close()
        return
    db_pool.putconn(conn, close=bool(conn.closed))


@contextmanager
def get_connection() -> Generator[PgConnection, None, None]:
    conn, pooled = _checkout_connection()
    try:
        with trace_span("db.work"):
            yield conn
        with trace_span("db.commit"):
            conn.commit()
    except Exception:
        if not conn.closed:
            try:
                with trace_span("db.rollback"):
                    conn.rollback()
            except InterfaceError:
                logger.warning("Database rollback skipped because connection is already closed")
        raise
    finally:
        with trace_span("db.close"):
            _release_connection(conn, pooled)
