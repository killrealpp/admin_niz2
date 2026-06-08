from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Queue
from threading import Thread
from typing import Any, Callable
from urllib.parse import urlparse

from app.core.config import get_settings
from app.db.connection import get_connection
from app.db.repositories import webhook_events_repo

logger = logging.getLogger(__name__)

_PRODUCTION_ENVS = {"prod", "production"}
_MAX_EVENT_KEY_BYTES = 128
_STOP = object()


@dataclass(frozen=True, slots=True)
class MaxWebhookEvent:
    webhook_event_id: int | None
    event_type: str
    event_key: str
    payload: dict[str, Any]


MaxWebhookEventProcessor = Callable[[MaxWebhookEvent], None]


class _MaxWebhookServer(ThreadingHTTPServer):
    event_queue: Queue[MaxWebhookEvent | object]
    event_processor: MaxWebhookEventProcessor | None
    worker_thread: Thread

    def start_worker(self) -> None:
        self.worker_thread = Thread(
            target=_process_queue,
            args=(self,),
            name="max-webhook-worker",
            daemon=True,
        )
        self.worker_thread.start()

    def server_close(self) -> None:
        self.event_queue.put(_STOP)
        if getattr(self, "worker_thread", None):
            self.worker_thread.join(timeout=5)
        super().server_close()


def start_max_webhook_server(
    *,
    event_processor: MaxWebhookEventProcessor | None = None,
) -> ThreadingHTTPServer | None:
    settings = get_settings()
    if not settings.max_webhook_enabled:
        logger.info("MAX webhook server disabled")
        return None
    if settings.max_mode.strip().lower() != "webhook":
        raise RuntimeError("MAX webhook server requires MAX_MODE=webhook")
    if settings.app_env.lower() in _PRODUCTION_ENVS and not settings.max_webhook_secret:
        raise RuntimeError("MAX_WEBHOOK_SECRET is required when APP_ENV=production")

    server = _MaxWebhookServer(
        (settings.max_webhook_host, settings.max_webhook_port),
        _MaxWebhookHandler,
    )
    server.event_queue = Queue()
    server.event_processor = event_processor
    server.start_worker()
    thread = Thread(target=server.serve_forever, name="max-webhook", daemon=True)
    thread.start()
    logger.info(
        "MAX webhook server started on %s:%s%s",
        settings.max_webhook_host,
        settings.max_webhook_port,
        settings.max_webhook_path,
    )
    return server


class _MaxWebhookHandler(BaseHTTPRequestHandler):
    server: _MaxWebhookServer

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("MAX webhook: " + fmt, *args)

    def do_GET(self) -> None:
        settings = get_settings()
        if urlparse(self.path).path != settings.max_webhook_path:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        self._send_json(HTTPStatus.OK, {"ok": True, "service": "max-webhook"})

    def do_POST(self) -> None:
        settings = get_settings()
        if urlparse(self.path).path != settings.max_webhook_path:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        if not _is_valid_secret(
            settings.max_webhook_secret,
            self.headers.get("X-Max-Bot-Api-Secret"),
        ):
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
            return

        payload = self._read_json_payload(settings.max_webhook_max_body_bytes)
        if payload is None:
            return

        event_type = max_event_type(payload)
        event_key = stable_max_event_key(payload)
        try:
            with get_connection() as conn:
                saved_event, is_new = webhook_events_repo.create_if_new(
                    conn,
                    provider="max",
                    event_type=event_type,
                    provider_object_id=event_key,
                    payload=payload,
                )
        except Exception:
            logger.exception("MAX webhook deduplication failed")
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "deduplication_failed"},
            )
            return

        if not is_new:
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "accepted": False,
                    "duplicate": True,
                    "event_type": event_type,
                    "event_key": event_key,
                },
            )
            return

        self.server.event_queue.put(
            MaxWebhookEvent(
                webhook_event_id=int(saved_event["id"]) if saved_event else None,
                event_type=event_type,
                event_key=event_key,
                payload=payload,
            )
        )
        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "accepted": True,
                "duplicate": False,
                "event_type": event_type,
                "event_key": event_key,
            },
        )

    def _read_json_payload(self, max_body_bytes: int) -> dict[str, Any] | None:
        try:
            length_header = self.headers.get("Content-Length")
            if length_header is None:
                self._send_json(
                    HTTPStatus.LENGTH_REQUIRED,
                    {"ok": False, "error": "content_length_required"},
                )
                return None
            length = int(length_header)
        except ValueError:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_content_length"},
            )
            return None

        if length <= 0:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "empty_body"})
            return None
        if length > max_body_bytes:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"ok": False, "error": "payload_too_large"},
            )
            return None

        body = self.rfile.read(length)
        if len(body) != length:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "incomplete_body"},
            )
            return None

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return None
        if not isinstance(payload, dict):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "json_object_required"},
            )
            return None
        return payload

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


