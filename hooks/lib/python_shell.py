from __future__ import annotations

import os

from .python_imports import imports_are_trusted
from .shell_syntax import _bare, _payload_command_index, _skip_leading_redirect

NO_VALUE_OPTIONS = frozenset("bBdEhIOPqRsSuvVx")


def isolated_python(segment: list[str] | tuple[str, ...]) -> bool:
    options = _python_options(segment)
    return options is not None and {"I", "S"} <= options


def trusted_python_startup(segment: list[str] | tuple[str, ...], cwd: str | None = None) -> bool:
    options = _python_options(segment)
    if options is None:
        return False
    if {"I", "S"} <= options:
        return True
    prefix = list(segment[:_payload_command_index(list(segment))])
    if prefix not in ([], ["command"], ["env"]) or os.environ.get("PYTHONINSPECT"):
        return False
    return imports_are_trusted(cwd)


def _python_options(segment: list[str] | tuple[str, ...]) -> set[str] | None:
    tokens = list(segment)
    index = _payload_command_index(tokens) + 1
    options: set[str] = set()
    while index < len(tokens):
        after_redirect = _skip_leading_redirect(tokens, index)
        if after_redirect is not None:
            index = after_redirect
            continue
        token = _bare(tokens[index])
        if not token.startswith("-") or token.startswith("--"):
            return None
        if token == "-":
            return options
        for option in token[1:]:
            if option == "c":
                return options
            if option not in NO_VALUE_OPTIONS:
                return None
            options.add(option)
        index += 1
    return options


def startup_finding(make_finding, rule: str) -> dict:
    return {
        **make_finding(rule),
        "detail": "Python startup can execute project or environment imports before the checked code",
        "action": "For Python reads, use python3 -I -S with the same code. Use Write or Edit for file content.",
    }
