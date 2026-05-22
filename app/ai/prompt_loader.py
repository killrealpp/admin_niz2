from functools import lru_cache

from app.core.config import PROJECT_ROOT

PROMPTS_DIR = PROJECT_ROOT / "app" / "prompts"


@lru_cache
def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8").strip()
