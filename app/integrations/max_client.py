from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import time
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from app.core.config import get_settings


class MaxApiError(RuntimeError):
    pass


MAX_MESSAGE_TEXT_LIMIT = 4000
MAX_UPLOAD_TYPES = frozenset({"image", "video", "audio", "file"})


class MaxApiClient:
    DEFAULT_BASE_URL = "https://platform-api.max.ru"

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float = 20.0,
        max_attempts: int = 3,
        http_trust_env: bool | None = None,
        client_factory: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        settings = None
        if token is None or base_url is None or http_trust_env is None:
            settings = get_settings()

        configured_base_url = (
            base_url
            if base_url is not None
            else settings.max_api_base_url if settings else self.DEFAULT_BASE_URL
        )
        self.base_url = (configured_base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.token = token if token is not None else settings.max_bot_token if settings else ""
        self.timeout = timeout
        self.max_attempts = max(1, int(max_attempts))
        self.http_trust_env = (
            http_trust_env
            if http_trust_env is not None
            else bool(settings.http_trust_env) if settings else False
        )
        self._client_factory = client_factory or httpx.Client
        self._sleep = sleep or time.sleep

    @property
    def headers(self) -> dict[str, str]:
        token = self.token.strip()
        if not token:
            raise MaxApiError("MAX_BOT_TOKEN is not configured")
        return {
            "Accept": "application/json",
            "Authorization": token,
        }

    def get_me(self) -> dict[str, Any]:
        return self._request("GET", "/me")

    def get_subscriptions(self) -> dict[str, Any]:
        return self._request("GET", "/subscriptions")

    def get_message(self, message_id: str) -> dict[str, Any]:
        message = str(message_id or "").strip()
        if not message:
            raise MaxApiError("MAX message_id is required")
        return self._request("GET", f"/messages/{quote(message, safe='')}")

    def get_updates(
        self,
        *,
        marker: int | None = None,
        limit: int = 100,
        timeout: int = 30,
        types: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": max(1, min(1000, int(limit))),
            "timeout": max(0, min(90, int(timeout))),
        }
        if marker is not None:
            params["marker"] = int(marker)
        event_types = [str(item).strip() for item in (types or ()) if str(item).strip()]
        if event_types:
            params["types"] = ",".join(event_types)
        return self._request("GET", "/updates", params=params)

    def send_chat_action(self, *, chat_id: str, action: str = "typing_on") -> dict[str, Any]:
        chat = str(chat_id or "").strip()
        if not chat:
            raise MaxApiError("MAX chat action requires chat_id")
        action_text = str(action or "").strip()
        if not action_text:
            raise MaxApiError("MAX chat action is required")
        return self._request(
            "POST",
            f"/chats/{quote(chat, safe='')}/actions",
            json={"action": action_text},
        )

    def send_message(
        self,
        *,
        text: str | None = None,
        user_id: str | None = None,
        chat_id: str | None = None,
        attachments: Sequence[dict[str, Any]] | None = None,
        text_format: str | None = None,
        notify: bool | None = None,
        disable_link_preview: bool | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if text is not None:
            if not isinstance(text, str):
                raise MaxApiError("MAX message text must be a string")
            if len(text) > MAX_MESSAGE_TEXT_LIMIT:
                raise MaxApiError(
                    f"MAX message text exceeds {MAX_MESSAGE_TEXT_LIMIT} characters"
                )
            if text:
                body["text"] = text
        if attachments is not None:
            normalized_attachments = [
                dict(item)
                for item in attachments
                if isinstance(item, dict)
            ]
            if normalized_attachments:
                body["attachments"] = normalized_attachments
        if not body.get("text") and not body.get("attachments"):
            raise MaxApiError(
                "MAX message requires text or attachments"
            )
        if text_format is not None:
            body["format"] = text_format
        if notify is not None:
            body["notify"] = bool(notify)
        params = _message_target_params(user_id=user_id, chat_id=chat_id)
        if disable_link_preview is not None:
            params["disable_link_preview"] = bool(disable_link_preview)
        return self._request(
            "POST",
            "/messages",
            params=params,
            json=body,
        )

    def create_upload(self, *, upload_type: str = "file") -> dict[str, Any]:
        return self._request(
            "POST",
            "/uploads",
            params={"type": _normalize_upload_type(upload_type)},
        )

    def upload_file(
        self,
        file_path: str | Path,
        *,
        upload_type: str = "file",
    ) -> dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            raise MaxApiError(f"MAX upload file does not exist: {path}")

        upload_info = self.create_upload(upload_type=upload_type)
        upload_url = _upload_url_from_payload(upload_info)
        upload_result = self._upload_to_url(upload_url, path)
        return _attachment_payload_from_upload(upload_info, upload_result)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        method = method.upper()
        path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{path}"
        attempts = self.max_attempts if method == "GET" else 1
        last_error: httpx.HTTPError | None = None

        for attempt in range(1, attempts + 1):
            try:
                with self._client_factory(
                    timeout=self.timeout,
                    trust_env=self.http_trust_env,
                ) as client:
                    response = client.request(
                        method,
                        url,
                        headers=self.headers,
                        **kwargs,
                    )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise MaxApiError(f"MAX API request failed: {exc}") from exc
                self._sleep(0.8 * attempt)
                continue
            except httpx.HTTPError as exc:
                raise MaxApiError(f"MAX API request failed: {exc}") from exc

            if response.status_code == 429 and attempt < attempts:
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                self._sleep(retry_after if retry_after is not None else 0.8 * attempt)
                continue

            if response.status_code >= 500 and attempt < attempts:
                self._sleep(0.8 * attempt)
                continue

            if response.status_code >= 400:
                raise MaxApiError(
                    f"MAX API returned HTTP {response.status_code} for {path}: "
                    f"{self._safe_response_text(response)}"
                )

            if not response.text.strip():
                return {}
            try:
                payload = response.json()
            except ValueError as exc:
                raise MaxApiError(
                    f"MAX API returned non-JSON response for {path}: "
                    f"{self._safe_response_text(response)}"
                ) from exc
            if isinstance(payload, dict):
                return payload
            return {"data": payload}

        raise MaxApiError(f"MAX API request failed: {last_error}")

    def download_file_url(
        self,
        url: str,
        *,
        max_bytes: int = 20 * 1024 * 1024,
    ) -> bytes:
        download_url = str(url or "").strip()
        if not download_url:
            raise MaxApiError("MAX download URL is empty")
        if max_bytes <= 0:
            raise MaxApiError("MAX download max_bytes must be positive")
        headers = self.headers if _same_origin(download_url, self.base_url) else {}
        try:
            with self._client_factory(
                timeout=self.timeout,
                trust_env=self.http_trust_env,
            ) as client:
                response = client.request("GET", download_url, headers=headers)
        except httpx.HTTPError as exc:
            raise MaxApiError(f"MAX download failed: {exc}") from exc

        if response.status_code >= 400:
            raise MaxApiError(
                f"MAX download returned HTTP {response.status_code}: "
                f"{self._safe_response_text(response)}"
            )
        data = response.content
        if len(data) > max_bytes:
            raise MaxApiError("MAX download exceeds size limit")
        return data

    def _upload_to_url(self, upload_url: str, path: Path) -> dict[str, Any]:
        try:
            with path.open("rb") as file_obj:
                with self._client_factory(
                    timeout=self.timeout,
                    trust_env=self.http_trust_env,
                ) as client:
                    response = client.request(
                        "POST",
                        upload_url,
                        headers={},
                        files={"data": (path.name, file_obj)},
                    )
        except (OSError, httpx.HTTPError) as exc:
            raise MaxApiError(f"MAX upload failed: {exc}") from exc

        if response.status_code >= 400:
            raise MaxApiError(
                f"MAX upload returned HTTP {response.status_code}: "
                f"{self._safe_response_text(response)}"
            )
        if not response.text.strip():
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise MaxApiError(
                "MAX upload returned non-JSON response: "
                f"{self._safe_response_text(response)}"
            ) from exc
        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    def _safe_response_text(self, response: httpx.Response) -> str:
        text = response.text[:500]
        token = self.token.strip()
        if token:
            text = text.replace(token, "[redacted]")
        return text


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())


def _message_target_params(
    *,
    user_id: str | None,
    chat_id: str | None,
) -> dict[str, Any]:
    chat = str(chat_id).strip() if chat_id is not None else ""
    if chat:
        return {"chat_id": chat}
    user = str(user_id).strip() if user_id is not None else ""
    if user:
        return {"user_id": user}
    raise MaxApiError("MAX message target requires user_id or chat_id")


def _normalize_upload_type(upload_type: str) -> str:
    value = str(upload_type or "").strip().lower()
    if value == "photo":
        value = "image"
    if value not in MAX_UPLOAD_TYPES:
        raise MaxApiError(
            "MAX upload type must be one of: "
            + ", ".join(sorted(MAX_UPLOAD_TYPES))
        )
    return value


def _payload_dict(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _same_origin(url: str, base_url: str) -> bool:
    parsed = urlparse(url)
    base = urlparse(base_url)
    return bool(
        parsed.scheme
        and parsed.netloc
        and parsed.scheme.lower() == base.scheme.lower()
        and parsed.netloc.lower() == base.netloc.lower()
    )


def _upload_url_from_payload(payload: dict[str, Any]) -> str:
    data = _payload_dict(payload)
    value = data.get("url") or data.get("upload_url")
    url = str(value or "").strip()
    if not url:
        raise MaxApiError("MAX upload URL is missing in /uploads response")
    return url


def _attachment_payload_from_upload(
    upload_info: dict[str, Any],
    upload_result: dict[str, Any],
) -> dict[str, Any]:
    result_data = _payload_dict(upload_result)
    if result_data.get("token"):
        return dict(result_data)
    info_data = _payload_dict(upload_info)
    token = info_data.get("token")
    if token:
        return {"token": token}
    raise MaxApiError("MAX upload did not return attachment token")


__all__ = [
    "MAX_MESSAGE_TEXT_LIMIT",
    "MAX_UPLOAD_TYPES",
    "MaxApiClient",
    "MaxApiError",
]
