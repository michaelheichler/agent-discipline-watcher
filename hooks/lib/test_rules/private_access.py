"""Match private access, because a test should use the public seam."""
from __future__ import annotations

import ast
import copy
import io
import re
import tokenize

try:
    from . import Hit, Rule, RuleSet, module_scopes, module_tree
except ImportError:
    from lib.test_rules import Hit, Rule, RuleSet, module_scopes, module_tree

METHODS_RULE = Rule(
    "exposing_private_methods_for_testing",
    "Calls a private method or patches a private name directly",
    "Call the public method that exercises this path instead.",
)
STATE_RULE = Rule(
    "exposing_private_state_for_testing",
    "Reads or writes a private attribute directly",
    "Assert on the public result the call already returns.",
)

# Skip these, because a namedtuple exposes them on purpose.
_NAMEDTUPLE_NAMES = frozenset({"_replace", "_asdict", "_make", "_fields", "_field_defaults"})

_PRIVATE_CALL = re.compile(
    r"\b(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>_[A-Za-z][A-Za-z0-9_]*)\s*\("
)
_PRIVATE_ATTR = re.compile(
    r"\b(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>_[A-Za-z][A-Za-z0-9_]*)\b(?!\s*\()"
)
_PRIVATE_NAME = re.compile(r"_[A-Za-z][A-Za-z0-9_]*$")
_LITERAL_TOKENS = frozenset({tokenize.STRING, tokenize.COMMENT, *(
    getattr(tokenize, name, -1) for name in (
        "FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END",
        "TSTRING_START", "TSTRING_MIDDLE", "TSTRING_END",
    )
)})


def _masked(body: str) -> str:
    """Blank string literals, because a dotted config key is not an attribute."""
    lines = body.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    out = list(body)
    try:
        for token in tokenize.generate_tokens(io.StringIO(body).readline):
            if token.type not in _LITERAL_TOKENS:
                continue
            start = offsets[token.start[0] - 1] + token.start[1]
            end = offsets[token.end[0] - 1] + token.end[1]
            out[start:end] = ["\n" if char == "\n" else " " for char in body[start:end]]
    except (tokenize.TokenError, IndentationError):
        return ""
    return "".join(out)


def _line_at(unit_start: int, body: str, index: int) -> int:
    """Add newline count, because a unit starts mid file."""
    return unit_start + body.count("\n", 0, index)


def _snippet_at(body: str, index: int) -> str:
    """Bound the line, because a hit shows one line."""
    line_start = body.rfind("\n", 0, index) + 1
    line_end = body.find("\n", index)
    return body[line_start:line_end] if line_end != -1 else body[line_start:]


def _own_private_calls(unit_start: int, scan_text: str, body: str):
    for found in _PRIVATE_CALL.finditer(scan_text):
        if found.group("owner") == "self" or found.group("name") in _NAMEDTUPLE_NAMES:
            continue
        yield Hit(METHODS_RULE.name, _line_at(unit_start, body, found.start()),
                  _snippet_at(body, found.start()))


def _private_name(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and bool(_PRIVATE_NAME.fullmatch(node.value)) and node.value not in _NAMEDTUPLE_NAMES)


def _external(node: ast.expr) -> bool:
    while isinstance(node, ast.Attribute):
        node = node.value
    return not isinstance(node, ast.Name) or node.id != "self"


def _lookup(node: ast.Call) -> tuple[ast.expr, ast.expr] | None:
    if isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
        return node.args[0], node.args[1]
    if (isinstance(node.func, ast.Attribute) and node.func.attr == "__getattribute__"
            and node.args):
        return node.func.value, node.args[0]
    return None


def _called_lookup(node: ast.Call, parents: dict[ast.AST, ast.AST], calls: set[str]) -> bool:
    parent = parents.get(node)
    if isinstance(parent, ast.Call) and parent.func is node:
        return True
    targets = parent.targets if isinstance(parent, ast.Assign) else ()
    return any(isinstance(target, ast.Name) and target.id in calls for target in targets)


def _dynamic_rule(node: ast.AST, parents: dict[ast.AST, ast.AST], calls: set[str]) -> str | None:
    if isinstance(node, ast.Call):
        target = _lookup(node)
        if target and _external(target[0]) and _private_name(target[1]):
            return METHODS_RULE.name if _called_lookup(node, parents, calls) else STATE_RULE.name
        if (isinstance(node.func, ast.Attribute) and len(node.args) >= 2
                and ast.unparse(node.func) in {"monkeypatch.setattr", "patch.object", "mock.patch.object"}
                and _external(node.args[0]) and _private_name(node.args[1])):
            return METHODS_RULE.name
    if isinstance(node, ast.Subscript) and _private_name(node.slice):
        value = node.value
        if isinstance(value, ast.Attribute) and value.attr == "__dict__" and _external(value.value):
            return STATE_RULE.name
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id == "vars" and value.args and _external(value.args[0])):
            return STATE_RULE.name
    return None


def _dynamic_access_hits(unit, text: str):
    tree = module_tree(text)
    scope = module_scopes(tree).get((unit.start, unit.end)) if tree else None
    if scope is None:
        return
    # Because unit bodies exclude outer decorators, leave the cached node intact.
    scope = copy.copy(scope)
    scope.decorator_list = []
    parents = {child: parent for parent in ast.walk(scope) for child in ast.iter_child_nodes(parent)}
    calls = {node.func.id for node in ast.walk(scope)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    lines = text.splitlines()
    for node in ast.walk(scope):
        rule = _dynamic_rule(node, parents, calls)
        if rule:
            yield Hit(rule, node.lineno, lines[node.lineno - 1])


def _own_private_attrs(unit_start: int, scan_text: str, body: str):
    for found in _PRIVATE_ATTR.finditer(scan_text):
        if found.group("owner") == "self" or found.group("name") in _NAMEDTUPLE_NAMES:
            continue
        yield Hit(STATE_RULE.name, _line_at(unit_start, body, found.start()),
                  _snippet_at(body, found.start()))


def check(unit, text: str) -> list[Hit]:
    """Scan Python only, because underscores carry no privacy rule in Rust."""
    if unit.language != "python":
        return []
    body = unit.body
    scan_text = _masked(body)
    return [
        *_own_private_calls(unit.start, scan_text, body),
        *_dynamic_access_hits(unit, text),
        *_own_private_attrs(unit.start, scan_text, body),
    ]


RULE_SET = RuleSet(rules=(METHODS_RULE, STATE_RULE), check=check)
