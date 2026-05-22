from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as PgConnection

from app.db.repositories import users_repo


def get_or_create_user(
    conn: PgConnection,
    channel: str,
    external_id: str,
    name: str | None,
    seen_at: datetime,
) -> tuple[dict[str, Any], bool]:
    user = users_repo.find_by_external_id(conn, channel, external_id)
    if user:
        users_repo.touch(conn, user["id"], name, seen_at)
        return user, False
    return users_repo.create(conn, channel, external_id, name, seen_at), True
