from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.config import get_settings, sqlite_path


T_CONVERSATIONS = "mvp_conversations"
T_MESSAGES = "mvp_messages"
T_BOOKINGS = "mvp_bookings"
T_SLOT_HOLDS = "mvp_slot_holds"
T_SYSTEM_LOGS = "mvp_system_logs"
T_ADMIN_NOTIFICATIONS = "mvp_admin_notifications"
T_AVAILABILITY_CACHE = "mvp_availability_cache"


def _use_postgres() -> bool:
    settings = get_settings()
    return bool(settings.db_host and settings.db_name and settings.db_user)


def init_db() -> None:
    if _use_postgres():
        _init_postgres()
        return
    path = sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_conversations (
                chat_id TEXT PRIMARY KEY,
                draft_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                current_step TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        _add_column(conn, T_CONVERSATIONS, "status", "TEXT NOT NULL DEFAULT 'active'")
        _add_column(conn, T_CONVERSATIONS, "current_step", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                text TEXT NOT NULL,
                raw_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                draft_json TEXT NOT NULL,
                status TEXT NOT NULL,
                payment_id TEXT,
                yclients_record_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_slot_holds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                service_type TEXT NOT NULL,
                service_variant TEXT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                duration REAL,
                status TEXT NOT NULL DEFAULT 'active',
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                event TEXT NOT NULL,
                message TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_admin_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                sent_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_availability_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_type TEXT NOT NULL,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT,
                service_id TEXT NOT NULL,
                staff_id TEXT NOT NULL,
                status TEXT NOT NULL,
                refreshed_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mvp_availability_lookup ON mvp_availability_cache(staff_id, service_id, date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mvp_availability_filter ON mvp_availability_cache(service_type, date)")
        conn.commit()


def _init_postgres() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_conversations (
                chat_id TEXT PRIMARY KEY,
                draft_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                current_step TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("ALTER TABLE mvp_conversations ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")
        conn.execute("ALTER TABLE mvp_conversations ADD COLUMN IF NOT EXISTS current_step TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_messages (
                id BIGSERIAL PRIMARY KEY,
                chat_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                text TEXT NOT NULL,
                raw_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_bookings (
                id BIGSERIAL PRIMARY KEY,
                chat_id TEXT NOT NULL,
                draft_json TEXT NOT NULL,
                status TEXT NOT NULL,
                payment_id TEXT,
                yclients_record_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_slot_holds (
                id BIGSERIAL PRIMARY KEY,
                chat_id TEXT NOT NULL,
                service_type TEXT NOT NULL,
                service_variant TEXT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                duration DOUBLE PRECISION,
                status TEXT NOT NULL DEFAULT 'active',
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_system_logs (
                id BIGSERIAL PRIMARY KEY,
                level TEXT NOT NULL,
                event TEXT NOT NULL,
                message TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_admin_notifications (
                id BIGSERIAL PRIMARY KEY,
                chat_id TEXT,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                sent_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mvp_availability_cache (
                id BIGSERIAL PRIMARY KEY,
                service_type TEXT NOT NULL,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT,
                service_id TEXT NOT NULL,
                staff_id TEXT NOT NULL,
                status TEXT NOT NULL,
                refreshed_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mvp_availability_lookup ON mvp_availability_cache(staff_id, service_id, date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mvp_availability_filter ON mvp_availability_cache(service_type, date)")


def _add_column(conn: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _postgres_kwargs() -> dict[str, Any]:
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "host": settings.db_host,
        "port": settings.db_port,
        "dbname": settings.db_name,
        "user": settings.db_user,
        "password": settings.db_password,
        "connect_timeout": settings.db_connect_timeout,
        "cursor_factory": RealDictCursor,
    }
    if settings.db_sslmode:
        kwargs["sslmode"] = settings.db_sslmode
    if settings.db_sslmode in {"verify-ca", "verify-full"} and settings.db_sslrootcert:
        kwargs["sslrootcert"] = str(Path(settings.db_sslrootcert).expanduser())
    if settings.db_target_session_attrs:
        kwargs["target_session_attrs"] = settings.db_target_session_attrs
    return kwargs


class _PostgresConnection:
    def __init__(self) -> None:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                self._conn = psycopg2.connect(**_postgres_kwargs())
                return
            except psycopg2.OperationalError as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
        raise last_error or RuntimeError("Postgres connection failed")

    def execute(self, query: str, params: Any = None):
        cur = self._conn.cursor()
        cur.execute(_pg_query(query), params)
        return cur

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _pg_query(query: str) -> str:
    return query.replace("?", "%s")


@contextmanager
def connect() -> Iterator[Any]:
    if _use_postgres():
        conn = _PostgresConnection()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
        return
    conn = sqlite3.connect(sqlite_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def load_draft(chat_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(f"SELECT draft_json FROM {T_CONVERSATIONS} WHERE chat_id = ?", (chat_id,)).fetchone()
    return json.loads(row["draft_json"]) if row else {}


def save_draft(chat_id: str, draft: dict, *, status: str = "active", current_step: str | None = None) -> None:
    now = datetime.utcnow().isoformat()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO mvp_conversations(chat_id, draft_json, status, current_step, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                draft_json = excluded.draft_json,
                status = excluded.status,
                current_step = excluded.current_step,
                updated_at = excluded.updated_at
            """,
            (chat_id, json.dumps(draft, ensure_ascii=False), status, current_step, now),
        )


def add_message(chat_id: str, sender: str, text: str, raw: dict | None = None) -> None:
    now = datetime.utcnow().isoformat()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO mvp_messages(chat_id, sender, text, raw_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, sender, text, json.dumps(raw or {}, ensure_ascii=False), now),
        )


def list_recent_messages(chat_id: str, *, limit: int = 12) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT sender, text, created_at
            FROM {T_MESSAGES}
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()
    return list(reversed([dict(row) for row in rows]))


def clear_messages(chat_id: str) -> None:
    with connect() as conn:
        conn.execute(f"DELETE FROM {T_MESSAGES} WHERE chat_id = ?", (chat_id,))


def create_booking(chat_id: str, draft: dict, status: str) -> int:
    now = datetime.utcnow().isoformat()
    with connect() as conn:
        query = """
            INSERT INTO mvp_bookings(chat_id, draft_json, status, payment_id, yclients_record_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        if _use_postgres():
            query += " RETURNING id"
        cur = conn.execute(
            query,
            (
                    chat_id,
                    json.dumps(draft, ensure_ascii=False),
                    status,
                    draft.get("payment_id"),
                    draft.get("yclients_record_id"),
                    now,
                    now,
                ),
            )
        if _use_postgres():
            row = cur.fetchone()
            return int(row["id"])
        return int(cur.lastrowid)


def update_booking(booking_id: int, draft: dict, status: str | None = None) -> None:
    now = datetime.utcnow().isoformat()
    with connect() as conn:
        conn.execute(
            """
            UPDATE mvp_bookings
            SET draft_json = ?, status = COALESCE(?, status), payment_id = ?, yclients_record_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(draft, ensure_ascii=False),
                status,
                draft.get("payment_id"),
                draft.get("yclients_record_id"),
                now,
                booking_id,
            ),
        )


def list_pending_payments() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM {T_BOOKINGS} WHERE status = 'waiting_payment' AND payment_id IS NOT NULL ORDER BY id ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def latest_booking(chat_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            f"SELECT * FROM {T_BOOKINGS} WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
    return dict(row) if row else None


def expire_holds() -> None:
    now = datetime.utcnow().isoformat()
    with connect() as conn:
        conn.execute(
            f"UPDATE {T_SLOT_HOLDS} SET status = 'expired', updated_at = ? WHERE status = 'active' AND expires_at <= ?",
            (now, now),
        )


def active_hold_exists(draft: dict, *, ignore_chat_id: str | None = None) -> bool:
    expire_holds()
    with connect() as conn:
        params = [
            draft.get("service_type"),
            draft.get("date"),
            draft.get("time"),
            float(draft.get("duration") or 0),
            draft.get("service_variant"),
        ]
        query = """
            SELECT 1 FROM mvp_slot_holds
            WHERE status = 'active'
              AND service_type = ?
              AND date = ?
              AND time = ?
              AND COALESCE(duration, 0) = ?
              AND COALESCE(service_variant, '') = COALESCE(?, '')
        """
        if ignore_chat_id:
            query += " AND chat_id != ?"
            params.append(ignore_chat_id)
        return conn.execute(query, params).fetchone() is not None


def upsert_hold(chat_id: str, draft: dict) -> None:
    expire_holds()
    now = datetime.utcnow()
    expires_at = now + timedelta(minutes=get_settings().hold_ttl_minutes)
    with connect() as conn:
        conn.execute(
            f"UPDATE {T_SLOT_HOLDS} SET status = 'released', updated_at = ? WHERE chat_id = ? AND status = 'active'",
            (now.isoformat(), chat_id),
        )
        conn.execute(
            """
            INSERT INTO mvp_slot_holds(chat_id, service_type, service_variant, date, time, duration, status, expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                chat_id,
                draft.get("service_type"),
                draft.get("service_variant"),
                draft.get("date"),
                draft.get("time"),
                draft.get("duration"),
                expires_at.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )


def convert_hold(chat_id: str) -> None:
    now = datetime.utcnow().isoformat()
    with connect() as conn:
        conn.execute(
            f"UPDATE {T_SLOT_HOLDS} SET status = 'converted', updated_at = ? WHERE chat_id = ? AND status = 'active'",
            (now, chat_id),
        )


def release_holds(chat_id: str) -> None:
    now = datetime.utcnow().isoformat()
    with connect() as conn:
        conn.execute(
            f"UPDATE {T_SLOT_HOLDS} SET status = 'released', updated_at = ? WHERE chat_id = ? AND status = 'active'",
            (now, chat_id),
        )


def log_system(level: str, event: str, message: str = "", payload: dict | None = None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO mvp_system_logs(level, event, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (level, event, message, json.dumps(payload or {}, ensure_ascii=False), datetime.utcnow().isoformat()),
        )


def enqueue_admin_notification(message: str, chat_id: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO mvp_admin_notifications(chat_id, message, status, created_at)
            VALUES (?, ?, 'pending', ?)
            """,
            (chat_id, message, datetime.utcnow().isoformat()),
        )


def list_pending_admin_notifications(limit: int = 20) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM {T_ADMIN_NOTIFICATIONS} WHERE status = 'pending' ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_admin_notification_sent(notification_id: int) -> None:
    with connect() as conn:
        conn.execute(
            f"UPDATE {T_ADMIN_NOTIFICATIONS} SET status = 'sent', sent_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), notification_id),
        )


def replace_availability_cache(rows: list[dict[str, Any]], *, refreshed_at: str | None = None) -> None:
    refreshed_at = refreshed_at or datetime.utcnow().isoformat()
    with connect() as conn:
        conn.execute(f"DELETE FROM {T_AVAILABILITY_CACHE}")
        for row in rows:
            conn.execute(
                f"""
                INSERT INTO {T_AVAILABILITY_CACHE}
                    (service_type, title, date, time, service_id, staff_id, status, refreshed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("service_type") or "",
                    row.get("title") or "",
                    row.get("date") or "",
                    row.get("time") or None,
                    row.get("service_id") or "",
                    row.get("staff_id") or "",
                    row.get("status") or "",
                    refreshed_at,
                ),
            )


def availability_date_exists(date: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            f"SELECT 1 FROM {T_AVAILABILITY_CACHE} WHERE date = ? LIMIT 1",
            (date,),
        ).fetchone()
    return row is not None


def replace_availability_cache_for_date(
    date: str,
    rows: list[dict[str, Any]],
    *,
    refreshed_at: str | None = None,
) -> None:
    refreshed_at = refreshed_at or datetime.utcnow().isoformat()
    with connect() as conn:
        conn.execute(f"DELETE FROM {T_AVAILABILITY_CACHE} WHERE date = ?", (date,))
        for row in rows:
            conn.execute(
                f"""
                INSERT INTO {T_AVAILABILITY_CACHE}
                    (service_type, title, date, time, service_id, staff_id, status, refreshed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("service_type") or "",
                    row.get("title") or "",
                    row.get("date") or date,
                    row.get("time") or None,
                    row.get("service_id") or "",
                    row.get("staff_id") or "",
                    row.get("status") or "",
                    refreshed_at,
                ),
            )


def availability_cache_age_seconds() -> float | None:
    with connect() as conn:
        row = conn.execute(f"SELECT MAX(refreshed_at) AS refreshed_at FROM {T_AVAILABILITY_CACHE}").fetchone()
    value = row["refreshed_at"] if row else None
    if not value:
        return None
    try:
        refreshed_at = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return max(0.0, (datetime.utcnow() - refreshed_at).total_seconds())


def get_availability_times(*, staff_id: str, service_id: str, date: str) -> tuple[bool, list[str]]:
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT time, status
            FROM {T_AVAILABILITY_CACHE}
            WHERE staff_id = ? AND service_id = ? AND date = ?
            """,
            (str(staff_id), str(service_id), str(date)),
        ).fetchall()
    if not rows:
        return False, []
    times = sorted({str(row["time"]) for row in rows if row["status"] != "empty" and row["time"]})
    return True, times


def list_availability_rows(
    *,
    service_type: str | None = None,
    date: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    params: list[Any] = []
    where: list[str] = []
    if service_type:
        where.append("service_type = ?")
        params.append(service_type)
    if date:
        where.append("date = ?")
        params.append(date)
    query = f"SELECT * FROM {T_AVAILABILITY_CACHE}"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY date ASC, title ASC, time ASC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
