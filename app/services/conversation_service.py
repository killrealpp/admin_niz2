from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection

from app.db.repositories import conversations_repo


def get_or_create_conversation(
    conn: PgConnection,
    user_id: int,
    channel: str,
    now: datetime,
    ttl_hours: int,
) -> tuple[dict[str, Any], bool]:
    conversations_repo.expire_stale(conn, user_id, ttl_hours, now)
    active = conversations_repo.find_active_for_user(conn, user_id, ttl_hours, now)
    if active:
        return active, False
    return conversations_repo.create(conn, user_id, channel, now), True
