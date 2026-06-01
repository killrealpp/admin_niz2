from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Any

from app.core.config import PROJECT_ROOT

BEST2INFO_DIR = PROJECT_ROOT / "best2info"
BEST2INFO_RUNTIME_PATH = BEST2INFO_DIR / "runtime.md"
KNOWLEDGE_PATH = PROJECT_ROOT / "information.md"
KNOWLEDGE_DIR = PROJECT_ROOT / "app" / "knowledge"
CLIENT_RUNTIME_KNOWLEDGE_PATH = KNOWLEDGE_DIR / "client_runtime.md"
RUNTIME_KNOWLEDGE_PATH = KNOWLEDGE_DIR / "runtime.md"
MAX_KNOWLEDGE_CHARS = 24000
MAX_RETRIEVED_KNOWLEDGE_CHARS = 12000
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class KnowledgeDocument:
    rel_path: str
    content: str
    headings: tuple[str, ...]
    links: tuple[str, ...]


TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "prices/gazebos.md": ("бесед", "цена", "стоим", "почем", "по чем", "прайс", "дешев", "руб"),
    "prices/bathhouse.md": ("бан", "цена", "стоим", "почем", "по чем", "прайс", "час", "руб"),
    "prices/house.md": ("дом", "домик", "гостев", "цена", "стоим", "почем", "по чем", "прайс", "сутки", "руб"),
    "prices/addons.md": ("доп", "кальян", "уголь", "розжиг", "решет", "решот", "шампур", "лед", "лёд", "посуд", "вода", "стоим", "почем"),
    "rules/discounts.md": ("скид", "акци", "со скид", "будн", "понедель", "вторник", "сред", "четверг", "пн", "чт"),
    "rules/payment.md": ("предоплат", "аванс", "оплат", "бронь", "закреп", "возврат", "вернут", "отмен"),
    "rules/location.md": ("адрес", "где", "локац", "парков", "навигатор", "горьк", "ризадеев"),
    "rules/kids-pets.md": ("дет", "ребен", "ребён", "живот", "собак", "кошк", "питом"),
    "rules/rest.md": ("правил", "мангал", "дров", "фейер", "салют", "веник", "веники", "комар", "мошк", "туалет", "украш"),
    "objects/gazebos.md": ("бесед", "вмест", "человек", "гост", "влез", "помест", "свет", "розет", "крыт"),
    "objects/bathhouse.md": ("бан", "бассейн", "пар", "саун"),
    "objects/house.md": ("дом", "домик", "гостев", "ночев", "сутки"),
    "objects/warm_gazebo.md": ("тепл", "тёпл", "бесед", "зимн", "прохлад"),
}


@lru_cache
def load_knowledge() -> str:
    if BEST2INFO_RUNTIME_PATH.exists():
        text = BEST2INFO_RUNTIME_PATH.read_text(encoding="utf-8").strip()
        if len(text) <= MAX_KNOWLEDGE_CHARS:
            return text
        return text[:MAX_KNOWLEDGE_CHARS] + "\n\n[База знаний обрезана для контекста.]"

    if CLIENT_RUNTIME_KNOWLEDGE_PATH.exists():
        text = CLIENT_RUNTIME_KNOWLEDGE_PATH.read_text(encoding="utf-8").strip()
        if len(text) <= MAX_KNOWLEDGE_CHARS:
            return text
        return text[:MAX_KNOWLEDGE_CHARS] + "\n\n[База знаний обрезана для контекста.]"

    if RUNTIME_KNOWLEDGE_PATH.exists():
        text = RUNTIME_KNOWLEDGE_PATH.read_text(encoding="utf-8").strip()
        if len(text) <= MAX_KNOWLEDGE_CHARS:
            return text
        return text[:MAX_KNOWLEDGE_CHARS] + "\n\n[База знаний обрезана для контекста.]"

    chunks: list[str] = []
    has_base = False
    if KNOWLEDGE_DIR.exists():
        priority = {
            "prices.md": 0,
            "objects.md": 1,
            "yclients_ids.md": 2,
            "company_knowledge.md": 3,
            "base.md": 4,
        }
        paths = sorted(KNOWLEDGE_DIR.glob("*.md"), key=lambda path: (priority.get(path.name, 10), path.name))
        for path in paths:
            if path.name == "base.md":
                has_base = True
            chunks.append(f"# {path.name}\n\n{path.read_text(encoding='utf-8').strip()}")

    if KNOWLEDGE_PATH.exists() and not has_base:
        chunks.append(KNOWLEDGE_PATH.read_text(encoding="utf-8").strip())
    elif not chunks:
        chunks.append("База знаний пока не заполнена.")

    text = "\n\n".join(chunk for chunk in chunks if chunk)
    if len(text) <= MAX_KNOWLEDGE_CHARS:
        return text
    return text[:MAX_KNOWLEDGE_CHARS] + "\n\n[База знаний обрезана для контекста.]"


