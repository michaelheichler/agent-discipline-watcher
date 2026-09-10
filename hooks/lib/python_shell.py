from __future__ import annotations

from .shell_syntax import _bare, _payload_command_index, _skip_leading_redirect

NO_VALUE_OPTIONS = frozenset("bBdEhIOPqRsSuvVx")


def isolated_python(segment: list[str] | tuple[str, ...]) -> bool:
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
            return False
        if token == "-":
            return {"I", "S"} <= options
        for option in token[1:]:
            if option == "c":
                return {"I", "S"} <= options
            if option not in NO_VALUE_OPTIONS:
                return False
            options.add(option)
        index += 1
    return {"I", "S"} <= options


def startup_finding(make_finding, rule: str) -> dict:
    return {
        **make_finding(rule),
        "detail": "Python startup can execute project or environment imports before the checked code",
        "action": "For Python reads, use python3 -I -S with the same code. Use Write or Edit for file content.",
    }
