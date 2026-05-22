from contextlib import contextmanager
from pathlib import Path
import time
from typing import Generator

import psycopg2
from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import RealDictCursor

from app.core.config import get_settings


def connect() -> PgConnection:
    settings = get_settings()
    sslrootcert = Path(settings.db_sslrootcert).expanduser()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return psycopg2.connect(
                host=settings.db_host,
                port=settings.db_port,
                dbname=settings.db_name,
                user=settings.db_user,
                password=settings.db_password,
                sslmode=settings.db_sslmode,
                sslrootcert=str(sslrootcert),
                target_session_attrs=settings.db_target_session_attrs,
                connect_timeout=settings.db_connect_timeout,
                cursor_factory=RealDictCursor,
            )
        except psycopg2.OperationalError as exc:
            last_error = exc
            if attempt == 2:
                raise
            time.sleep(1 + attempt)
    raise last_error or RuntimeError("Database connection failed")


@contextmanager
def get_connection() -> Generator[PgConnection, None, None]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
