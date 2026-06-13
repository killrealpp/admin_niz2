from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from datetime import datetime, timedelta
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

_CLEARABLE_DRAFT_FIELDS = {
    "service_type",
    "service_variant",
    "date",
    "time",
    "duration",
    "guests_count",
    "event_format",
    "upsell_items",
    "upsell_done",
    "client_name",
    "phone",
}

_READ_ONLY_SELECTION_INTENTS = {
    "availability_question",
    "recommendation_request",
    "alternative_request",
    "alternatives_request",
    "date_refinement",
    "info_question",
    "other",
}

# Для read-only запросов нельзя начинать оформление нового объекта,
# но нельзя выкидывать полезные данные вроде имени/телефона из сообщения
# «Савелий, 8902..., а парковка большая?».
_SELECTION_FIELDS = {"service_type", "service_variant"}


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

    predecision = _apply_date_refinement_context(predecision, draft, today=today)
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
    logger.debug("LLM_AVAILABILITY_CONTEXT:\n%s", availability_context[:6000])

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
        logger.info("LLM_FINAL_RAW_RESPONSE=%s", content[:1200])
    except Exception as exc:
        logger.exception("LLM final decision failed: %s", exc)
        return fallback_decision(text)

    decision = _decision_from_json(content)
    if not decision:
        return fallback_decision(text)

    predecision_intent = str(predecision.get("intent") or "other")
    router_action = predecision.get("action") or {}
    if (not decision.action or decision.action.type == "none") and isinstance(router_action, dict):
        action_type = str(router_action.get("type") or "none")
        action_params = dict(router_action.get("params") or {})
        if action_type != "none" and _router_action_allowed(action_type, action_params, predecision.get("intent"), draft):
            decision.action = AdminAction(type=action_type, params=action_params)

    # Важно: LLM может рекомендовать единственный свободный объект и вернуть его в draft.
    # Но рекомендация НЕ равна выбору клиента. В fields_patch оставляем только явно
    # подтверждённые клиентом поля; для запросов подбора/доступности не записываем объект.
    router_patch = _sanitize_fields_patch(predecision.get("fields_patch") or {})
    decision_patch = _sanitize_fields_patch(decision.fields_patch or {})

    merged_patch = dict(router_patch)
    merged_patch.update(decision_patch)
    decision.fields_patch = _guard_fields_patch_by_intent(
        merged_patch,
        predecision_intent=predecision_intent,
        current_draft=draft,
    )
    decision.fields_patch = _enforce_upsell_two_step(
        decision.fields_patch,
        reply=decision.reply,
        current_draft=draft,
    )

    proposed_draft = _draft_with_patch(draft, decision.fields_patch)

    # Важно: отдельный LLM-finalizer отключён.
    # Он начал спорить с основным решением: додумывал duration=3, сушил ответы,
    # возвращал допы и мог менять action. Дальше flow защищают только кодовые guard'ы.
    decision.fields_patch = _guard_no_default_duration(
        decision.fields_patch,
        message=text,
        current_draft=draft,
    )
    decision.fields_patch = _drop_null_overwrites_unless_clear_intent(
        decision.fields_patch,
        predecision_intent=predecision_intent,
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

    final_draft_for_reply = _draft_with_patch(draft, decision.fields_patch)
    decision.requested_media = _filter_requested_media_by_active_draft(
        decision.requested_media,
        final_draft_for_reply,
        current_draft=draft,
        predecision_intent=predecision_intent,
    )
    decision.reply = _canonicalize_price_in_reply(decision.reply, final_draft_for_reply)
    logger.info("LLM_MEDIA_DECISION requested_media=%s", decision.requested_media)

    return decision



def _router_action_allowed(action_type: str, params: dict[str, Any], intent: Any, draft: BookingDraft) -> bool:
    """Do not let the router accidentally reset an active booking on confirmation/payment.

    The previous bug was: router returned action=new_booking on "все верно",
    engine reset the draft, and the next "оплачу" started from empty state.
    """
    if action_type == "new_booking":
        explicit = bool(params.get("explicit") or params.get("confirmed") or params.get("confirmed_new_booking"))
        has_active_draft = bool(draft.service_type or draft.date or draft.time or draft.duration or draft.guests_count or draft.client_name or draft.phone)
        if has_active_draft and not explicit:
            logger.warning("ROUTER_ACTION_BLOCKED action=new_booking intent=%s active_draft=True params=%s", intent, params)
            return False
    return True


def _finalizer_lost_useful_context(original_reply: str, final_reply: str) -> bool:
    original = (original_reply or "").strip()
    final = (final_reply or "").strip()
    if not original or not final:
        return False
    if len(final) >= max(80, int(len(original) * 0.7)):
        return False
    final_l = final.lower().replace("ё", "е")
    original_l = original.lower().replace("ё", "е")
    final_is_bare_question = final.endswith("?") and not any(w in final_l for w in ("запис", "понял", "принял", "доступ", "стоим", "итого", "состав"))
    original_has_context = any(w in original_l for w in ("запис", "понял", "принял", "доступ", "с ", "это ", "стоим", "итого", "состав"))
    return bool(final_is_bare_question and original_has_context)


def _canonicalize_price_in_reply(reply: str, draft: BookingDraft) -> str:
    if not reply:
        return reply
    price = calculate_booking_price(draft)
    if not price:
        return reply
    price_text = f"{price:,}".replace(",", " ")
    patterns = [
        r"(общая стоимость(?:\s+составит|\s*[:—-])?\s*)\d[\d\s]*(?:руб(?:\.|лей)?|₽)",
        r"(стоимость(?:\s+составит|\s*[:—-])\s*)\d[\d\s]*(?:руб(?:\.|лей)?|₽)",
        r"(итого(?:\s*[:—-])?\s*)\d[\d\s]*(?:руб(?:\.|лей)?|₽)",
    ]
    result = reply
    for pattern in patterns:
        result = re.sub(pattern, lambda m: f"{m.group(1)}{price_text} ₽", result, flags=re.I)
    return result


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
8. Допы нужно предложить два раза перед переходом к имени/телефону. Если upsell_offer_count=0 — сделай первое предложение допов и верни fields_patch.upsell_offer_count=1, upsell_done=false. Если upsell_offer_count=1 и клиент отказался или прислал имя/телефон — всё равно сделай второе короткое предложение допов, сохрани имя/телефон в fields_patch при наличии, верни upsell_offer_count=2, upsell_done=false. Только если upsell_offer_count>=2 и клиент снова отказался — можно поставить upsell_done=true и перейти к имени/телефону/подтверждению.
9. Если flow_state.next_required_step_before_message == "confirmation", покажи финальную сводку заявки и точную стоимость из price_info. Не выдумывай цену.
10. Для бани 8+ часов цена берётся только из price_info. Не пересчитывай её самостоятельно и не используй цену из старого ответа.
11. Если в исходном ответе есть противоречивая цена, замени её на price_info.price_rub.
12. requested_media не заполняй здесь, если бот собирает данные или показывает финальную сводку.
13. Если flow_state.upsell_locked=true, запрещено снова предлагать дополнительные услуги, баню, питание, кальян, комфортные добавки и любые допы. Тема допов уже закрыта.
14. Предлагай только допы из upsell_catalog/services_catalog. Нельзя выдумывать массаж, ресторан, питание и любые услуги, которых нет в базе.
15. Если клиент просит оплату или ссылку на оплату, и flow_state.payment_allowed_now=true, верни wants_payment=true и action.type="create_payment". Не предлагай допы и не задавай новых вопросов.
16. Не сокращай хороший исходный ответ. Если original_decision.reply уже подтверждает полученное поле и задаёт следующий вопрос, оставь его смысл и детали. Например: «Поняла, с 12:00 до 22:00, это 10 часов. Сколько гостей?» лучше, чем просто «Сколько гостей?».

Формат ответа:
{
  "reply": "сообщение клиенту",
  "ready_for_confirmation": true или false,
  "fields_patch": {},
  "requested_media": [],
  "wants_payment": true или false,
  "action": {"type": "none", "params": {}}
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
                            "wants_payment": getattr(original_decision, "wants_payment", False),
                            "action": original_decision.action.__dict__ if original_decision.action else {"type": "none", "params": {}},
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
        logger.info("LLM_FLOW_FINALIZER_RAW_RESPONSE=%s", content[:1200])
        data = _json_from_content(content) or {}
    except Exception as exc:
        logger.exception("LLM flow finalizer failed: %s", exc)
        return original_decision

    if not isinstance(data, dict):
        return original_decision

    reply = str(data.get("reply") or original_decision.reply or "").strip()
    if reply:
        cleaned_reply = _clean_reply(reply)
        if _finalizer_lost_useful_context(original_decision.reply, cleaned_reply):
            original_decision.reply = _clean_reply(original_decision.reply)
        else:
            original_decision.reply = cleaned_reply

    if "wants_payment" in data:
        original_decision.wants_payment = bool(data.get("wants_payment"))

    action_raw = data.get("action")
    if isinstance(action_raw, dict):
        action_type = str(action_raw.get("type") or "none")
        if action_type != "none":
            original_decision.action = AdminAction(type=action_type, params=dict(action_raw.get("params") or {}))

    patch = data.get("fields_patch")
    if isinstance(patch, dict) and patch:
        merged_patch = dict(original_decision.fields_patch or {})
        merged_patch.update({key: value for key, value in patch.items() if value not in (None, "", [])})
        original_decision.fields_patch = merged_patch

    media = data.get("requested_media")
    if isinstance(media, list):
        original_decision.requested_media = _normalize_requested_media_items(media)

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

        # None в fields_patch — это явное очищение поля. Нужно для сценариев
        # «не хочу пятую», «давайте не на 13», «посмотрим другое».
        if raw_value is None:
            if key in _CLEARABLE_DRAFT_FIELDS:
                data[key] = None
            continue

        if raw_value in ("", []):
            continue
        data[key] = raw_value
    return BookingDraft.from_dict(data)


def _sanitize_fields_patch(patch: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(patch, dict):
        return {}

    aliases = {"guests": "guests_count", "variant": "service_variant", "format": "event_format", "name": "client_name"}
    allowed = set(BookingDraft.__dataclass_fields__)
    result: dict[str, Any] = {}

    for raw_key, value in patch.items():
        key = aliases.get(raw_key, raw_key)
        if key not in allowed:
            continue
        if value in ("", []):
            continue
        if value is None and key not in _CLEARABLE_DRAFT_FIELDS:
            continue
        result[key] = value

    return result


def _guard_fields_patch_by_intent(
    patch: dict[str, Any],
    *,
    predecision_intent: str,
    current_draft: BookingDraft,
) -> dict[str, Any]:
    result = dict(patch or {})

    # Если клиент просит посмотреть/подобрать/посоветовать, не записываем в draft
    # объект, который модель сама рекомендовала. Можно сохранять дату/гостей как
    # контекст для follow-up, но не начинать оформление без явного выбора.
    if predecision_intent in _READ_ONLY_SELECTION_INTENTS:
        for key in list(result.keys()):
            if key in _SELECTION_FIELDS:
                result.pop(key, None)

    # reset — клиент отказался от текущего выбранного сценария/даты. Старый объект
    # нельзя оставлять в draft, иначе следующий ответ снова продолжит его оформление.
    if predecision_intent == "reset":
        result.setdefault("service_type", None)
        result.setdefault("service_variant", None)
        result.setdefault("date", None)
        result.setdefault("time", None)
        result.setdefault("duration", None)
        result.setdefault("event_format", None)

    # change_booking с service_variant=None должен реально очистить вариант.
    # Если вариант очищен, время тоже уже невалидно.
    if result.get("service_variant") is None and "service_variant" in result:
        result.setdefault("time", None)

    return result




def _drop_null_overwrites_unless_clear_intent(patch: dict[str, Any], *, predecision_intent: str) -> dict[str, Any]:
    result = dict(patch or {})
    if predecision_intent in {"reset", "change_booking"}:
        return result
    return {key: value for key, value in result.items() if value is not None}


def _guard_no_default_duration(
    patch: dict[str, Any],
    *,
    message: str,
    current_draft: BookingDraft,
) -> dict[str, Any]:
    """Do not let the model invent duration while the user only answered time."""
    result = dict(patch or {})
    if "duration" not in result:
        return result

    if current_draft.next_step() == "time" and "time" in result and not _message_has_explicit_duration(message):
        logger.warning(
            "GUARD_DROP_DEFAULT_DURATION message=%r time=%r dropped_duration=%r",
            message,
            result.get("time"),
            result.get("duration"),
        )
        result.pop("duration", None)

    return result


def _message_has_explicit_duration(message: str) -> bool:
    text = (message or "").lower().replace("ё", "е")
    if " до " in f" {text} " or re.search(r"\b\d{1,2}(?::\d{2})?\s*[-–—]\s*\d{1,2}(?::\d{2})?\b", text):
        return True
    if any(word in text for word in ("длитель", "аренд", "на весь", "сутк")):
        return True
    if re.search(r"\b(3|4|5|6|7|8|9|10|11)\s*(?:ч|час|часа|часов)\b", text):
        return True
    return False


def _filter_requested_media_by_active_draft(
    requested_media: list[str] | None,
    draft: BookingDraft,
    *,
    current_draft: BookingDraft | None = None,
    predecision_intent: str,
) -> list[str]:
    items = _normalize_requested_media_items(requested_media or [])
    if not items:
        return []

    # If the user is already booking the same object type and only уточняет дату /
    # продолжает сбор полей, do not resend the same photos. Text remains LLM-made;
    # this guard only prevents duplicate media side effects.
    if current_draft and current_draft.service_type and draft.service_type == current_draft.service_type:
        if predecision_intent in {"availability_question", "booking_request", "continue_booking", "info_question", "other"}:
            return []

    if predecision_intent in {"availability_question", "recommendation_request", "alternative_request", "alternatives_request"}:
        # For selection/availability output, still don't allow media from a different
        # active service type. This prevents bathhouse flow from sending gazebo photos.
        if draft.service_type == "bathhouse":
            return [item for item in items if item == "bathhouse"]
        if draft.service_type == "house":
            return [item for item in items if item == "house"]
        if draft.service_type == "warm_gazebo":
            return [item for item in items if item in {"Тёплая беседка", "Теплая беседка"}]
        if draft.service_type == "gazebo":
            if draft.service_variant:
                return [item for item in items if item == draft.service_variant]
            return [item for item in items if item.startswith("Беседка №") or item == "Крытая беседка"]
        return items

    if draft.service_type == "bathhouse":
        return [item for item in items if item == "bathhouse"]
    if draft.service_type == "house":
        return [item for item in items if item == "house"]
    if draft.service_type == "warm_gazebo":
        return [item for item in items if item in {"Тёплая беседка", "Теплая беседка"}]
    if draft.service_type == "gazebo":
        if draft.service_variant:
            return [item for item in items if item == draft.service_variant]
        return [item for item in items if item.startswith("Беседка №") or item == "Крытая беседка"]

    return items


def _enforce_upsell_two_step(
    patch: dict[str, Any],
    *,
    reply: str,
    current_draft: BookingDraft,
) -> dict[str, Any]:
    """State-level safety for the two-offer upsell flow.

    The LLM still writes the customer-facing answer. This guard only prevents
    the draft from skipping the second upsell attempt when the model marks
    upsell_done too early.
    """
    result = dict(patch or {})

    future = _draft_with_patch(current_draft, result)
    core_ready = bool(
        future.service_type
        and future.date
        and future.time
        and future.duration
        and future.guests_count
        and future.event_format
    )

    if not core_ready:
        return result

    current_count = int(current_draft.upsell_offer_count or 0)
    # После двух предложений тема допов закрывается. Модель может отвечать живым текстом,
    # но состояние не должно откатываться назад и запускать третий оффер.
    if bool(current_draft.upsell_done) or current_count >= 2:
        result.pop("upsell_offer_count", None)
        result["upsell_done"] = True
        return result

    patched_count = result.get("upsell_offer_count")
    try:
        target_count = int(patched_count) if patched_count is not None else current_count
    except (TypeError, ValueError):
        target_count = current_count

    has_accepted_items = bool(result.get("upsell_items") or current_draft.upsell_items)

    if not has_accepted_items and current_count == 0 and target_count == 0 and _reply_mentions_upsell(reply):
        result["upsell_offer_count"] = 1
        result["upsell_done"] = False
        return result

    if result.get("upsell_done") is True and not has_accepted_items and target_count < 2:
        # If the booking already has contact details, do not keep the flow stuck
        # on upsells forever. The model may close upsells after the user answers
        # a repeated refusal/confirmation, even if it forgot to bump the counter.
        if future.client_name and future.phone:
            result["upsell_offer_count"] = 2
            result["upsell_done"] = True
        else:
            result["upsell_done"] = False
            result["upsell_offer_count"] = max(current_count, target_count, 1)

    return result


def _reply_mentions_upsell(reply: str) -> bool:
    text = (reply or "").lower().replace("ё", "е")
    return any(word in text for word in ("доп", "уголь", "розжиг", "решет", "посуда", "лед", "кальян"))


def _should_run_flow_finalizer(
    predecision_intent: str,
    fields_patch: dict[str, Any],
    proposed_draft: BookingDraft,
) -> bool:
    # Deprecated: the extra LLM finalizer is intentionally disabled.
    return False

    if not proposed_draft.service_type:
        return False

    if predecision_intent in {"reset", "availability_question", "recommendation_request", "alternative_request", "alternatives_request", "info_question"}:
        return False

    # Если текущий ход только очищает выбор, finalizer не должен возвращать старую
    # заявку к жизни и спрашивать время по старому объекту.
    if any(value is None for value in (fields_patch or {}).values()):
        return False

    return True


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
        logger.debug("LLM_MEDIA_RAW_RESPONSE=%s", content[:1200])
        data = _json_from_content(content) or {}
    except Exception as exc:
        logger.exception("LLM media decision failed: %s", exc)
        return []

    requested = data.get("requested_media") or []
    if not isinstance(requested, list):
        return []

    allowed = set(media_catalog.keys())
    result: list[str] = []
    for title in _normalize_requested_media_items(requested):
        if title in allowed and title not in result:
            result.append(title)
        if len(result) >= 10:
            break

    return result


def _normalize_requested_media_items(items: list[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("name") or item.get("id") or "").strip()
        else:
            title = str(item).strip()

        if not title:
            continue

        if title == "Баня с бассейном":
            title = "bathhouse"
        elif title == "Гостевой дом":
            title = "house"
        elif title == "Теплая беседка":
            title = "Тёплая беседка"

        if title and title not in result:
            result.append(title)
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


def _apply_date_refinement_context(predecision: dict[str, Any], draft: BookingDraft, *, today: str) -> dict[str, Any]:
    """Convert the router's semantic date-refinement intent into a scoped availability query.

    This is not a phrase hack: the router/LLM decides intent=date_refinement.
    Code only turns that structured intent plus saved last_offered_dates into
    a query for the same object after the previously offered dates.
    """
    if not isinstance(predecision, dict):
        return {}

    intent = str(predecision.get("intent") or "")
    if intent != "date_refinement":
        return predecision

    offered = sorted(str(item) for item in (getattr(draft, "last_offered_dates", None) or []) if item)
    if not offered:
        return predecision

    last_date = offered[-1]
    try:
        date_from = (datetime.fromisoformat(last_date).date() + timedelta(days=1)).isoformat()
    except Exception:
        date_from = today

    service_type = getattr(draft, "last_offered_service_type", None) or draft.service_type
    object_title = getattr(draft, "last_offered_object_title", None)
    if not object_title and service_type == "bathhouse":
        object_title = "Баня с бассейном"
    elif not object_title and service_type == "house":
        object_title = "Гостевой дом"
    elif not object_title and service_type == "warm_gazebo":
        object_title = "Теплая беседка"
    elif not object_title and draft.service_variant:
        object_title = draft.service_variant

    if object_title:
        query = {
            "mode": "object_dates",
            "date_from": date_from,
            "date_to": None,
            "service_type": service_type,
            "object_title": object_title,
        }
    else:
        query = {
            "mode": "date_overview",
            "date_from": date_from,
            "date_to": None,
            "service_type": service_type,
            "object_title": None,
        }

    predecision = dict(predecision)
    predecision["availability_query"] = query
    predecision.setdefault("fields_patch", {})
    logger.info("DATE_REFINEMENT_CONTEXT last_offered=%s query=%s", offered, query)
    return predecision


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
        wants_payment=False,
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
        # Старые промпты могли возвращать draft целиком вместо fields_patch.
        # Берём только заполненные значения; явные null-очистки должны приходить
        # именно через fields_patch, иначе полный draft с null сотрёт заявку.
        fields_patch = {key: value for key, value in data["draft"].items() if value not in (None, "", [])}

    requested_media = data.get("requested_media") or []
    if not isinstance(requested_media, list):
        requested_media = []

    return AdminDecision(
        reply=_clean_reply(str(data.get("reply_to_user") or data.get("reply") or "")),
        intent=str(data.get("intent") or "unknown"),
        fields_patch=_sanitize_fields_patch(fields_patch),
        action=AdminAction(type=action_type, params=action_params),
        missing_fields=list(data.get("missing_fields") or []),
        confidence=float(data.get("confidence") or 0),
        requested_media=_normalize_requested_media_items(requested_media),
        ready_for_confirmation=bool(data.get("ready_for_confirmation") or False),
        wants_payment=bool(data.get("wants_payment") or False),
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
    upsell_count = int(draft.upsell_offer_count or 0)
    must_offer_second_upsell = bool(core_ready_for_upsell and not draft.upsell_done and upsell_count == 1)
    return {
        "next_required_step_before_message": next_step,
        "ready_for_confirmation_before_message": draft.ready_for_confirmation(),
        "payment_allowed_now": draft.ready_for_confirmation(),
        "core_ready_for_upsell": core_ready_for_upsell,
        "upsell_offer_count": draft.upsell_offer_count,
        "upsell_done": draft.upsell_done,
        "must_offer_second_upsell": must_offer_second_upsell,
        "block_contact_request": must_offer_second_upsell,
        "upsell_locked": bool(draft.upsell_done or upsell_count >= 2),
        "last_offered_dates": list(getattr(draft, "last_offered_dates", []) or []),
        "last_offered_service_type": getattr(draft, "last_offered_service_type", None),
        "last_offered_object_title": getattr(draft, "last_offered_object_title", None),
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
        "rule": "Если next_required_step_before_message не confirmation, нельзя писать что бронь подтверждена или что ссылка на оплату будет отправлена. Сначала ответь на вопрос клиента, затем спроси ровно следующий недостающий пункт. Допы нельзя предлагать до заполнения time, duration, guests_count и event_format. Если must_offer_second_upsell=true, нельзя спрашивать имя/телефон или показывать сводку — нужно только вторично мягко уточнить допы одним цельным LLM-ответом.",
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
