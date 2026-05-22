from functools import lru_cache

from app.core.config import PROJECT_ROOT

KNOWLEDGE_PATH = PROJECT_ROOT / "information.md"
KNOWLEDGE_DIR = PROJECT_ROOT / "app" / "knowledge"
CLIENT_RUNTIME_KNOWLEDGE_PATH = KNOWLEDGE_DIR / "client_runtime.md"
RUNTIME_KNOWLEDGE_PATH = KNOWLEDGE_DIR / "runtime.md"
MAX_KNOWLEDGE_CHARS = 24000


@lru_cache
def load_knowledge() -> str:
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
