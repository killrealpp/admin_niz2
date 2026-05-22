"""Print YCLIENTS service and staff ids without exposing tokens."""

import sys
from pathlib import Path
from pprint import pprint

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.logger import setup_logging  # noqa: E402
from app.integrations.yclients_client import YClientsClient  # noqa: E402


def compact_item(item: dict) -> dict:
    keys = (
        "id",
        "title",
        "name",
        "price_min",
        "price_max",
        "duration",
        "duration_min",
        "duration_max",
        "category_id",
        "specialization",
    )
    return {key: item.get(key) for key in keys if key in item}


def main() -> None:
    setup_logging()
    client = YClientsClient()

    print("YCLIENTS services:")
    for item in client.get_book_services():
        pprint(compact_item(item), sort_dicts=False)

    print("\nYCLIENTS staff/resources:")
    for item in client.get_book_staff():
        pprint(compact_item(item), sort_dicts=False)


if __name__ == "__main__":
    main()
