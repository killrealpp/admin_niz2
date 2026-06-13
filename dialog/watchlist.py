from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.data.services import normalize_service_type
from app.dialog.state import BookingDraft
from app.dialog.availability import check_availability
from app.storage import sqlite

logger = logging.getLogger(__name__)


@dataclass
class WatchlistCandidate:
    service_type: str | None
    object_title: str
    date: str


def candidate_from_action(params: dict[str, Any] | None, draft: BookingDraft | None = None) -> WatchlistCandidate | None:
    params = params or {}
    date = str(params.get("date") or params.get("date_from") or (draft.date if draft else "") or "").strip()
    object_title = str(params.get("object_title") or params.get("title") or "").strip()
    service_type = normalize_service_type(str(params.get("service_type") or (draft.service_type if draft else "") or ""))

    if not object_title:
        if service_type == "bathhouse":
            object_title = "Баня с бассейном"
        elif service_type == "house":
            object_title = "Гостевой дом"
        elif service_type == "warm_gazebo":
            object_title = "Теплая беседка"
        elif draft and draft.service_variant:
            object_title = draft.service_variant

    if not date or not object_title:
        return None
    return WatchlistCandidate(service_type=service_type, object_title=object_title, date=date)


def create_watchlist(chat_id: str, candidate: WatchlistCandidate) -> int:
    watch_id = sqlite.create_watchlist(
        chat_id,
        service_type=candidate.service_type,
        object_title=candidate.object_title,
        date=candidate.date,
    )
    logger.info(
        "WATCHLIST_CREATED id=%s chat_id=%s service_type=%s object_title=%s date=%s",
        watch_id,
        chat_id,
        candidate.service_type,
        candidate.object_title,
        candidate.date,
    )
    return watch_id


def object_is_free(candidate: WatchlistCandidate) -> bool:
    draft = BookingDraft(service_type=candidate.service_type, date=candidate.date)
    if candidate.object_title.startswith("Беседка") or candidate.object_title.startswith("Крытая"):
        draft.service_type = "gazebo"
        draft.service_variant = candidate.object_title
    elif "бан" in candidate.object_title.lower():
        draft.service_type = "bathhouse"
        draft.duration = 7
    elif "дом" in candidate.object_title.lower():
        draft.service_type = "house"
        draft.duration = 7
    elif "теп" in candidate.object_title.lower():
        draft.service_type = "warm_gazebo"
    try:
        availability = check_availability(draft)
        return bool(availability.ok)
    except Exception:
        logger.exception("WATCHLIST_CHECK_FAILED candidate=%s", candidate)
        return False


def check_active_watchlist() -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for row in sqlite.list_active_watchlist(limit=50):
        candidate = WatchlistCandidate(
            service_type=row.get("service_type"),
            object_title=str(row.get("object_title") or ""),
            date=str(row.get("date") or ""),
        )
        logger.info(
            "WATCHLIST_CHECK id=%s chat_id=%s object_title=%s date=%s",
            row.get("id"),
            row.get("chat_id"),
            candidate.object_title,
            candidate.date,
        )
        if object_is_free(candidate):
            sqlite.mark_watchlist_notified(int(row["id"]))
            events.append(
                {
                    "chat_id": str(row["chat_id"]),
                    "message": f"Хорошая новость: {candidate.object_title} на {candidate.date} освободилась. Хотите забронировать?",
                }
            )
            logger.info("WATCHLIST_NOTIFIED id=%s", row.get("id"))
    return events
