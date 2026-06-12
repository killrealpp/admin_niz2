from __future__ import annotations

from pathlib import Path

IMAGES_DIR = Path(__file__).resolve().parents[1] / "images"

GAZEBO_IMAGE_BY_VARIANT = {
    "Беседка №1": IMAGES_DIR / "besedka1.jpg",
    "Беседка №2": IMAGES_DIR / "besedka2.jpg",
    "Беседка №3": IMAGES_DIR / "besedka3.jpg",
    "Беседка №4": IMAGES_DIR / "besedka4.jpg",
    "Беседка №5": IMAGES_DIR / "besedka5.jpg",
    "Беседка №6": IMAGES_DIR / "besedka6.jpg",
    "Беседка №8": IMAGES_DIR / "besedka8.jpg",
    "Крытая беседка": IMAGES_DIR / "besedka_krytaya.jpg",
    "Тёплая беседка": IMAGES_DIR / "besedka_teplaya.jpg",
    "Теплая беседка": IMAGES_DIR / "besedka_teplaya.jpg",
}

SERVICE_IMAGE_BY_TYPE = {
    "bathhouse": IMAGES_DIR / "banya.jpg",
    "house": IMAGES_DIR / "dom_gostevoy.jpg",
    "warm_gazebo": IMAGES_DIR / "besedka_teplaya.jpg",
    "баня": IMAGES_DIR / "banya.jpg",
    "дом": IMAGES_DIR / "dom_gostevoy.jpg",
    "гостевой дом": IMAGES_DIR / "dom_gostevoy.jpg",
    "тёплая беседка": IMAGES_DIR / "besedka_teplaya.jpg",
    "теплая беседка": IMAGES_DIR / "besedka_teplaya.jpg",
}


def paths_for_requested_media(requested_media: list[str]) -> list[Path]:
    """Возвращает фото только по явному requested_media от LLM.

    Здесь нет анализа текста клиента/ответа по ключевым словам: модель сама решает,
    какие фото нужны, а код только мапит стабильные названия на файлы.
    """
    paths: list[Path] = []

    for item in requested_media or []:
        key = str(item).strip()
        if not key:
            continue

        path = GAZEBO_IMAGE_BY_VARIANT.get(key)
        if path:
            paths.append(path)
            continue

        service_path = SERVICE_IMAGE_BY_TYPE.get(key)
        if service_path:
            paths.append(service_path)
            continue

        normalized = key.lower().replace("ё", "е")
        service_path = SERVICE_IMAGE_BY_TYPE.get(normalized)
        if service_path:
            paths.append(service_path)

    return _existing(paths)


def _existing(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path.exists() and path not in seen:
            result.append(path)
            seen.add(path)
    return result
