"""Lint the client-facing best2info wiki against links and service prices."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
INFO_DIR = ROOT / "best2info"
SERVICES_MAP_PATH = ROOT / "config" / "services_map.yaml"

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
MONEY_RE = re.compile(r"(\d[\d\s]*)(?:₽|руб)")


def main() -> None:
    errors: list[str] = []
    warnings: list[str] = []
    files = _markdown_files()
    rel_paths = {path.relative_to(INFO_DIR).as_posix(): path for path in files}
    incoming = {rel_path: 0 for rel_path in rel_paths}

    for rel_path, path in rel_paths.items():
        content = path.read_text(encoding="utf-8")
        for raw_target in WIKILINK_RE.findall(content):
            target = _resolve_wikilink(path, raw_target, rel_paths)
            if target is None:
                errors.append(f"broken wikilink: {rel_path} -> [[{raw_target}]]")
            else:
                incoming[target] += 1

    for rel_path, count in sorted(incoming.items()):
        if rel_path != "index.md" and count == 0:
            errors.append(f"orphan page: {rel_path}")

    services = _load_services_map()
    _check_gazebo_prices(services, errors)
    _check_fixed_service_prices("bathhouse", "prices/bathhouse.md", services, errors)
    _check_fixed_service_prices("house", "prices/house.md", services, errors)
    _check_single_price("warm_gazebo", "objects/warm_gazebo.md", services, errors)
    warnings.extend(_unknown_price_notes(rel_paths))

    if errors:
        print("FAIL best2info lint")
        for error in errors:
            print(f"- {error}")
        if warnings:
            print("\nNotes:")
            for warning in warnings:
                print(f"- {warning}")
        raise SystemExit(1)

    print(
        f"OK best2info lint: files={len(files)}, links_checked={sum(incoming.values())}, price_checks=ok"
    )
    for warning in warnings:
        print(f"NOTE: {warning}")


def _markdown_files() -> list[Path]:
    return sorted(
        path
        for path in INFO_DIR.rglob("*.md")
        if path.is_file() and ".obsidian" not in path.parts
    )


def _resolve_wikilink(source: Path, raw_target: str, rel_paths: dict[str, Path]) -> str | None:
    target = raw_target.strip().replace("\\", "/")
    if not target:
        return None
    if not target.endswith(".md"):
        target = f"{target}.md"
    candidates = [target.lstrip("/")]
    if "/" not in target:
        candidates.append((source.parent / target).relative_to(INFO_DIR).as_posix())
        matches = [rel_path for rel_path in rel_paths if Path(rel_path).name == target]
        candidates.extend(matches)
    for candidate in candidates:
        if candidate in rel_paths:
            return candidate
    return None


def _load_services_map() -> dict[str, Any]:
    return yaml.safe_load(SERVICES_MAP_PATH.read_text(encoding="utf-8")) or {}


def _money(value: str) -> int | None:
    match = MONEY_RE.search(value)
    if not match:
        return None
    return int(re.sub(r"\s+", "", match.group(1)))


def _table_rows(rel_path: str) -> dict[str, list[int]]:
    path = INFO_DIR / rel_path
    rows: dict[str, list[int]] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0].lower() in {"беседка", "длительность", "вариант"}:
            continue
        prices = [price for price in (_money(cell) for cell in cells[1:]) if price is not None]
        if prices:
            rows[cells[0]] = prices
    return rows


def _check_gazebo_prices(services: dict[str, Any], errors: list[str]) -> None:
    variants = services.get("gazebo", {}).get("variants") or []
    for rel_path in ("prices/gazebos.md", "rules/discounts.md"):
        rows = _table_rows(rel_path)
        for variant in variants:
            title = str(variant.get("title") or "")
            price = int(variant.get("price") or 0)
            if not title or not price:
                continue
            row = rows.get(title)
            if not row:
                errors.append(f"{rel_path}: missing gazebo price row for {title}")
                continue
            base = row[0]
            discount = row[1] if len(row) > 1 else None
            expected_discount = int(price * 0.5)
            if base != price:
                errors.append(f"{rel_path}: {title} base price {base} != services_map {price}")
            if discount != expected_discount:
                errors.append(
                    f"{rel_path}: {title} discount price {discount} != 50% of {price} ({expected_discount})"
                )


def _check_fixed_service_prices(
    service_type: str,
    rel_path: str,
    services: dict[str, Any],
    errors: list[str],
) -> None:
    rows = _table_rows(rel_path)
    expected: dict[tuple[int, str], int] = {}
    for variant in services.get(service_type, {}).get("variants") or []:
        duration = int(variant.get("duration_minutes") or 0)
        weekdays = set(variant.get("weekdays") or [])
        if not duration:
            continue
        if weekdays == {0, 1, 2, 3}:
            expected[(duration, "weekday")] = int(variant.get("price") or 0)
        elif weekdays == {4, 5, 6}:
            expected[(duration, "weekend")] = int(variant.get("price") or 0)
    for duration, label in sorted({(key[0], key[1]) for key in expected}):
        row_key = "Сутки" if duration == 1440 else f"{duration // 60} часа"
        row = rows.get(row_key) or rows.get(f"{duration // 60} часов")
        if not row or len(row) < 2:
            errors.append(f"{rel_path}: missing row for {row_key}")
            continue
        actual = row[0] if label == "weekday" else row[1]
        wanted = expected[(duration, label)]
        if actual != wanted:
            errors.append(f"{rel_path}: {duration // 60}h {label} price {actual} != services_map {wanted}")


def _check_single_price(
    service_type: str,
    rel_path: str,
    services: dict[str, Any],
    errors: list[str],
) -> None:
    expected = services.get(service_type, {}).get("price")
    if not expected:
        return
    path = INFO_DIR / rel_path
    if not path.exists():
        errors.append(f"{rel_path}: missing page for {service_type}")
        return
    prices = [_money(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if int(expected) not in {price for price in prices if price is not None}:
        errors.append(f"{rel_path}: price for {service_type} does not match services_map {expected}")


def _unknown_price_notes(rel_paths: dict[str, Path]) -> list[str]:
    notes: list[str] = []
    for rel_path, path in sorted(rel_paths.items()):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            normalized = line.lower().replace("ё", "е")
            if "точн" in normalized and "цен" in normalized and ("нет" in normalized or "не " in normalized):
                notes.append(f"{rel_path}:{line_no}: fact without exact price must be answered as уточним по факту")
    return notes


if __name__ == "__main__":
    main()
