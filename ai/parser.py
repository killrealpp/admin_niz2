from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from app.ai.response_sanitizer import sanitize_reply
from app.core.config import get_settings
from app.data.services import load_services
from app.dialog.availability_cache import availability_context_for_llm, availability_object_dates_for_llm
from app.dialog.state import AdminAction, AdminDecision, BookingDraft

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().with_name("admin_prompt.md")
ROUTER_PROMPT_PATH = Path(__file__).resolve().with_name("router_prompt.md")
KNOWLEDGE_PATH = Path(__file__).resolve().with_name("knowledge.md")


def _load_knowledge() -> str:
    if not KNOWLEDGE_PATH.exists():
        return ""
    return KNOWLEDGE_PATH.read_text(encoding="utf-8")


def decide(text: str, draft: BookingDraft, *, today: str, history: list[dict[str, str]] | None = None) -> AdminDecision:
    settings = get_settings()
    if not settings.deepseek_api_key:
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
        "model": settings.openai_model,
        "temperature": settings.openai_temperature,
        "max_tokens": settings.openai_max_tokens,
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

    return decision


def _decide_data_request(
    text: str,
    draft: BookingDraft,
    *,
    today: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    settings = get_settings()

    payload = {
        "model": settings.openai_model,
        "temperature": 0,
        "max_tokens": 900,
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


def _post_chat_completion(payload: dict[str, Any]) -> str:
    settings = get_settings()
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json=payload,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])


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
        catalog[service_type] = {
            "title": service.get("title"),
            "capacity_max": service.get("capacity_max"),
            "price": service.get("price"),
            "default_duration_minutes": service.get("default_duration_minutes"),
            "variants": variants[:30],
        }
    return catalog


def _compact_media_catalog() -> dict[str, Any]:
    catalog: dict[str, Any] = {}

    for service_type, service in load_services().items():
        service_title = str(service.get("title") or service_type)
        service_media = service.get("media") or service.get("photos") or service.get("images") or []

        if service_media:
            catalog[service_title] = service_media
            catalog[service_type] = service_media

        for variant in service.get("variants") or []:
            title = variant.get("title")
            variant_media = variant.get("media") or variant.get("photos") or variant.get("images") or service_media

            if title and variant_media:
                catalog[str(title)] = variant_media

    return catalog
