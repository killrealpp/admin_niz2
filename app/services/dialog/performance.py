from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter
from typing import Any, Callable, Iterator, TypeVar


F = TypeVar("F", bound=Callable[..., Any])
_current_trace: ContextVar["PerformanceTrace | None"] = ContextVar("dialog_performance_trace", default=None)


@dataclass
class PerformanceTrace:
    name: str
    started_at: float = field(default_factory=perf_counter)
    steps: dict[str, float] = field(default_factory=dict)

    def add(self, step: str, elapsed: float) -> None:
        self.steps[step] = self.steps.get(step, 0.0) + elapsed

    def total(self) -> float:
        return perf_counter() - self.started_at

    def payload(self, **extra: Any) -> dict[str, Any]:
        return {
            "trace": self.name,
            "total_s": round(self.total(), 3),
            "steps_s": {key: round(value, 3) for key, value in sorted(self.steps.items())},
            **{key: value for key, value in extra.items() if value is not None},
        }


def current_trace() -> PerformanceTrace | None:
    return _current_trace.get()


@contextmanager
def trace_span(name: str) -> Iterator[None]:
    started_at = perf_counter()
    try:
        yield
    finally:
        trace = current_trace()
        if trace:
            trace.add(name, perf_counter() - started_at)


def trace_message_handler(logger: logging.Logger, *, slow_threshold_s: float = 3.0) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(message: Any, *args: Any, **kwargs: Any) -> Any:
            trace = PerformanceTrace("handle_incoming")
            token = _current_trace.set(trace)
            status = "ok"
            try:
                return func(message, *args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                _current_trace.reset(token)
                payload = trace.payload(
                    status=status,
                    channel=getattr(message, "channel", None),
                    external_user_id=getattr(message, "external_user_id", None),
                )
                if trace.total() >= slow_threshold_s:
                    logger.warning("dialog_timing_slow %s", payload)
                else:
                    logger.info("dialog_timing %s", payload)

        return wrapper  # type: ignore[return-value]

    return decorator
