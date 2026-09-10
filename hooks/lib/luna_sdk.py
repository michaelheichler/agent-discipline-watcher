from __future__ import annotations

from typing import Any


def enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def item_type(item: object) -> str:
    root = getattr(item, "root", item)
    return str(getattr(root, "type", ""))


def usage_dict(usage: object) -> dict[str, Any]:
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    dumped = getattr(usage, "model_dump", None)
    return dumped(mode="json") if callable(dumped) else {}
