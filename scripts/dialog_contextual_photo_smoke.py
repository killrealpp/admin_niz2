"""Smoke-check contextual photo requests such as "покажете их?"."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.constants import SENDER_ASSISTANT, SENDER_USER  # noqa: E402
from app.services.dialog.info_flow import InfoFlowCallbacks, contextual_photo_reply  # noqa: E402
from app.services.media_service import media_for_client_message  # noqa: E402
from app.services.message_handler import _awaiting_confirmation_side_reply  # noqa: E402


def _callbacks(seen: list[str]) -> InfoFlowCallbacks:
    return InfoFlowCallbacks(
        next_question=lambda _form_data: ("confirmation", "Если по заявке всё верно, напишите «да»."),
        reply_already_asks=lambda reply, _next_key, question: bool(question and question in reply),
        explicit_photo_reply=lambda text, _form_data: _explicit_photo_reply(text, seen),
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


def _explicit_photo_reply(text: str, seen: list[str]) -> str | None:
    seen.append(text)
    if "бесед" in text.lower().replace("ё", "е"):
        return "Конечно, сейчас отправлю фото беседок: Беседка №1, Беседка №2 📸"
    return None


def _fail_ai_process_reply(**_kwargs: Any) -> str:
    raise AssertionError("contextual photo answer must not call AI")


def main() -> None:
    seen: list[str] = []
    history = [
        {"sender": SENDER_USER, "text": "а беседки какие у вас есть?"},
        {
            "sender": SENDER_ASSISTANT,
            "text": "Есть несколько беседок: №1 до 50 гостей, №2/№4/№6 до 15, №5 до 10, №3/№8 и Крытая беседка до 20 гостей.",
        },
    ]
    reply = contextual_photo_reply(
        "покажете их?",
        {"service_type": "bathhouse"},
        history,
        callbacks=_callbacks(seen),
    )
    assert reply is not None
    assert "фото беседок" in reply
    assert seen == ["покажите фото беседок"]
    paths = media_for_client_message("покажете их?", reply)
    assert [path.name for path in paths] == [
        "besedka1.jpg",
        "besedka2.jpg",
    ]
    reply_with_particle = contextual_photo_reply(
        "а покажете их?",
        {"service_type": "bathhouse"},
        history,
        callbacks=_callbacks([]),
    )
    assert reply_with_particle is not None
    assert "фото беседок" in reply_with_particle

    user_only_history = [{"sender": SENDER_USER, "text": "какие беседки у вас есть?"}]
    user_only_reply = contextual_photo_reply(
        "а покажете их?",
        {"service_type": "bathhouse"},
        user_only_history,
        callbacks=_callbacks([]),
    )
    assert user_only_reply is not None
    assert "фото беседок" in user_only_reply

    confirmation_reply = _awaiting_confirmation_side_reply(
        text="покажете их?",
        form_data={"service_type": "bathhouse"},
        history=history,
    )
    assert "фото бесед" in confirmation_reply.lower().replace("ё", "е")
    print("dialog_contextual_photo_smoke=ok")


if __name__ == "__main__":
    main()
