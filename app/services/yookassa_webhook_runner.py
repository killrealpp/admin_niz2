from __future__ import annotations

import asyncio
import hmac
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

from aiogram import Bot

from app.core.config import get_settings
from app.db.connection import get_connection
from app.services.payment_service import process_yookassa_notification
from app.services.payment_status_runner import notify_paid_payments_once

logger = logging.getLogger(__name__)

_PRODUCTION_ENVS = {"prod", "production"}


class _WebhookServer(ThreadingHTTPServer):
    bot: Bot | None
    loop: asyncio.AbstractEventLoop | None


def start_yookassa_webhook_server(
    *,
    bot: Bot | None,
    loop: asyncio.AbstractEventLoop,
) -> ThreadingHTTPServer | None:
    settings = get_settings()
    if not settings.yookassa_webhook_enabled:
        logger.info("YooKassa webhook server disabled")
        return None
    if settings.app_env.lower() in _PRODUCTION_ENVS and not settings.yookassa_webhook_secret:
        raise RuntimeError("YOOKASSA_WEBHOOK_SECRET is required when APP_ENV=production")

    server = _WebhookServer(
        (settings.yookassa_webhook_host, settings.yookassa_webhook_port),
        _YooKassaWebhookHandler,
    )
    server.bot = bot
    server.loop = loop
    thread = Thread(target=server.serve_forever, name="yookassa-webhook", daemon=True)
    thread.start()
    logger.info(
        "YooKassa webhook server started on %s:%s%s",
        settings.yookassa_webhook_host,
        settings.yookassa_webhook_port,
        settings.yookassa_webhook_path,
    )
    return server


class _YooKassaWebhookHandler(BaseHTTPRequestHandler):
    server: _WebhookServer

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("YooKassa webhook: " + fmt, *args)

    def do_GET(self) -> None:
        settings = get_settings()
        if urlparse(self.path).path != settings.yookassa_webhook_path:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        self._send_json(HTTPStatus.OK, {"ok": True, "service": "yookassa-webhook"})

    def do_POST(self) -> None:
        settings = get_settings()
        parsed = urlparse(self.path)
        if parsed.path != settings.yookassa_webhook_path:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        if not _is_valid_secret(settings.yookassa_webhook_secret, self.headers.get("X-Webhook-Secret"), parsed.query):
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
            return

        try:
            length_header = self.headers.get("Content-Length")
            if length_header is None:
                self._send_json(HTTPStatus.LENGTH_REQUIRED, {"ok": False, "error": "content_length_required"})
                return
            length = int(length_header)
            if length <= 0:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "empty_body"})
                return
            if length > settings.yookassa_webhook_max_body_bytes:
                self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "payload_too_large"})
                return
            body = self.rfile.read(length)
            if len(body) != length:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "incomplete_body"})
                return
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
                return
        except Exception:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return

        try:
            with get_connection() as conn:
                result = process_yookassa_notification(conn, payload)
        except Exception:
            logger.exception("YooKassa webhook processing failed")
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "processing_failed"})
            return

        if self.server.bot and self.server.loop:
            future = asyncio.run_coroutine_threadsafe(
                notify_paid_payments_once(self.server.bot),
                self.server.loop,
            )
            future.add_done_callback(_log_notify_result)
        self._send_json(HTTPStatus.OK, result)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


def _is_valid_secret(expected_secret: str, header_token: str | None, query: str) -> bool:
    if not expected_secret:
        return True
    token = header_token or parse_qs(query).get("secret", [""])[0]
    return hmac.compare_digest(token, expected_secret)


def _log_notify_result(future: asyncio.Future) -> None:
    try:
        future.result()
    except Exception:
        logger.exception("YooKassa webhook notification follow-up failed")
