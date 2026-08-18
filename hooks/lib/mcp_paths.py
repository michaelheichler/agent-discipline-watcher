"""A shared extractor lives here because MCP tool_input path keys vary by server, and every write gate would otherwise have to guess independently."""
from __future__ import annotations

try:
    # Relative first because every hook entry script imports this module as lib.mcp_paths, where a bare name cannot resolve.
    from .payloads import exact_string_dict
except ImportError:
    from payloads import exact_string_dict

_PATH_KEYS = ("path", "file_path", "relative_path")
_PATH_LIST_KEY = "paths"


def mcp_target_paths(tool_input: object) -> list[str]:
    """Every recognized key is checked here because MCP servers do not standardize on one path field name for a write target."""
    fields = exact_string_dict(tool_input)
    found: list[str] = []
    for key in _PATH_KEYS:
        value = fields.get(key)
        if isinstance(value, str) and value:
            found.append(value)
    raw_list = fields.get(_PATH_LIST_KEY)
    if isinstance(raw_list, list):
        found.extend(item for item in raw_list if isinstance(item, str) and item)
    return found
