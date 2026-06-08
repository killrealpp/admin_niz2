"""Smoke-test MAX webhook endpoint hardening without live MAX calls."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bot import max_webhook_runner as runner  # noqa: E402


@dataclass
class FakeSettings:
    app_env: str = "local"
    max_webhook_enabled: bool = True
    max_webhook_host: str = "127.0.0.1"
    max_webhook_port: int = 0
    max_webhook_path: str = "/webhooks/max"
    max_webhook_secret: str = "secret"
    max_webhook_max_body_bytes: int = 256
    max_mode: str = "webhook"


class DummyConnection:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_exc: object) -> None:
        return None


class FakeWebhookEventsRepo:
    def __init__(self) -> None:
        self._lock = Lock()
        self._seen: set[tuple[str, str, str | None]] = set()
        self._next_id = 1
        self.marked_processed: list[int] = []

    def create_if_new(
        self,
        _conn: object,
        *,
        provider: str,
        event_type: str,
        provider_object_id: str | None,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, bool]:
        key = (provider, event_type, provider_object_id)
        with self._lock:
            if key in self._seen:
                return None, False
            self._seen.add(key)
            event_id = self._next_id
            self._next_id += 1
        return {
            "id": event_id,
            "provider": provider,
            "event_type": event_type,
            "provider_object_id": provider_object_id,
            "payload": payload,
        }, True

    def mark_processed(self, _conn: object, *, event_id: int) -> None:
        with self._lock:
            self.marked_processed.append(event_id)


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | list[Any] | bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    if isinstance(payload, bytes):
        data = payload
    elif payload is None:
        data = None
    else:
        data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers=headers or {})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def max_payload(message_id: str, *, slow: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "update_type": "message_created",
        "message": {
            "id": message_id,
            "body": {"text": "hello"},
            "sender": {"user_id": "user-1", "name": "Test User"},
            "recipient": {"chat_id": "chat-1"},
        },
        "timestamp": 1_771_000_000,
    }
    if slow:
        payload["slow_test_processor"] = True
    return payload


def wait_for_queue(server: object, timeout_seconds: float = 3.0) -> None:
    deadline = time.perf_counter() + timeout_seconds
    queue = getattr(server, "event_queue")
    while time.perf_counter() < deadline:
        if queue.unfinished_tasks == 0:
            return
        time.sleep(0.02)
    raise AssertionError("MAX webhook queue did not drain in time")


def main() -> None:
    original_get_settings = runner.get_settings
    original_get_connection = runner.get_connection
    original_create = runner.webhook_events_repo.create_if_new
    original_mark_processed = runner.webhook_events_repo.mark_processed
    fake_repo = FakeWebhookEventsRepo()
    processed_events: list[runner.MaxWebhookEvent] = []

    def fake_processor(event: runner.MaxWebhookEvent) -> None:
        processed_events.append(event)
        if event.payload.get("slow_test_processor"):
            time.sleep(1.0)

    try:
        runner.get_settings = lambda: FakeSettings()
        runner.get_connection = lambda: DummyConnection()
        runner.webhook_events_repo.create_if_new = fake_repo.create_if_new
        runner.webhook_events_repo.mark_processed = fake_repo.mark_processed

        prod_settings = FakeSettings(app_env="production", max_webhook_secret="")
        runner.get_settings = lambda: prod_settings
        try:
            runner.start_max_webhook_server(event_processor=fake_processor)
        except RuntimeError:
            pass
        else:
            raise AssertionError("production MAX webhook must require MAX_WEBHOOK_SECRET")

        settings = FakeSettings()
        runner.get_settings = lambda: settings
        server = runner.start_max_webhook_server(event_processor=fake_processor)
        assert server is not None
        base_url = f"http://127.0.0.1:{server.server_port}{settings.max_webhook_path}"

        try:
            status, body = request_json(base_url)
            assert status == 200 and body["service"] == "max-webhook", body

            status, body = request_json(base_url + "-bad")
            assert status == 404 and body["error"] == "not_found", body

            status, body = request_json(base_url, method="POST", payload=max_payload("bad-secret"))
            assert status == 403 and body["error"] == "forbidden", body

            status, body = request_json(
                base_url,
                method="POST",
                payload=b"{not-json",
                headers={"X-Max-Bot-Api-Secret": settings.max_webhook_secret},
            )
            assert status == 400 and body["error"] == "invalid_json", body

            status, body = request_json(
                base_url,
                method="POST",
                payload=["not", "object"],
                headers={"X-Max-Bot-Api-Secret": settings.max_webhook_secret},
            )
            assert status == 400 and body["error"] == "json_object_required", body

            status, body = request_json(
                base_url,
                method="POST",
                payload={"blob": "x" * 300},
                headers={"X-Max-Bot-Api-Secret": settings.max_webhook_secret},
            )
            assert status == 413 and body["error"] == "payload_too_large", body

            first_payload = max_payload("dup-1")
            status, body = request_json(
                base_url,
                method="POST",
                payload=first_payload,
                headers={"X-Max-Bot-Api-Secret": settings.max_webhook_secret},
            )
            assert status == 200 and body["accepted"] is True and body["duplicate"] is False, body

            status, body = request_json(
                base_url,
                method="POST",
                payload=first_payload,
                headers={"X-Max-Bot-Api-Secret": settings.max_webhook_secret},
            )
            assert status == 200 and body["accepted"] is False and body["duplicate"] is True, body
            wait_for_queue(server)
            assert [event.event_key for event in processed_events].count("message:chat-1:dup-1") == 1

            start = time.perf_counter()
            status, body = request_json(
                base_url,
                method="POST",
                payload=max_payload("slow-1", slow=True),
                headers={"X-Max-Bot-Api-Secret": settings.max_webhook_secret},
            )
            elapsed = time.perf_counter() - start
            assert status == 200 and body["accepted"] is True, body
            assert elapsed < 0.5, f"webhook response waited for processor: {elapsed:.3f}s"
            wait_for_queue(server)
            assert len(processed_events) == 2, processed_events
            assert sorted(fake_repo.marked_processed) == [1, 2], fake_repo.marked_processed
        finally:
            server.shutdown()
            server.server_close()
    finally:
        runner.get_settings = original_get_settings
        runner.get_connection = original_get_connection
        runner.webhook_events_repo.create_if_new = original_create
        runner.webhook_events_repo.mark_processed = original_mark_processed

    print("max_webhook_runner_smoke=ok")


if __name__ == "__main__":
    main()
