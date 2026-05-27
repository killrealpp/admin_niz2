from __future__ import annotations


def asks_for_free_slots(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if any(word in normalized for word in ("свобод", "слот", "во сколько")):
        return True
    if "что есть" in normalized or "что у вас есть" in normalized:
        return True
    if any(marker in normalized for marker in ("не подходит", "не подойд", "не удобно", "неудобно", "еще варианты", "ещё варианты", "дальше", "другую дату", "другая дата")):
        return True
    return any(
        marker in normalized
        for marker in (
            "когда можно",
            "на когда можно",
            "на когд",
            "когдя",
            "когда есть",
            "когда получится",
            "какие даты",
            "ближайшие даты",
        )
    )


def asks_nearest_free_dates(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    if not asks_for_free_slots(text):
        return False
    return any(
        marker in normalized
        for marker in (
            "ближай",
            "какие даты",
            "свободные даты",
            "когда свобод",
            "когда можно",
            "когда есть",
            "когда получится",
            "на когда можно",
            "на когд",
            "когдя",
        )
    )