@lru_cache
def _load_best2info_documents() -> tuple[KnowledgeDocument, ...]:
    if not BEST2INFO_DIR.exists():
        return ()
    paths = sorted(
        path
        for path in BEST2INFO_DIR.rglob("*.md")
        if path.is_file() and path.name != "runtime.md"
    )
    documents: list[KnowledgeDocument] = []
    for path in paths:
        rel_path = path.relative_to(BEST2INFO_DIR).as_posix()
        text = path.read_text(encoding="utf-8").strip()
        if text:
            documents.append(
                KnowledgeDocument(
                    rel_path=rel_path,
                    content=text,
                    headings=tuple(match.strip() for match in HEADING_RE.findall(text)),
                    links=_wikilinks_for_document(text),
                )
            )
    return tuple(documents)


def retrieve_client_knowledge(
    text: str,
    form_data: dict[str, Any] | None = None,
    *,
    limit: int = 5,
    max_chars: int = MAX_RETRIEVED_KNOWLEDGE_CHARS,
) -> str:
    """Return compact client knowledge for one info question.

    `best2info` is the client-facing source of truth. Legacy `app/knowledge`
    stays as a fallback while the wiki is being filled.
    """
    runtime = load_knowledge()
    documents = _load_best2info_documents()
    if not documents:
        return runtime

    query = _normalize_text(" ".join(str(part or "") for part in (text, _form_context_text(form_data or {}))))
    query_tokens = _tokens(query)
    by_path = {document.rel_path: document for document in documents}
    scored: list[tuple[int, KnowledgeDocument]] = []
    for document in documents:
        score = _knowledge_score(document, query, query_tokens)
        if score > 0:
            scored.append((score, document))

    if not scored:
        scored = [
            (1, document)
            for document in documents
            if document.rel_path in {"index.md", "rules/payment.md", "rules/location.md"}
        ]
    scored.sort(key=lambda item: (-item[0], item[1].rel_path))

    chunks = [f"# runtime.md\n\n{runtime}"]
    selected_paths = _selected_graph_paths(scored[:limit], by_path, limit=limit)
    for rel_path in selected_paths:
        document = by_path.get(rel_path)
        if document:
            chunks.append(f"# {rel_path}\n\n{document.content}")

    result = "\n\n".join(chunks)
    if len(result) <= max_chars:
        return result
    return result[:max_chars] + "\n\n[Клиентская база знаний обрезана для контекста.]"


def _selected_graph_paths(
    scored: list[tuple[int, KnowledgeDocument]],
    by_path: dict[str, KnowledgeDocument],
    *,
    limit: int,
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()

    def add(rel_path: str) -> None:
        if rel_path in by_path and rel_path not in seen:
            selected.append(rel_path)
            seen.add(rel_path)

    for _score, document in scored:
        add(document.rel_path)

    seeds = list(selected)
    for rel_path in seeds:
        document = by_path.get(rel_path)
        if not document:
            continue
        if document.rel_path != "index.md":
            for linked_path in document.links:
                add(linked_path)
        for candidate in by_path.values():
            if rel_path in candidate.links:
                add(candidate.rel_path)

    return selected[: max(limit * 2, limit)]


def _knowledge_score(document: KnowledgeDocument, query: str, query_tokens: set[str]) -> int:
    haystack = _normalize_text(f"{document.rel_path} {' '.join(document.headings)} {document.content}")
    score = 0
    for token in query_tokens:
        if len(token) >= 3 and token in haystack:
            score += 2
    for heading in document.headings:
        normalized_heading = _normalize_text(heading)
        if normalized_heading and normalized_heading in query:
            score += 4
    for keyword in TOPIC_KEYWORDS.get(document.rel_path, ()):
        if _normalize_text(keyword) in query:
            score += 8
    if document.rel_path == "index.md" and score > 0:
        return 1
    return score


def _normalize_text(value: str) -> str:
    return value.lower().replace("ё", "е")


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zа-я0-9]+", value.lower().replace("ё", "е"))
        if len(token) >= 3
    }


def _wikilinks_for_document(content: str) -> tuple[str, ...]:
    links: list[str] = []
    for raw_target in WIKILINK_RE.findall(content):
        rel_path = _normalize_wikilink_target(raw_target)
        if rel_path and rel_path not in links:
            links.append(rel_path)
    return tuple(links)


def _normalize_wikilink_target(raw_target: str) -> str:
    target = raw_target.strip().replace("\\", "/")
    if not target:
        return ""
    if not target.endswith(".md"):
        target = f"{target}.md"
    return target.lstrip("/")


def _form_context_text(form_data: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("service_type", "service_variant", "date", "guests_count", "event_format"):
        value = form_data.get(key)
        if value:
            parts.append(str(value))
    return " ".join(parts)
