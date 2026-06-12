from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from app.ai.response_sanitizer import sanitize_reply
from app.core.config import get_settings
from app.data.services import load_services
from app.dialog.pricing import BATHHOUSE_EXTRA_HOUR_PRICE_RUB, calculate_booking_price
from app.dialog.availability_cache import availability_context_for_llm, availability_object_dates_for_llm
from app.dialog.state import AdminAction, AdminDecision, BookingDraft

logger = logging.getLogger(__name__)

_RATE_LIMIT_EVENT = threading.Event()


def is_llm_rate_limited() -> bool:
    """True while an LLM request is sleeping after a 429 retry.

    Telegram uses this to keep showing the typing action during backoff instead
    of looking frozen.
    """
    return _RATE_LIMIT_EVENT.is_set()


PROMPT_PATH = Path(__file__).resolve().with_name("admin_prompt.md")
ROUTER_PROMPT_PATH = Path(__file__).resolve().with_name("router_prompt.md")
KNOWLEDGE_PATH = Path(__file__).resolve().with_name("knowledge.md")


def _load_knowledge() -> str:
    if not KNOWLEDGE_PATH.exists():
        return ""
    return KNOWLEDGE_PATH.read_text(encoding="utf-8")


def decide(text: str, draft: BookingDraft, *, today: str, history: list[dict[str, str]] | None = None) -> AdminDecision:
    settings = get_settings()
    if not _llm_api_key(settings):
        logger.warning(
            "LLM disabled: no API key found. Set OPENAI_API_KEY or AI_API_KEY in .env. parser_model=%s answer_model=%s base_url=%s",
            getattr(settings, "parser_model", None),
            getattr(settings, "answer_model", None),
            _llm_base_url(settings),
        )
        return fallback_decision(text)

    predecision = _decide_data_request(
        text,
        draft,
        today=today,
        history=history,
    )

    availability_query = _normalize_availability_query(predecision.get("availability_query"))

    mode = availability_query.get("mode")

    if mode == "object_dates" and availability_query.get("object_title"):
        object_context = availability_object_dates_for_llm(
            title=str(availability_query.get("object_title")),
            date_from=availability_query.get("date_from") or today,
            limit=21,
        )

        overview_context = availability_context_for_llm(
            service_type=None,
            date=None,
            limit=1000,
        )

        availability_context = (
            "БЛОК 1. ДОСТУПНОСТЬ КОНКРЕТНОГО ОБЪЕКТА\n"
            + object_context
            + "\n\n"
            + "БЛОК 2. ОБЩИЙ ОБЗОР ДОСТУПНЫХ ВАРИАНТОВ ПО ДАТАМ\n"
            + overview_context
        )
    else:
        availability_context = availability_context_for_llm(
            service_type=availability_query.get("service_type"),
            date=availability_query.get("date_from"),
            limit=1000,
        )

    logger.info("LLM_PREDECISION=%s", predecision)
    logger.info("LLM_AVAILABILITY_CONTEXT:\n%s", availability_context[:6000])

    payload = {
        "model": settings.answer_model,
        "temperature": settings.openai_temperature,
        "max_tokens": settings.answer_max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "decide_final_reply",
                        "today": today,
                        "recent_dialog": history or [],
                        "current_draft": draft.to_dict(),
                        "booking_flow_state": _booking_flow_state(draft),
                        "predecision": predecision,
                        "availability_query_used": availability_query,
                        "services_catalog": _compact_services_catalog(),
                        "media_catalog": _compact_media_catalog(),
                        "availability_cache": availability_context,
                        "knowledge": _load_knowledge(),
                        "message": text,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    try:
        content = _post_chat_completion(payload)
        logger.info("LLM_FINAL_RAW_RESPONSE=%s", content[:6000])
    except Exception as exc:
        logger.exception("LLM final decision failed: %s", exc)
        return fallback_decision(text)

    decision = _decision_from_json(content)
    if not decision:
        return fallback_decision(text)

    router_patch = predecision.get("fields_patch") or {}
    if router_patch:
        merged_patch = dict(router_patch)
        merged_patch.update(decision.fields_patch or {})
        decision.fields_patch = {key: value for key, value in merged_patch.items() if value not in (None, "", [])}

    proposed_draft = _draft_with_patch(draft, decision.fields_patch)

    # Отдельный LLM-шаг выравнивает финальный ответ по уже собранному draft.
    # Здесь код не решает, что говорить клиенту: он только передаёт модели факты
    # после применения fields_patch — next_step, точную цену и статус готовности.
    if proposed_draft.service_type:
        decision = _finalize_reply_with_flow_state(
            original_message=text,
            original_decision=decision,
            current_draft=draft,
            proposed_draft=proposed_draft,
            availability_context=availability_context,
            settings=settings,
        )
        proposed_draft = _draft_with_patch(draft, decision.fields_patch)

    # Финальная модель иногда игнорирует requested_media, потому что у неё слишком много задач.
    # Поэтому решение о фото выносим в отдельный маленький LLM-вызов: модель видит готовый ответ,
    # availability и media_catalog, и возвращает только список фото. Код сам не решает, где фото нужны.
    if not decision.requested_media:
        decision.requested_media = _decide_requested_media(
            reply=decision.reply,
            availability_context=availability_context,
            media_catalog=_compact_media_catalog(),
            settings=settings,
            current_draft=proposed_draft.to_dict(),
            booking_flow_state=_booking_flow_state(proposed_draft),
            decision_intent=decision.intent,
            ready_for_confirmation=decision.ready_for_confirmation,
            missing_fields=decision.missing_fields,
        )

    logger.info("LLM_MEDIA_DECISION requested_media=%s", decision.requested_media)

    return decision



def _finalize_reply_with_flow_state(
    *,
    original_message: str,
    original_decision: AdminDecision,
    current_draft: BookingDraft,
    proposed_draft: BookingDraft,
    availability_context: str,
    settings: Any,
) -> AdminDecision:
    price_info = _booking_price_info(proposed_draft)
    flow_state = _booking_flow_state(proposed_draft)

    system_prompt = """
Ты финально редактируешь ответ администратора базы отдыха после того, как LLM уже извлекла данные в draft.

Верни только JSON. Никакого текста вокруг.

Твоя задача — не менять логику бронирования, а сделать ответ корректным по текущему proposed_draft.
Код не должен хардкодить финальную сводку, поэтому её формируешь ты.

Строгие правила:
1. Всегда сначала отвечай на вопрос клиента, если в сообщении клиента был вопрос. Затем вернись к бронированию.
2. Не обещай ссылку на оплату и не пиши, что бронь подтверждена, если flow_state.next_required_step_before_message != "confirmation".
3. Если после сообщения клиента не хватает time — спроси только время. Не спрашивай гостей/формат/допы раньше времени.
4. Если не хватает duration — спроси длительность.
5. Если не хватает guests_count — спроси количество гостей.
6. Если не хватает event_format — спроси формат. Если клиент пишет «не знаю», можно записать event_format="отдых" и перейти дальше.
7. Допы предлагай только когда уже есть service_type, date, time, duration, guests_count и event_format.
8. Допы нужно предложить два раза. Если upsell_offer_count=0 и клиент отказался — предложи допы ещё раз, не переходи к имени/телефону. Если upsell_offer_count>=1 и клиент снова отказался — можно перейти к имени/телефону.
9. Если flow_state.next_required_step_before_message == "confirmation", покажи финальную сводку заявки и точную стоимость из price_info. Не выдумывай цену.
10. Для бани 8+ часов цена берётся только из price_info. Не пересчитывай её самостоятельно и не используй цену из старого ответа.
11. Если в исходном ответе есть противоречивая цена, замени её на price_info.price_rub.
12. requested_media не заполняй здесь, если бот собирает данные или показывает финальную сводку.

Формат ответа:
{
  "reply": "сообщение клиенту",
  "ready_for_confirmation": true или false,
  "fields_patch": {},
  "requested_media": []
}
""".strip()

    payload = {
        "model": settings.answer_model,
        "temperature": 0,
        "max_tokens": settings.finalizer_max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "finalize_reply_with_flow_state",
                        "message": original_message,
                        "original_decision": {
                            "reply": original_decision.reply,
                            "intent": original_decision.intent,
                            "fields_patch": original_decision.fields_patch,
                            "ready_for_confirmation": original_decision.ready_for_confirmation,
                            "missing_fields": original_decision.missing_fields,
                        },
                        "current_draft_before_message": current_draft.to_dict(),
                        "proposed_draft_after_message": proposed_draft.to_dict(),
                        "flow_state_after_message": flow_state,
                        "price_info": price_info,
                        "availability_context": availability_context[:5000],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    try:
        content = _post_chat_completion(payload)
        logger.info("LLM_FLOW_FINALIZER_RAW_RESPONSE=%s", content[:3000])
        data = _json_from_content(content) or {}
    except Exception as exc:
        logger.exception("LLM flow finalizer failed: %s", exc)
        return original_decision

    if not isinstance(data, dict):
        return original_decision

    reply = str(data.get("reply") or original_decision.reply or "").strip()
    if reply:
        original_decision.reply = _clean_reply(reply)

    patch = data.get("fields_patch")
    if isinstance(patch, dict) and patch:
        merged_patch = dict(original_decision.fields_patch or {})
        merged_patch.update({key: value for key, value in patch.items() if value not in (None, "", [])})
        original_decision.fields_patch = merged_patch

    media = data.get("requested_media")
    if isinstance(media, list):
        original_decision.requested_media = [str(item) for item in media if item]

    original_decision.ready_for_confirmation = bool(data.get("ready_for_confirmation") or False)
    return original_decision


def _draft_with_patch(draft: BookingDraft, patch: dict[str, Any] | None) -> BookingDraft:
    data = draft.to_dict()
    if not patch:
        return BookingDraft.from_dict(data)

    aliases = {"guests": "guests_count", "variant": "service_variant", "format": "event_format", "name": "client_name"}
    allowed = set(BookingDraft.__dataclass_fields__)
    for raw_key, raw_value in patch.items():
        key = aliases.get(raw_key, raw_key)
        if key not in allowed:
            continue
        if raw_value in (None, "", []):
            continue
        data[key] = raw_value
    return BookingDraft.from_dict(data)


def _booking_price_info(draft: BookingDraft) -> dict[str, Any]:
    price = calculate_booking_price(draft)
    duration = draft.duration
    try:
        duration_hours = int(float(duration)) if duration is not None else None
    except (TypeError, ValueError):
        duration_hours = None

    return {
        "price_rub": price,
        "service_type": draft.service_type,
        "duration_hours": duration_hours,
        "bathhouse_extra_hour_price_rub": BATHHOUSE_EXTRA_HOUR_PRICE_RUB,
        "rule": "Для бани дольше 7 часов: цена за 7 часов + 1500 ₽ за каждый дополнительный час.",
    }

def _decide_requested_media(
    *,
    reply: str,
    availability_context: str,
    media_catalog: dict[str, Any],
    settings: Any,
    current_draft: dict[str, Any],
    booking_flow_state: dict[str, Any],
    decision_intent: str,
    ready_for_confirmation: bool,
    missing_fields: list[str],
) -> list[str]:
    if not media_catalog:
        logger.info("LLM_MEDIA_SKIP empty_media_catalog=true")
        return []

    system_prompt = """
Ты решаешь, какие фото объектов нужно отправить клиенту после готового ответа бота.

Верни только JSON. Никакого текста вокруг.

Главный принцип:
Фото нужны, когда клиент выбирает объект. Фото НЕ нужны, когда бот уже оформляет конкретную бронь и собирает недостающие данные.

Верни [] если ответ бота:
- спрашивает время, длительность, формат мероприятия, количество гостей, имя или телефон;
- показывает финальную сводку/подтверждение уже выбранной брони;
- говорит про оплату или ссылку на оплату;
- отвечает на уточняющий вопрос внутри оформления и потом возвращает к сбору данных;
- начинается по смыслу с «отлично, выбрали...» / «записала...» / «уточните...» и не предлагает выбрать другой объект.

Фото нужны обязательно, если ответ бота:
- показывает список свободных вариантов на дату;
- предлагает клиенту выбрать из нескольких объектов;
- рекомендует конкретные альтернативные объекты вместо занятого.

Добавляй только объекты, которые упомянуты в ответе бота и есть в media_catalog.
Не добавляй объект, если в availability_context он находится в блоке НЕДОСТУПНО на обсуждаемую дату.
Для бани используй "bathhouse".
Для гостевого дома используй "house".
Для тёплой беседки используй "Тёплая беседка".
Для крытой беседки используй "Крытая беседка".
Для обычных беседок используй полные названия: "Беседка №1", "Беседка №2" и так далее.
Максимум 10 элементов.

Формат ответа строго такой:
{
  "requested_media": []
}
""".strip()

    payload = {
        "model": settings.parser_model,
        "temperature": 0,
        "max_tokens": settings.media_max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "decide_requested_media",
                        "bot_reply": reply,
                        "current_draft": current_draft,
                        "booking_flow_state": booking_flow_state,
                        "decision_intent": decision_intent,
                        "ready_for_confirmation": ready_for_confirmation,
                        "missing_fields": missing_fields,
                        "availability_context": availability_context[:7000],
                        "media_catalog": media_catalog,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    try:
        content = _post_chat_completion(payload)
        logger.info("LLM_MEDIA_RAW_RESPONSE=%s", content[:2000])
        data = _json_from_content(content) or {}
    except Exception as exc:
        logger.exception("LLM media decision failed: %s", exc)
        return []

    requested = data.get("requested_media") or []
    if not isinstance(requested, list):
        return []

    allowed = set(media_catalog.keys())
    result: list[str] = []
    for item in requested:
        title = str(item).strip()
        if title in allowed and title not in result:
            result.append(title)
        if len(result) >= 10:
            break

    return result


def _decide_data_request(
    text: str,
    draft: BookingDraft,
    *,
    today: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    settings = get_settings()

    payload = {
        "model": settings.parser_model,
        "temperature": 0,
        "max_tokens": settings.parser_max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": ROUTER_PROMPT_PATH.read_text(encoding="utf-8")},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "route_data_request",
                        "today": today,
                        "recent_dialog": history or [],
                        "current_draft": draft.to_dict(),
                        "services_catalog": _compact_services_catalog(),
                        "message": text,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    try:
        content = _post_chat_completion(payload)
        data = _json_from_content(content) or {}
    except Exception as exc:
        logger.exception("LLM router failed: %s", exc)
        data = {}

    if not isinstance(data, dict):
        data = {}

    data.setdefault("intent", "other")
    data["availability_query"] = _normalize_availability_query(data.get("availability_query"))
    fields_patch = data.get("fields_patch") or data.get("form_data_patch") or {}
    data["fields_patch"] = fields_patch if isinstance(fields_patch, dict) else {}

    return data


def _normalize_availability_query(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}

    mode = value.get("mode") or "date_overview"
    if mode not in {"date_overview", "object_dates"}:
        mode = "date_overview"

    service_type = value.get("service_type")
    if service_type in ("", "null", "None"):
        service_type = None

    if service_type not in {None, "gazebo", "bathhouse", "house", "warm_gazebo"}:
        service_type = None

    date_from = value.get("date_from") or value.get("date")
    date_to = value.get("date_to") or date_from
    object_title = value.get("object_title")

    if object_title in ("", "null", "None"):
        object_title = None

    return {
        "mode": mode,
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
        "service_type": service_type,
        "object_title": str(object_title) if object_title else None,
    }


def _llm_api_key(settings: Any) -> str:
    # Priority: OpenAI key, generic aliases, OpenRouter key, then old DeepSeek key for backward compatibility.
    return str(
        getattr(settings, "openai_api_key", "")
        or getattr(settings, "ai_api_key", "")
        or getattr(settings, "api_key", "")
        or getattr(settings, "openrouter_api_key", "")
        or getattr(settings, "deepseek_api_key", "")
        or ""
    ).strip()


def _llm_base_url(settings: Any) -> str:
    return str(getattr(settings, "openai_base_url", "") or getattr(settings, "deepseek_base_url", "") or "https://api.openai.com/v1").rstrip("/")


def _post_chat_completion(payload: dict[str, Any]) -> str:
    settings = get_settings()
    api_key = _llm_api_key(settings)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is empty")

    base_url = _llm_base_url(settings)
    primary_model = str(payload.get("model") or settings.answer_model)
    fallback_model = str(getattr(settings, "answer_fallback_model", "") or "").strip()

    models = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models.append(fallback_model)

    max_retries = max(1, int(getattr(settings, "llm_max_retries", 3) or 3))
    timeout = float(getattr(settings, "llm_request_timeout_seconds", 45) or 45)
    last_error: Exception | None = None

    try:
        with httpx.Client(timeout=timeout) as client:
            for model_index, model in enumerate(models):
                model_payload = dict(payload)
                model_payload["model"] = model

                if model_index > 0:
                    logger.warning(
                        "LLM_FALLBACK_MODEL from=%s to=%s",
                        primary_model,
                        model,
                    )

                for attempt in range(1, max_retries + 1):
                    try:
                        logger.info(
                            "LLM_REQUEST model=%s base_url=%s attempt=%s/%s",
                            model,
                            base_url,
                            attempt,
                            max_retries,
                        )

                        response = client.post(
                            f"{base_url}/chat/completions",
                            headers={"Authorization": f"Bearer {api_key}"},
                            json=model_payload,
                        )

                        if response.status_code == 429:
                            sleep_seconds = _llm_retry_sleep_seconds(response, attempt, settings)
                            logger.warning(
                                "LLM_RATE_LIMIT model=%s attempt=%s/%s sleep=%.2f retry_after=%s",
                                model,
                                attempt,
                                max_retries,
                                sleep_seconds,
                                response.headers.get("retry-after"),
                            )
                            _RATE_LIMIT_EVENT.set()
                            time.sleep(sleep_seconds)
                            continue

                        if response.status_code >= 500 and attempt < max_retries:
                            sleep_seconds = _llm_retry_sleep_seconds(response, attempt, settings)
                            logger.warning(
                                "LLM_SERVER_RETRY model=%s status=%s attempt=%s/%s sleep=%.2f",
                                model,
                                response.status_code,
                                attempt,
                                max_retries,
                                sleep_seconds,
                            )
                            time.sleep(sleep_seconds)
                            continue

                        if response.status_code >= 400:
                            logger.error(
                                "LLM_HTTP_ERROR status=%s body=%s",
                                response.status_code,
                                response.text[:2000],
                            )

                        response.raise_for_status()
                        content = str(response.json()["choices"][0]["message"]["content"])

                        if attempt > 1 or model_index > 0:
                            logger.info(
                                "LLM_RETRY_SUCCESS model=%s attempt=%s fallback_used=%s",
                                model,
                                attempt,
                                model_index > 0,
                            )

                        return content

                    except httpx.HTTPStatusError as exc:
                        last_error = exc
                        status_code = exc.response.status_code if exc.response is not None else None

                        if status_code == 429 and attempt < max_retries:
                            sleep_seconds = _llm_retry_sleep_seconds(exc.response, attempt, settings)
                            logger.warning(
                                "LLM_RATE_LIMIT_EXCEPTION model=%s attempt=%s/%s sleep=%.2f",
                                model,
                                attempt,
                                max_retries,
                                sleep_seconds,
                            )
                            _RATE_LIMIT_EVENT.set()
                            time.sleep(sleep_seconds)
                            continue

                        if status_code and status_code >= 500 and attempt < max_retries:
                            sleep_seconds = _llm_retry_sleep_seconds(exc.response, attempt, settings)
                            logger.warning(
                                "LLM_HTTP_RETRY model=%s status=%s attempt=%s/%s sleep=%.2f",
                                model,
                                status_code,
                                attempt,
                                max_retries,
                                sleep_seconds,
                            )
                            time.sleep(sleep_seconds)
                            continue

                        break

                    except httpx.RequestError as exc:
                        last_error = exc
                        if attempt < max_retries:
                            sleep_seconds = _llm_retry_sleep_seconds(None, attempt, settings)
                            logger.warning(
                                "LLM_NETWORK_RETRY model=%s attempt=%s/%s sleep=%.2f error=%s",
                                model,
                                attempt,
                                max_retries,
                                sleep_seconds,
                                exc,
                            )
                            time.sleep(sleep_seconds)
                            continue
                        break

    finally:
        _RATE_LIMIT_EVENT.clear()

    if last_error:
        raise last_error
    raise RuntimeError(f"LLM request failed for model={primary_model}")


def _llm_retry_sleep_seconds(response: httpx.Response | None, attempt: int, settings: Any) -> float:
    retry_after = _parse_retry_after(response.headers.get("retry-after") if response is not None else None)
    if retry_after is not None:
        return min(retry_after, float(getattr(settings, "llm_retry_max_seconds", 8) or 8))

    base = float(getattr(settings, "llm_retry_base_seconds", 1.5) or 1.5)
    max_sleep = float(getattr(settings, "llm_retry_max_seconds", 8) or 8)
    jitter = random.uniform(0.0, 0.35)
    return min(max_sleep, base * (2 ** max(0, attempt - 1)) + jitter)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None

    value = value.strip()

    try:
        seconds = float(value)
        if seconds >= 0:
            return seconds
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)
        return max(0.0, retry_at.timestamp() - time.time())
    except Exception:
        return None


def fallback_decision(text: str) -> AdminDecision:
    return AdminDecision(
        reply="Подскажите, что хотите забронировать: беседку, баню, дом или тёплую беседку?",
        intent="info",
        fields_patch={},
        action=AdminAction("none"),
        confidence=0.0,
        ready_for_confirmation=False,
    )


def _json_from_content(content: str) -> dict[str, Any] | None:
    raw = content.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.I | re.M).strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        raw = match.group(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Cannot parse JSON from LLM content=%r", content[:1000])
        return None
    return data if isinstance(data, dict) else None


def _decision_from_json(content: str) -> AdminDecision | None:
    data = _json_from_content(content)
    if not data:
        return None

    action_raw = data.get("action") or "none"
    if isinstance(action_raw, dict):
        action_type = str(action_raw.get("type") or "none")
        action_params = dict(action_raw.get("params") or {})
    else:
        action_type = str(action_raw)
        action_params = {}

    fields_patch = data.get("form_data_patch") or data.get("fields_patch") or {}
    if not fields_patch and isinstance(data.get("draft"), dict):
        fields_patch = {key: value for key, value in data["draft"].items() if value not in (None, "", [])}

    requested_media = data.get("requested_media") or []
    if not isinstance(requested_media, list):
        requested_media = []

    return AdminDecision(
        reply=_clean_reply(str(data.get("reply_to_user") or data.get("reply") or "")),
        intent=str(data.get("intent") or "unknown"),
        fields_patch={key: value for key, value in fields_patch.items() if value not in (None, "", [])},
        action=AdminAction(type=action_type, params=action_params),
        missing_fields=list(data.get("missing_fields") or []),
        confidence=float(data.get("confidence") or 0),
        requested_media=[str(item) for item in requested_media if item],
        ready_for_confirmation=bool(data.get("ready_for_confirmation") or False),
    )


def _clean_reply(reply: str) -> str:
    return sanitize_reply(reply, fallback="Подскажите подробнее, что хотите забронировать или уточнить?")


def _booking_flow_state(draft: BookingDraft) -> dict[str, Any]:
    next_step = draft.next_step()
    core_ready_for_upsell = bool(
        draft.service_type
        and draft.date
        and draft.time
        and draft.duration
        and draft.guests_count
        and draft.event_format
    )
    return {
        "next_required_step_before_message": next_step,
        "ready_for_confirmation_before_message": draft.ready_for_confirmation(),
        "payment_allowed_now": draft.ready_for_confirmation(),
        "core_ready_for_upsell": core_ready_for_upsell,
        "upsell_offer_count": draft.upsell_offer_count,
        "upsell_done": draft.upsell_done,
        "required_order": [
            "service_type",
            "date",
            "service_variant для обычной беседки",
            "time",
            "duration",
            "guests_count",
            "event_format",
            "upsell_items минимум 2 предложения допов",
            "client_name",
            "phone",
            "confirmation",
        ],
        "rule": "Если next_required_step_before_message не confirmation, нельзя писать что бронь подтверждена или что ссылка на оплату будет отправлена. Сначала ответь на вопрос клиента, затем спроси ровно следующий недостающий пункт. Допы нельзя предлагать до заполнения time, duration, guests_count и event_format.",
    }


def _compact_services_catalog() -> dict[str, Any]:
    catalog: dict[str, Any] = {}
    for service_type, service in load_services().items():
        variants = []
        for variant in service.get("variants") or []:
            variants.append(
                {
                    "title": variant.get("title"),
                    "capacity_max": variant.get("capacity_max"),
                    "price": variant.get("price"),
                    "duration_minutes": variant.get("duration_minutes"),
                    "weekdays": variant.get("weekdays"),
                }
            )
        item = {
            "title": service.get("title"),
            "capacity_max": service.get("capacity_max"),
            "price": service.get("price"),
            "default_duration_minutes": service.get("default_duration_minutes"),
            "variants": variants[:30],
        }
        if service_type == "bathhouse":
            item["duration_rule"] = {
                "can_book_more_than_7_hours": True,
                "base_duration_hours": 7,
                "extra_hour_price_rub": BATHHOUSE_EXTRA_HOUR_PRICE_RUB,
                "instruction": "Если клиент просит 8 часов или больше, это разрешено при доступности варианта на 7 часов. Не говори, что максимум 7 часов.",
            }
        catalog[service_type] = item
    return catalog


def _compact_media_catalog() -> dict[str, Any]:
    # Фотки в этом проекте лежат не в services.yaml, а в app/images + app/bot/media.py.
    # Для LLM нужен не путь к файлу, а список допустимых названий, которые потом понимает media.py.
    return {
        "bathhouse": {"title": "Баня с бассейном"},
        "house": {"title": "Гостевой дом"},
        "Тёплая беседка": {"title": "Тёплая беседка"},
        "Теплая беседка": {"title": "Теплая беседка"},
        "Крытая беседка": {"title": "Крытая беседка"},
        "Беседка №1": {"title": "Беседка №1"},
        "Беседка №2": {"title": "Беседка №2"},
        "Беседка №3": {"title": "Беседка №3"},
        "Беседка №4": {"title": "Беседка №4"},
        "Беседка №5": {"title": "Беседка №5"},
        "Беседка №6": {"title": "Беседка №6"},
        "Беседка №8": {"title": "Беседка №8"},
    }
