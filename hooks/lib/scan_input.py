"""Source loading and numeric limits for scanner entry points."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from .config import effective_config
except ImportError:
    from config import effective_config

LEGACY_ENV_NAMES = {
    "ADW_FILE_BLOCK_LINES": "CLEANCODER_FILE_BLOCK_LINES",
    "ADW_FUNC_BLOCK_LINES": "CLEANCODER_FUNC_BLOCK_LINES",
}


def read_scannable(path: Path, config: dict) -> str | None:
    cfg = effective_config(config)
    try:
        if path.stat().st_size > _max_scan_bytes(cfg):
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="replace")


def scannable_text(text: str, config: dict) -> str | None:
    if len(text) > _max_scan_bytes(effective_config(config)):
        return None
    if "\0" in text[:8192]:
        return None
    return text


def _max_scan_bytes(config: dict) -> int:
    return int_setting(config, "max_scan_bytes", "ADW_MAX_SCAN_BYTES", 1_000_000)


def _env_setting(env_name: str, default: int) -> object:
    for name in (env_name, LEGACY_ENV_NAMES.get(env_name)):
        if name and name in os.environ:
            return os.environ[name]
    return default


def int_setting(config: dict, key: str, env_name: str, default: int) -> int:
    raw = config.get(key, _env_setting(env_name, default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
