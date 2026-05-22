"""Apply SQL migrations. Usage: python scripts/init_db.py"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.logger import setup_logging  # noqa: E402
from app.db.connection import connect  # noqa: E402


def main() -> None:
    setup_logging()
    settings = get_settings()
    migration = ROOT / "app" / "db" / "migrations" / "001_init.sql"
    sql = migration.read_text(encoding="utf-8")

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print(f"OK: migration applied to {settings.db_host}/{settings.db_name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
