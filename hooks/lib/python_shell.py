from __future__ import annotations

import os
import re

from .python_imports import imports_are_trusted
from .shell_syntax import (
    DYNAMIC_RE, _assignment_word, _bare, _is_quoted, _payload_command_index, _skip_leading_redirect,
)

NO_VALUE_OPTIONS = frozenset("bBdEhIOPqRsSuvVx")
STARTUP_FLAGS: dict[str, frozenset[str]] = {
    "command": frozenset(),
    "env": frozenset({"-i", "--ignore-environment"}),
    "nice": frozenset(),
    "time": frozenset({"-p"}),
    "timeout": frozenset({"--foreground", "--preserve-status", "-v", "--verbose"}),
}
STARTUP_VALUE_FLAGS: dict[str, frozenset[str]] = {
    "env": frozenset({"-u", "--unset"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
}
STARTUP_VARIABLE_RE = re.compile(r"(?:PYTHON|LD_|DYLD_|PYENV|CONDA|__PYVENV)|(?:HOME|PATH|VIRTUAL_ENV|USERPROFILE|APPDATA)$")
DURATION_RE = re.compile(r"\d+(?:\.\d+)?[smhd]?")
NICE_LEVEL_RE = re.compile(r"-\d+")


def isolated_python(segment: list[str] | tuple[str, ...]) -> bool:
    """Because -I -S cannot stop a preload library or a swapped interpreter path, the prefix counts too."""
    options = _python_options(segment)
    if options is None or not {"I", "S"} <= options:
        return False
    prefix = list(segment[:_payload_command_index(list(segment))])
    assignments = (_assignment_word(token) for token in prefix)
    return all(_harmless_assignment(word) for word in assignments if word is not None)


def _harmless_assignment(word: str) -> bool:
    name, _, _ = word.partition("=")
    return not STARTUP_VARIABLE_RE.match(name) and not DYNAMIC_RE.search(word)


def trusted_python_startup(segment: list[str] | tuple[str, ...], cwd: str | None = None) -> bool:
    options = _python_options(segment)
    if options is None:
        return False
    if isolated_python(segment):
        return True
    prefix = list(segment[:_payload_command_index(list(segment))])
    if not _plain_startup_prefix(prefix) or os.environ.get("PYTHONINSPECT"):
        return False
    return imports_are_trusted(cwd)


def _plain_startup_prefix(prefix: list[str]) -> bool:
    """Because a prefix word can change which Python starts or what it imports, only known harmless words pass."""
    wrapper, index = "", 0
    while index < len(prefix):
        token = prefix[index]
        step = None if _is_quoted(token) or DYNAMIC_RE.search(token) else _startup_step(wrapper, token)
        if step is None:
            return False
        wrapper, width = step
        index += width
    return True


def _startup_step(wrapper: str, token: str) -> tuple[str, int] | None:
    if wrapper and token.startswith("-"):
        return _startup_option(wrapper, token)
    if wrapper == "timeout":
        return ("", 1) if DURATION_RE.fullmatch(token) else None
    assignment = _assignment_word(token)
    if assignment is not None:
        return (wrapper, 1) if _harmless_assignment(assignment) else None
    return (token, 1) if token in STARTUP_FLAGS else None


def _startup_option(wrapper: str, token: str) -> tuple[str, int] | None:
    flag, separator, _ = token.partition("=")
    value_flags = STARTUP_VALUE_FLAGS.get(wrapper, frozenset())
    if token in STARTUP_FLAGS[wrapper] or (wrapper == "nice" and NICE_LEVEL_RE.fullmatch(token)):
        return wrapper, 1
    if flag in value_flags:
        return wrapper, 1 if separator else 2
    if not token.startswith("--") and token[:2] in value_flags:
        return wrapper, 1
    return None


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


def rejection_finding(make_finding, rule: str, rejection: str, startup_trusted: bool) -> dict:
    startup = "" if startup_trusted else " Run Python reads as python3 -I -S."
    finding = make_finding(rule)
    return {
        **finding,
        "detail": f"Python payload is not provably read-only. The checker rejected {rejection}",
        "action": f"The checker rejected {rejection}. {finding['action']}{startup}",
    }


def startup_finding(make_finding, rule: str) -> dict:
    finding = make_finding(rule)
    return {
        **finding,
        "detail": "Python startup can execute project or environment imports before the checked code",
        "action": f"For Python reads, use python3 -I -S with the same code. {finding['action']}",
    }
