"""Register YooKassa webhooks from YOOKASSA_WEBHOOK_URL.

Usage:
    python scripts/register_yookassa_webhook.py
"""

import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.integrations.yookassa_client import YooKassaClient  # noqa: E402


def main() -> None:
    settings = get_settings()
    if not settings.yookassa_webhook_url:
        raise SystemExit("YOOKASSA_WEBHOOK_URL is empty")
    parsed = urlparse(settings.yookassa_webhook_url)
    if parsed.scheme != "https" or parsed.path.rstrip("/") != settings.yookassa_webhook_path.rstrip("/"):
        raise SystemExit(
            "YOOKASSA_WEBHOOK_URL must be a public HTTPS URL ending with "
            f"{settings.yookassa_webhook_path!r}. Current value: {settings.yookassa_webhook_url}"
        )
    client = YooKassaClient()
    for event in ("payment.succeeded", "payment.canceled"):
        response = client.create_webhook(event=event, url=settings.yookassa_webhook_url)
        print(f"{event}: {response}")


if __name__ == "__main__":
    main()
