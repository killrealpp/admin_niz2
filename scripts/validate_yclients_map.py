"""Validate local YCLIENTS service/staff IDs against the live booking API."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.integrations.yclients_client import YClientsClient  # noqa: E402
from app.services.availability_service import load_services_map  # noqa: E402


ALIAS_SERVICE_TYPES = {"summer_gazebo", "gazebo_bathhouse"}


def _configured_items() -> list[tuple[str, dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any]]] = []
    for service_type, config in load_services_map().items():
        variants = list(config.get("variants") or [])
        if variants:
            items.extend((service_type, variant) for variant in variants)
        elif config.get("yclients_service_id") or config.get("yclients_staff_id"):
            items.append((service_type, config))
    return items


def main() -> None:
    client = YClientsClient()
    live_services = {str(item.get("id")): item for item in client.get_book_services()}
    configured = _configured_items()
    configured_service_ids = {
        str(item.get("yclients_service_id"))
        for _, item in configured
        if item.get("yclients_service_id")
    }

    errors: list[str] = []
    checked = 0
    for service_type, item in configured:
        service_id = str(item.get("yclients_service_id") or "")
        staff_id = str(item.get("yclients_staff_id") or "")
        title = item.get("title") or service_type
        if not service_id:
            continue
        checked += 1
        if service_id not in live_services:
            errors.append(f"{service_type}/{title}: service_id {service_id} not found in YCLIENTS book_services")
            continue
        allowed_staff = {str(staff.get("id")) for staff in client.get_book_staff(service_id)}
        if staff_id and staff_id not in allowed_staff:
            errors.append(
                f"{service_type}/{title}: staff_id {staff_id} is not available for service_id {service_id}"
            )

    unmapped = [
        f"{sid}:{item.get('title')}"
        for sid, item in live_services.items()
        if sid not in configured_service_ids
    ]
    aliases = [
        service_type
        for service_type, config in load_services_map().items()
        if service_type in ALIAS_SERVICE_TYPES and not config.get("yclients_service_id")
    ]

    print(f"checked_configured_pairs={checked}")
    print(f"live_book_services={len(live_services)}")
    print(f"unmapped_live_services={unmapped or 'none'}")
    print(f"aliases_without_direct_service={aliases or 'none'}")
    if errors:
        print("errors:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("OK: services_map.yaml matches live YCLIENTS service/staff pairs")


if __name__ == "__main__":
    main()