def max_event_type(payload: dict[str, Any]) -> str:
    value = (
        payload.get("update_type")
        or payload.get("type")
        or payload.get("event_type")
        or "unknown"
    )
    text = str(value).strip() or "unknown"
    if len(text) <= 128:
        return text
    return f"{text[:95]}:{_payload_hash({'event_type': text})[:32]}"


def stable_max_event_key(payload: dict[str, Any]) -> str:
    direct_id = _string_value(payload, "event_id", "update_id", "notification_id", "id")
    if direct_id:
        return _bounded_event_key(f"event:{direct_id}")

    message = _message_payload(payload)
    message_id = _string_value(message, "message_id", "mid", "id")
    if message_id:
        chat_id = _string_value(payload, "chat_id") or _chat_id_from_message(message)
        user = _user_payload(payload, message)
        user_id = _string_value(user, "user_id", "id") or _string_value(
            payload,
            "user_id",
            "sender_id",
        )
        scope = chat_id or user_id or "unknown"
        return _bounded_event_key(f"message:{scope}:{message_id}")

    return f"sha256:{_payload_hash(payload)}"


def _process_queue(server: _MaxWebhookServer) -> None:
    while True:
        item = server.event_queue.get()
        try:
            if item is _STOP:
                return
            assert isinstance(item, MaxWebhookEvent)
            if server.event_processor is None:
                logger.info(
                    "MAX webhook event accepted without processor event_type=%s event_key=%s",
                    item.event_type,
                    item.event_key,
                )
                continue
            server.event_processor(item)
            if item.webhook_event_id is not None:
                with get_connection() as conn:
                    webhook_events_repo.mark_processed(
                        conn,
                        event_id=item.webhook_event_id,
                    )
        except Exception:
            logger.exception("MAX webhook queue processing failed")
        finally:
            server.event_queue.task_done()


def _is_valid_secret(expected_secret: str, header_token: str | None) -> bool:
    if not expected_secret:
        return True
    return hmac.compare_digest(header_token or "", expected_secret)


def _message_payload(update: dict[str, Any]) -> dict[str, Any]:
    message = update.get("message")
    if isinstance(message, dict):
        return message
    message_created = update.get("message_created")
    if isinstance(message_created, dict):
        return message_created
    return update


def _user_payload(
    update: dict[str, Any],
    message: dict[str, Any],
) -> dict[str, Any]:
    for key in ("sender", "user", "author"):
        value = message.get(key)
        if isinstance(value, dict):
            return value
    for key in ("sender", "user", "author"):
        value = update.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _chat_id_from_message(message: dict[str, Any]) -> str | None:
    recipient = message.get("recipient")
    if isinstance(recipient, dict):
        return _string_value(recipient, "chat_id", "id")
    return _string_value(message, "chat_id")


def _string_value(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _bounded_event_key(value: str) -> str:
    if len(value.encode("utf-8")) <= _MAX_EVENT_KEY_BYTES:
        return value
    return f"sha256:{_payload_hash({'event_key': value})}"


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "MaxWebhookEvent",
    "MaxWebhookEventProcessor",
    "max_event_type",
    "stable_max_event_key",
    "start_max_webhook_server",
]
