"""Because MCP schemas vary, gates share one path and content contract."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

try:
    # Because hook entry points import the lib package.
    from .payloads import exact_string_dict
except ImportError:
    from payloads import exact_string_dict

_LIST_FIELDS = frozenset({
    "path_keys", "path_list_keys", "path_tokens", "content_keys", "change_keys",
    "operation_keys", "write_operations", "delete_operations",
})
_LIMIT_FIELDS = frozenset({"max_argument_nodes", "max_argument_depth"})
_PATTERN_FIELDS = frozenset({"key_acronym_pattern", "key_camel_pattern", "word_pattern"})


def _load_contract() -> dict | None:
    try:
        value = json.loads(Path(__file__).with_name("mcp_contract.json").read_text(encoding="utf-8"))
        if type(value) is not dict or set(value) != _LIST_FIELDS | _LIMIT_FIELDS | _PATTERN_FIELDS:
            return None
        for key in _LIST_FIELDS:
            if type(value[key]) is not list or not all(type(item) is str for item in value[key]):
                return None
        if any(type(value[key]) is not int or value[key] <= 0 for key in _LIMIT_FIELDS):
            return None
        if any(type(value[key]) is not str or not value[key] for key in _PATTERN_FIELDS):
            return None
        contract = {key: frozenset(value[key]) for key in _LIST_FIELDS}
        contract["operation_keys"] = tuple(value["operation_keys"])
        contract.update({key: value[key] for key in _LIMIT_FIELDS})
        contract.update({key: re.compile(value[key]) for key in _PATTERN_FIELDS})
        contract["changes"] = contract["content_keys"] | contract["change_keys"]
        return contract
    except (OSError, ValueError, TypeError, re.error):
        return None


_CONTRACT = _load_contract()


def _contract() -> dict:
    if _CONTRACT is None:
        raise ValueError("MCP argument contract is missing or invalid")
    return _CONTRACT


def _argument_fields(tool_input: object) -> list[tuple[str, object]]:
    contract = _contract()
    max_nodes = contract["max_argument_nodes"]
    max_depth = contract["max_argument_depth"]
    pending = [(tool_input, 0)]
    fields: list[tuple[str, object]] = []
    visited = 0
    while pending:
        value, depth = pending.pop()
        visited += 1
        if visited > max_nodes or depth > max_depth:
            raise ValueError("MCP arguments exceed the inspection limit")
        if type(value) is dict:
            if len(fields) + len(value) > max_nodes:
                raise ValueError("MCP arguments exceed the inspection limit")
            for key, item in exact_string_dict(value).items():
                fields.append((key, item))
                pending.append((item, depth + 1))
        elif type(value) is list:
            if len(value) > max_nodes:
                raise ValueError("MCP arguments exceed the inspection limit")
            pending.extend((item, depth + 1) for item in value)
    return fields


def _strings(value: object) -> list[str]:
    if type(value) is str:
        return [value] if value else []
    if type(value) is list:
        return [item for item in value if type(item) is str and item]
    return []


def _local_path(value: str) -> str:
    if not value.lower().startswith("file:"):
        return value
    match = re.match(r"^file:(?://([^/]*))?(/[^?#]*)", value, re.IGNORECASE)
    if match is None or (match[1] and match[1].lower() != "localhost"):
        raise ValueError("MCP file URI must name an absolute local path")
    path = match[2]
    if re.search(r"%(?![0-9a-fA-F]{2})", path):
        raise ValueError("MCP file URI has invalid percent encoding")
    return unquote(path, errors="strict")


class McpArguments(NamedTuple):
    paths: list[str]
    contents: list[str]
    has_changes: bool


def _key_tokens(key: str) -> list[str]:
    contract = _contract()
    split = contract["key_acronym_pattern"].sub(r"\1_\2", key)
    split = contract["key_camel_pattern"].sub(r"\1_\2", split)
    return contract["word_pattern"].findall(split.lower())


def mcp_arguments(tool_input: object) -> McpArguments:
    """Because callers need several classifications, inspect arguments only once."""
    contract = _contract()
    paths: list[str] = []
    contents: list[str] = []
    has_changes = False
    for key, value in _argument_fields(tool_input):
        tokens = _key_tokens(key)
        normalized = "_".join(tokens)
        if normalized in contract["changes"]:
            has_changes = True
            if normalized in contract["content_keys"]:
                contents.extend(_strings(value))
            continue
        path_key = normalized in contract["path_keys"] or not contract["path_tokens"].isdisjoint(tokens)
        if path_key and type(value) is str and value:
            paths.append(value)
        elif normalized in contract["path_list_keys"]:
            paths.extend(_strings(value))
    return McpArguments(list(dict.fromkeys(_local_path(path) for path in paths)), contents, has_changes)


def mcp_target_paths(tool_input: object) -> list[str]:
    """Because content can resemble paths, exclude it before checking target tokens."""
    return mcp_arguments(tool_input).paths


def mcp_write_contents(tool_input: object) -> list[str]:
    """Because decoy fields can hide JSON, scan each content candidate alone."""
    return mcp_arguments(tool_input).contents


def mcp_operation(tool_name: str, tool_input: object) -> tuple[str, str]:
    contract = _contract()
    name = "__".join(tool_name.split("__")[2:])
    words = contract["word_pattern"].findall(contract["key_camel_pattern"].sub(r"\1_\2", name).lower())
    named = words[1] if len(words) > 1 and words[0] == "batch" else next(iter(words), "")
    fields = exact_string_dict(tool_input)
    explicit = next((
        fields[key].lower() for key in contract["operation_keys"]
        if type(fields.get(key)) is str and fields[key].strip()
    ), "")
    return named, explicit


def mcp_is_mutation(tool_name: str, tool_input: object) -> bool:
    """Because unknown readers must pass, require an operation or write-shaped arguments."""
    contract = _contract()
    if any(operation in contract["write_operations"] for operation in mcp_operation(tool_name, tool_input)):
        return True
    arguments = mcp_arguments(tool_input)
    return bool(arguments.paths) and arguments.has_changes
