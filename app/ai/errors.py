from __future__ import annotations

from typing import Any


class AIProviderUnavailable(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def is_quota_or_credit_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {402, 429}:
        return True
    text = str(exc).lower()
    markers = (
        "insufficient credits",
        "credits",
        "prompt tokens limit exceeded",
        "rate limit",
        "quota",
        "402",
        "429",
    )
    return any(marker in text for marker in markers)
