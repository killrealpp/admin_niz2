from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.services.media_service import is_explicit_photo_request, media_for_client_message


@dataclass(frozen=True)
class ExplicitPhotoCallbacks:
    service_variant_patch: Callable[..., dict[str, Any]]
    service_type_patch: Callable[[str], dict[str, Any]]
    normalize_service_aliases: Callable[[dict[str, Any]], dict[str, Any]]
    load_services_map: Callable[[], dict[str, Any]]
    suitable_available_gazebo_titles: Callable[[dict[str, Any]], list[str]]
    available_gazebo_titles: Callable[[dict[str, Any]], list[str]]


def explicit_photo_reply(
    text: str,
    form_data: dict[str, Any],
    callbacks: ExplicitPhotoCallbacks,
) -> str | None:
    if not is_explicit_photo_request(text):
        return None
    variant_patch = callbacks.service_variant_patch(text, allow_bare_ordinal=True)
    if variant_patch.get("service_variant"):
        title = variant_patch["service_variant"]
        reply = f"Конечно, сейчас отправлю фото: {title} 📸"
        if media_for_client_message(text, reply):
            return reply
        return f"Фото для {title} пока не добавлено в базу."
    if "бесед" in text.lower().replace("ё", "е"):
        titles = callbacks.suitable_available_gazebo_titles(form_data) or callbacks.available_gazebo_titles(form_data)
        if not titles:
            titles = [
                "Беседка №1",
                "Беседка №2",
                "Беседка №3",
                "Беседка №4",
                "Беседка №5",
                "Беседка №6",
                "Беседка №8",
                "Крытая беседка",
            ]
        names = ", ".join(titles[:8])
        reply = f"Конечно, сейчас отправлю фото беседок: {names} 📸"
        if media_for_client_message(text, reply):
            return reply
    service_patch = callbacks.service_type_patch(text)
    service_type = service_patch.get("service_type")
    if service_type:
        normalized_service = callbacks.normalize_service_aliases({"service_type": service_type}).get("service_type")
        service_title = None
        if normalized_service in {"bathhouse", "house", "warm_gazebo"}:
            service_title = (callbacks.load_services_map().get(normalized_service) or {}).get("title")
        if service_title:
            reply = f"Конечно, сейчас отправлю фото: {service_title} 📸"
            if media_for_client_message(text, reply):
                return reply
            return f"Фото для {service_title} пока не добавлено в базу."
        if normalized_service == "gazebo":
            titles = callbacks.suitable_available_gazebo_titles(form_data) or callbacks.available_gazebo_titles(form_data)
            if not titles:
                titles = [
                    "Беседка №1",
                    "Беседка №2",
                    "Беседка №3",
                    "Беседка №4",
                    "Беседка №5",
                    "Беседка №6",
                    "Беседка №8",
                    "Крытая беседка",
                ]
            names = ", ".join(titles[:8])
            reply = f"Конечно, сейчас отправлю фото беседок: {names} 📸"
            if media_for_client_message(text, reply):
                return reply
    title = form_data.get("service_variant")
    if title:
        reply = f"Конечно, сейчас отправлю фото: {title} 📸"
        if media_for_client_message(text, reply):
            return reply
        return f"Фото для {title} пока не добавлено в базу."

    available_titles = callbacks.suitable_available_gazebo_titles(form_data) or callbacks.available_gazebo_titles(form_data)
    if available_titles:
        names = ", ".join(available_titles[:8])
        reply = f"Конечно, сейчас отправлю фото вариантов: {names} 📸"
        if media_for_client_message(text, reply):
            return reply

    if "бесед" in text.lower().replace("ё", "е") or form_data.get("service_type") == "gazebo":
        return (
            "Конечно, покажу фото. Напишите номер беседки, например «фото беседки №2», "
            "или выберите дату и количество гостей — отправлю подходящие варианты."
        )
    return None
