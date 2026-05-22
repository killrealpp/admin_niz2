from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import get_connection
from app.services.payment_service import sync_payment_statuses
from app.services.yclients_record_service import create_missing_yclients_records


def main() -> None:
    with get_connection() as conn:
        result = sync_payment_statuses(conn)
        yclients_result = create_missing_yclients_records(conn)
    print({**result, "yclients": yclients_result})


if __name__ == "__main__":
    main()
