"""Smoke-check MAX API client without live MAX calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.integrations.max_client import MaxApiClient, MaxApiError  # noqa: E402


TOKEN = "secret-test-token"
BASE_URL = "https://platform-api.max.ru"


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        *,
        text: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.content = self.text.encode("utf-8")
        self.headers = headers or {}

    def json(self) -> Any:
        return self._payload


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def __enter__(self) -> FakeHttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> FakeResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "kwargs": kwargs,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected extra request")
        return self.responses.pop(0)


def _client(fake: FakeHttpClient, *, max_attempts: int = 3, sleep: Any = None) -> MaxApiClient:
    return MaxApiClient(
        token=TOKEN,
        base_url=BASE_URL,
        http_trust_env=False,
        client_factory=lambda **_kwargs: fake,
        max_attempts=max_attempts,
        sleep=sleep or (lambda _seconds: None),
    )


def _assert_safe_auth(request: dict[str, Any]) -> None:
    assert request["headers"]["Authorization"] == TOKEN
    assert TOKEN not in request["url"]
    assert "access_token" not in request["url"]


def main() -> None:
    get_me_http = FakeHttpClient(
        [FakeResponse(200, {"user_id": 1, "username": "max_bot", "is_bot": True})]
    )
    me = _client(get_me_http).get_me()
    assert me["user_id"] == 1
    assert get_me_http.requests[0]["url"] == f"{BASE_URL}/me"
    _assert_safe_auth(get_me_http.requests[0])

    sleeps: list[float] = []
    rate_limited_http = FakeHttpClient(
        [
            FakeResponse(429, {"message": "rate limited"}, headers={"Retry-After": "0"}),
            FakeResponse(200, {"subscriptions": []}),
        ]
    )
    subscriptions = _client(
        rate_limited_http,
        max_attempts=2,
        sleep=sleeps.append,
    ).get_subscriptions()
    assert subscriptions == {"subscriptions": []}
    assert len(rate_limited_http.requests) == 2
    assert sleeps == [0.0]
    _assert_safe_auth(rate_limited_http.requests[0])

    updates_http = FakeHttpClient(
        [FakeResponse(200, {"updates": [], "marker": 12345})]
    )
    updates = _client(updates_http).get_updates(
        marker=42,
        limit=5,
        timeout=7,
        types=("message_created", "bot_started"),
    )
    assert updates == {"updates": [], "marker": 12345}
    assert updates_http.requests[0]["url"] == f"{BASE_URL}/updates"
    assert updates_http.requests[0]["kwargs"]["params"] == {
        "marker": 42,
        "limit": 5,
        "timeout": 7,
        "types": "message_created,bot_started",
    }
    _assert_safe_auth(updates_http.requests[0])

    message_http = FakeHttpClient([FakeResponse(200, {"message": {"id": "msg/1"}})])
    message = _client(message_http).get_message("msg/1")
    assert message == {"message": {"id": "msg/1"}}
    assert message_http.requests[0]["method"] == "GET"
    assert message_http.requests[0]["url"] == f"{BASE_URL}/messages/msg%2F1"
    _assert_safe_auth(message_http.requests[0])

    action_http = FakeHttpClient([FakeResponse(200, {"success": True})])
    action = _client(action_http).send_chat_action(chat_id="chat/1")
    assert action == {"success": True}
    assert action_http.requests[0]["method"] == "POST"
    assert action_http.requests[0]["url"] == f"{BASE_URL}/chats/chat%2F1/actions"
    assert action_http.requests[0]["kwargs"]["json"] == {"action": "typing_on"}
    _assert_safe_auth(action_http.requests[0])

    download_http = FakeHttpClient([FakeResponse(200, text="audio-bytes")])
    data = _client(download_http).download_file_url("https://cdn.example.test/audio.ogg")
    assert data == b"audio-bytes"
    assert download_http.requests[0]["method"] == "GET"
    assert download_http.requests[0]["headers"] == {}

    missing_token_client = MaxApiClient(
        token="",
        base_url=BASE_URL,
        http_trust_env=False,
        client_factory=lambda **_kwargs: get_me_http,
    )
    try:
        missing_token_client.get_me()
    except MaxApiError as exc:
        assert "MAX_BOT_TOKEN" in str(exc)
    else:
        raise AssertionError("missing token must fail clearly")

    print("max_api_client_smoke=ok")


if __name__ == "__main__":
    main()
