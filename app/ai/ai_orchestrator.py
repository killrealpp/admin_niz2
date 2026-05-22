import json
import logging
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from openai import APIStatusError

from app.ai.errors import AIProviderUnavailable, is_quota_or_credit_error
from app.ai.openai_client import get_ai_client
from app.ai.prompt_loader import load_prompt
from app.ai.schemas import AIResponse, PostBookingResponse
from app.core.config import get_settings
from app.services.booking_form_service import describe_fields_for_prompt

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("AI response has no JSON object")
    return json.loads(cleaned[start : end + 1])


def _format_history(messages: list[dict[str, Any]], *, limit: int = 8) -> str:
    if not messages:
        return "Истории пока нет."
    lines = []
    for item in messages[-limit:]:
        lines.append(f"{item['sender']}: {item['text']}")
    return "\n".join(lines)


def _format_summaries(summaries: list[dict[str, Any]] | None) -> str:
    if not summaries:
        return "Сжатого старого контекста нет."
    lines = []
    for item in summaries:
        lines.append(
            f"[{item.get('messages_from')} - {item.get('messages_to')}] "
            f"{item.get('summary')}"
        )
    return "\n".join(lines)


def build_user_prompt(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    summaries: list[dict[str, Any]] | None = None,
    current_datetime: datetime,
    knowledge: str,
) -> str:
    return f"""
current_datetime: {current_datetime.isoformat()}

Анкета:
{describe_fields_for_prompt()}

Текущая form_data:
{json.dumps(form_data, ensure_ascii=False, indent=2)}

Сжатый старый контекст:
{_format_summaries(summaries)}

Последняя история:
{_format_history(history, limit=8)}

База знаний:
{knowledge}

Новое сообщение клиента:
{text}
""".strip()


def call_ai(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    summaries: list[dict[str, Any]] | None = None,
    current_datetime: datetime,
    knowledge: str,
) -> AIResponse:
    settings = get_settings()
    client = get_ai_client()
    user_prompt = build_user_prompt(
        text=text,
        form_data=form_data,
        history=history,
        summaries=summaries,
        current_datetime=current_datetime,
        knowledge=knowledge,
    )

    raw = _chat_completion(client, settings, load_prompt("system_prompt.md"), user_prompt)
    try:
        return AIResponse.model_validate(_extract_json(raw))
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        logger.warning("AI JSON parse failed, trying repair: %s", exc)

    repair_prompt = (
        f"{load_prompt('json_repair.md')}\n\n"
        f"{raw}"
    )
    repaired = _chat_completion(client, settings, load_prompt("system_prompt.md"), repair_prompt)
    return AIResponse.model_validate(_extract_json(repaired))


def generate_final_reply(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    ai_result: AIResponse,
    next_question: str | None,
    knowledge: str,
) -> str:
    settings = get_settings()
    client = get_ai_client()
    prompt = f"""
Сообщение клиента:
{text}

История:
{_format_history(history, limit=8)}

form_data:
{json.dumps(form_data, ensure_ascii=False, indent=2)}

Результат анализа AI:
{ai_result.model_dump_json(indent=2)}

next_question:
{next_question or ""}

База знаний:
{knowledge}
""".strip()
    return _chat_completion(
        client,
        settings,
        load_prompt("response_generator.md"),
        prompt,
    ).strip()


def generate_process_reply(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    required_meaning: str,
    knowledge: str,
) -> str:
    settings = get_settings()
    client = get_ai_client()
    prompt = f"""
Сообщение клиента:
{text}

История:
{_format_history(history, limit=8)}

form_data:
{json.dumps(form_data, ensure_ascii=False, indent=2)}

Обязательный смысл ответа:
{required_meaning}

База знаний:
{knowledge}
""".strip()
    system_prompt = load_prompt("response_generator.md")
    if "информацион" in required_meaning.lower():
        system_prompt = load_prompt("info_answer.md")
    return _chat_completion(
        client,
        settings,
        system_prompt,
        prompt,
    ).strip()


def classify_post_booking_message(
    *,
    text: str,
    form_data: dict[str, Any],
    history: list[dict[str, Any]],
    current_datetime: datetime,
    knowledge: str,
) -> PostBookingResponse:
    settings = get_settings()
    client = get_ai_client()
    prompt = f"""
current_datetime: {current_datetime.isoformat()}

Текущая form_data:
{json.dumps(form_data, ensure_ascii=False, indent=2)}

Последняя история:
{_format_history(history, limit=8)}

База знаний:
{knowledge}

Новое сообщение клиента:
{text}
""".strip()
    raw = _chat_completion(
        client,
        settings,
        load_prompt("post_booking_classifier.md"),
        prompt,
    )
    try:
        return PostBookingResponse.model_validate(_extract_json(raw))
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Post-booking JSON parse failed: %s", exc)
        return PostBookingResponse(
            intent="other",
            confidence=0.0,
            reply_to_user="",
        )


def summarize_dialog_messages(messages: list[dict[str, Any]]) -> str:
    settings = get_settings()
    client = get_ai_client()
    history = _format_history(messages)
    prompt = f"""
Сожми старую историю диалога для будущего CRM-контекста.
Сохрани только важное:
- что хотел клиент;
- выбранные объект, дата, время, гости;
- имя и телефон, если были;
- важные вопросы/ответы;
- незавершённые договорённости.

История:
{history}

Верни короткое резюме на русском, без markdown.
""".strip()
    return _chat_completion(
        client,
        settings,
        "Ты аккуратно сжимаешь историю диалога для CRM.",
        prompt,
    ).strip()


def _chat_completion(
    client: Any,
    settings: Any,
    system_prompt: str,
    user_prompt: str,
) -> str:
    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            temperature=settings.openai_temperature,
            max_tokens=settings.openai_max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except APIStatusError as exc:
        if is_quota_or_credit_error(exc):
            raise AIProviderUnavailable(
                "AI provider quota/credits problem",
                status_code=exc.status_code,
                payload=getattr(exc, "response", None).text if getattr(exc, "response", None) else str(exc),
            ) from exc
        raise
    except Exception as exc:
        if is_quota_or_credit_error(exc):
            raise AIProviderUnavailable("AI provider quota/credits problem", payload=str(exc)) from exc
        raise
    return response.choices[0].message.content or ""
