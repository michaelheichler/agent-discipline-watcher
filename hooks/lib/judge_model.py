from __future__ import annotations

DEFAULT_JUDGE_MODEL = "claude-haiku-4-5"


def is_haiku(model: object) -> bool:
    """Screen one name because only a haiku agent may reach the claude CLI."""
    if not isinstance(model, str):
        return False
    name = model.strip().lower()
    return name.startswith("claude-") and "haiku" in name


def judge_model(selected: object = None) -> str:
    """Discard a non-haiku selection because a stronger agent must never run."""
    return selected.strip() if is_haiku(selected) else DEFAULT_JUDGE_MODEL
