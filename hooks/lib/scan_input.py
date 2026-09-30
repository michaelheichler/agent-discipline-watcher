from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

try:
    from .config import effective_config
    from .findings import Finding
except ImportError:
    from config import effective_config
    from findings import Finding

LEGACY_ENV_NAMES = {
    "ADW_FUNC_BLOCK_LINES": "CLEANCODER_FUNC_BLOCK_LINES",
}
FILE_LENGTH_WARNING = 500
FILE_LENGTH_CRITICAL = 750
FILE_LENGTH_BLOCK = 1000
CONTENT_SAMPLE_BYTES = 8192

# Content is checked too, because text can hide under these.
BINARY_ASSET_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".jpe", ".gif", ".webp", ".avif", ".heic", ".heif",
    ".bmp", ".ico", ".icns", ".tif", ".tiff", ".psd", ".exr",
    ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".m4a", ".m4v", ".mov", ".avi", ".mkv", ".webm",
    ".wav", ".flac", ".ogg", ".opus", ".aac",
    ".zip", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".7z", ".rar", ".tar",
    ".jar", ".war", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".epub",
    ".sqlite", ".sqlite3", ".db", ".parquet", ".arrow", ".npy", ".npz",
    ".bin", ".dat", ".wasm", ".pyc", ".pyo", ".class", ".o", ".a",
    ".so", ".dylib", ".dll", ".exe", ".glb", ".pak",
})
ASSET_TEXT_HEADERS = {
    ".pdf": ("%PDF-",),
    ".gif": ("GIF87a", "GIF89a"),
    ".woff": ("wOFF",),
    ".woff2": ("wOF2",),
    ".otf": ("OTTO",),
    ".psd": ("8BPS",),
    ".flac": ("fLaC",),
    ".ogg": ("OggS",),
    ".opus": ("OggS",),
}


def is_binary_content(path: str | Path, content: bytes | str) -> bool:
    suffix = Path(path).suffix.lower()
    if suffix not in BINARY_ASSET_EXTS:
        return False
    sample = content[:CONTENT_SAMPLE_BYTES]
    if isinstance(sample, bytes):
        if sample.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")):
            return False
        try:
            sample = sample.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.reason != "unexpected end of data":
                return True
            sample = sample[:exc.start].decode("utf-8")
    if sample.startswith("\ufeff"):
        return False
    if sample.startswith(ASSET_TEXT_HEADERS.get(suffix, ())):
        return True
    return any(
        ord(char) < 32 and char not in "\t\n\r\f"
        for char in sample
    )


def file_length_policy(count: int) -> tuple[str, str] | None:
    if count >= FILE_LENGTH_BLOCK:
        return "file_too_long", "Split this file into focused modules."
    if count >= FILE_LENGTH_CRITICAL:
        return "file_length_critical", "Split this file now. It will hard block at 1000 lines."
    if count >= FILE_LENGTH_WARNING:
        return "file_length_warning", "Plan a focused split before this file reaches 750 lines."
    return None


def _count_open_file_lines(handle: BinaryIO) -> tuple[int, bool] | None:
    count = 0
    for line in handle:
        if b"\0" in line:
            return None
        count += 1
        if count >= FILE_LENGTH_BLOCK:
            return count, True
    return count, False


def file_line_count(path: Path) -> tuple[int, bool] | None:
    try:
        with path.open("rb") as handle:
            if is_binary_content(path, handle.read(CONTENT_SAMPLE_BYTES)):
                return None
            handle.seek(0)
            return _count_open_file_lines(handle)
    except OSError:
        return None


def fallback_findings_from_count(path: Path, count: int, capped: bool = True) -> list[dict]:
    policy = file_length_policy(count)
    if policy is not None and policy[0] == "file_too_long":
        rule, action = policy
        shown = f"at least {count}" if capped else str(count)
        detail = f"File has {shown} lines in {path}"
    else:
        rule = "unscannable_file"
        action = "Make the file readable UTF-8 text within the scan byte limit."
        detail = f"File could not be fully scanned: {path}"
    return [Finding(
        family="code",
        rule=rule,
        line=1,
        detail=detail,
        force=True,
        snippet=str(path)[:180],
        action=action,
        path=None,
        severity=None,
        tool_use_id=None,
    ).to_dict()]


def fallback_findings(path: Path) -> list[dict]:
    try:
        with path.open("rb") as handle:
            if is_binary_content(path, handle.read(CONTENT_SAMPLE_BYTES)):
                return []
            handle.seek(0)
            result = _count_open_file_lines(handle)
    except OSError:
        result = None
    if result is None:
        return fallback_findings_from_count(path, 0, capped=False)
    count, capped = result
    return fallback_findings_from_count(path, count, capped)


def read_scannable(path: Path, config: dict) -> str | None:
    cfg = effective_config(config)
    try:
        if path.stat().st_size > _max_scan_bytes(cfg):
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if is_binary_content(path, raw) or b"\0" in raw[:CONTENT_SAMPLE_BYTES]:
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
