from __future__ import annotations

from typing import NamedTuple

from .shell_syntax import _bare, _payload_command_index, _skip_leading_redirect

NO_VALUE_OPTIONS = frozenset("bBdEhIOPqRsSuvVx")


class PythonStartup(NamedTuple):
    isolated: bool
    unsupported_inline: bool = False


def python_startup(segment: list[str] | tuple[str, ...]) -> PythonStartup:
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
            return PythonStartup(False)
        if token == "-":
            return PythonStartup({"I", "S"} <= options)
        for offset, option in enumerate(token[1:], 1):
            if option == "c":
                supported = offset == len(token) - 1 or token.startswith("-c")
                return PythonStartup(supported and {"I", "S"} <= options, not supported)
            if option not in NO_VALUE_OPTIONS:
                return PythonStartup(False)
            options.add(option)
        index += 1
    return PythonStartup({"I", "S"} <= options)


def isolated_python(segment: list[str] | tuple[str, ...]) -> bool:
    return python_startup(segment).isolated


def startup_finding(make_finding, rule: str) -> dict:
    return {
        **make_finding(rule),
        "detail": "Python startup can execute project or environment imports before the checked code",
        "action": "For Python reads, use python3 -I -S with the same code. Use Write or Edit for file content.",
    }
