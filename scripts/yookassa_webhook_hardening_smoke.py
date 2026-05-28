"""Smoke-test YooKassa webhook request hardening without external side effects."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import yookassa_webhook_runner as runner  # noqa: E402


@dataclass
class FakeSettings:
    app_env: str = "local"
    yookassa_webhook_enabled: bool = True
    yookassa_webhook_host: str = "127.0.0.1"
    yookassa_webhook_port: int = 0
    yookassa_webhook_path: str = "/webhooks/yookassa"
    yookassa_webhook_secret: str = "secret"
    yookassa_webhook_max_body_bytes: int = 128


class DummyConnection:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_exc: object) -> None:
        return None


def request_json(url: str, *, method: str = "GET", payload: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers=headers or {})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def main() -> None:
    original_get_settings = runner.get_settings
    original_get_connection = runner.get_connection
    original_process = runner.process_yookassa_notification
    loop = asyncio.new_event_loop()
    calls: list[dict] = []

    def fake_process(_conn: object, payload: dict) -> dict:
        calls.append(payload)
        return {"ok": True, "processed": True}

    try:
        runner.get_connection = lambda: DummyConnection()
        runner.process_yookassa_notification = fake_process

        prod_settings = FakeSettings(app_env="production", yookassa_webhook_secret="")
        runner.get_settings = lambda: prod_settings
        try:
            runner.start_yookassa_webhook_server(bot=None, loop=loop)
        except RuntimeError:
            pass
        else:
            raise AssertionError("production webhook must require YOOKASSA_WEBHOOK_SECRET")

        settings = FakeSettings()
        runner.get_settings = lambda: settings
        server = runner.start_yookassa_webhook_server(bot=None, loop=loop)
        assert server is not None
        base_url = f"http://127.0.0.1:{server.server_port}{settings.yookassa_webhook_path}"
        try:
            status, body = request_json(base_url)
            assert status == 200 and body["service"] == "yookassa-webhook", body

            status, body = request_json(base_url, method="POST", payload={"event": "payment.succeeded"})
            assert status == 403 and body["error"] == "forbidden", body

            status, body = request_json(
                base_url,
                method="POST",
                payload={"event": "payment.succeeded", "object": {"id": "pay_test"}},
                headers={"X-Webhook-Secret": settings.yookassa_webhook_secret},
            )
            assert status == 200 and body["processed"] is True and len(calls) == 1, body

            large_payload = {"event": "payment.succeeded", "blob": "x" * 200}
            status, body = request_json(
                base_url,
                method="POST",
                payload=large_payload,
                headers={"X-Webhook-Secret": settings.yookassa_webhook_secret},
            )
            assert status == 413 and body["error"] == "payload_too_large", body

            status, body = request_json(base_url + "-bad")
            assert status == 404 and body["error"] == "not_found", body
        finally:
            server.shutdown()
            server.server_close()
    finally:
        loop.close()
        runner.get_settings = original_get_settings
        runner.get_connection = original_get_connection
        runner.process_yookassa_notification = original_process

    print("OK: YooKassa webhook hardening smoke passed")


if __name__ == "__main__":
    main()
