"""Smoke-check deterministic bot identity answers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.dialog.info_flow import InfoFlowCallbacks, deterministic_info_reply  # noqa: E402


def _callbacks() -> InfoFlowCallbacks:
    return InfoFlowCallbacks(
        next_question=lambda _form_data: ("event_format", "Какой формат отдыха: день рождения, корпоратив, семейный отдых, компания друзей или спокойный вечер?"),
        reply_already_asks=lambda reply, _next_key, question: bool(question and question in reply),
        explicit_photo_reply=lambda _text, _form_data: None,
        discount_reply_if_known=lambda _text, _form_data: None,
        price_reply_if_known=lambda _text, _form_data: None,
        looks_like_gazebo_budget_preference=lambda _text: False,
        gazebo_budget_selection_text=lambda _form_data: None,
        current_gazebo_quality_reply=lambda _text, _form_data: None,
        capacity_info_reply=lambda _text, _form_data: None,
        policy_or_common_info_reply=lambda _text: None,
        should_append_next_question_after_info=lambda _form_data, _next_key: True,
        capacity_guest_patch=lambda _text: {},
        clean_reply=lambda text: text,
        ai_process_reply=_fail_ai_process_reply,
        asks_gazebo_options=lambda _text: False,
        gazebo_selection_text=lambda _form_data: "",
    )


def _fail_ai_process_reply(**_kwargs: Any) -> str:
    raise AssertionError("identity answer must not call AI")


def main() -> None:
    reply = deterministic_info_reply(
        "как тебя зовут",
        {"service_type": "gazebo"},
        callbacks=_callbacks(),
    )
    assert reply is not None
    assert "Любовь" in reply
    assert "Бест" not in reply
    assert "Какой формат отдыха" in reply
    print("dialog_identity_smoke=ok")


if __name__ == "__main__":
    main()
