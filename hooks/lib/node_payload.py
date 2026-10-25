"""Judges node -e and -p payloads, because node reaches the file system through reflection that the shared token list never names."""
from __future__ import annotations

import os
import re
import stat
from collections.abc import Sequence

NODE_INTERPRETERS = frozenset({"node", "nodejs"})
NODE_JSON_PATH = r"(?:\.{1,2}/|/)[^'\"\\\n]*\.json"
NODE_JSON_READ = (
    rf"require\(\s*(?:'{NODE_JSON_PATH}'|\"{NODE_JSON_PATH}\")\s*\)"
    r"""(?:\.[A-Za-z_$][\w$]*|\[\s*(?:\d+|'[^'\\\n]*'|"[^"\\\n]*")\s*\])*"""
)
NODE_JSON_WRAPPED = r"(?:console\.log|JSON\.stringify|Object\.keys)\(\s*(?:{inner})(?:\s*,\s*null\s*,\s*\d+)?\s*\)"
NODE_JSON_ONCE = NODE_JSON_WRAPPED.format(inner=NODE_JSON_READ)
NODE_JSON_READ_RE = re.compile(
    rf"\s*(?:{NODE_JSON_READ}|{NODE_JSON_ONCE}|{NODE_JSON_WRAPPED.format(inner=NODE_JSON_ONCE)})\s*;?\s*"
)
JSON_REQUIRE_PATH_RE = re.compile(r"""require\(\s*(['"])([^'"]*)\1""")
JSON_REQUIRE_CALL_RE = re.compile(rf"""require\(\s*(['"])({NODE_JSON_PATH})\1\s*\)""")
JSON_STAND_IN = "0"
NODE_REFLECTION_RE = re.compile(
    r"\b(?:getBuiltinModule|_load|_linkedBinding|binding|dlopen|mainModule|constructor|prototype|getPrototypeOf|"
    r"getOwnProperty\w*|require|import|Function|eval|Reflect|module|global|globalThis|this|arguments|WebAssembly)\b|"
    r"\bprocess\b(?!\s*\.\s*(?:version|versions|platform|arch|pid|argv|env|execPath|release|uptime|cwd|exit)\b)"
)
LITERAL_KEY_RE = re.compile(r"""\[\s*(['"])([A-Za-z_$][\w$]*)\1\s*\]""")
LITERAL_KEY_AT_RE = re.compile(r"""\s*(?:\d+|'[^'\\\n]*'|"[^"\\\n]*")\s*\]""")
ARRAY_OPENERS = frozenset("(,=:[{;")
# Because node reads these as comments, keeping them as code could mask live text.
HTML_COMMENT_MARKS = ("<!--", "-->")
LINE_TERMINATORS = "\n\r" + chr(0x2028) + chr(0x2029)
CONTROL_KEYWORDS = frozenset({"if", "while", "for", "with"})
CONTROL_CLOSE = ")if"
TOKEN_RE = re.compile(r"""\s+|'(?:\\[\s\S]|[^'\\\n\r])*'|"(?:\\[\s\S]|[^"\\\n\r])*"|[\w$]+|\+\+|--|[(){}\[\];,.<>=!+\-*%&|^~?:]""")
WORD_RE = re.compile(r"[\w$]+")
REGEX_LITERAL_RE = re.compile(r"/(?:\\[^\n\r]|\[(?:\\[^\n\r]|[^\]\\\n\r])*\]|[^/\\\[\n\r])+/[A-Za-z]*(?![\w$])")
REGEX_AFTER = frozenset("(,=:[!&|?{;~^%*<>/+-")
EXPRESSION_KEYWORDS = frozenset({
    "await", "break", "case", "continue", "debugger", "default", "delete", "do", "else", "extends",
    "in", "instanceof", "new", "of", "return", "throw", "typeof", "void", "yield",
})
REGEX, DIVISION = "regex", "division"
REGEX_STAND_IN = "0"


def node_json_read(name: str, payload: str, directories: Sequence[str]) -> bool:
    """Whole payload only, because a JSON require in a shape with no other code adds no trust to the token list."""
    if name not in NODE_INTERPRETERS or NODE_JSON_READ_RE.fullmatch(payload) is None:
        return False
    required = JSON_REQUIRE_PATH_RE.search(payload)
    return bool(directories) and required is not None and all(
        _plain_json_file(os.path.join(directory, required.group(2))) for directory in directories
    )


def without_json_requires(payload: str, directories: Sequence[str]) -> str | None:
    """None unless every literal JSON require names a plain JSON file, because node runs a .js target or index.js as code."""
    found = list(JSON_REQUIRE_CALL_RE.finditer(payload))
    if not found or not directories:
        return None
    paths = {match.group(2) for match in found}
    if not all(_plain_json_file(os.path.join(directory, path)) for directory in directories for path in paths):
        return None
    return JSON_REQUIRE_CALL_RE.sub(JSON_STAND_IN, payload)


def _plain_json_file(path: str) -> bool:
    """Because node loads a symlink by its target extension and a directory by its index.js, only a regular .json file runs no code."""
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    real = os.path.realpath(path)
    return stat.S_ISREG(metadata.st_mode) and real.endswith(".json") and os.path.isfile(real)


def node_reflection(payload: str) -> bool:
    """Literal keys read as dot access first, because process['binding'] reaches the same module as process.binding."""
    if _has_unicode_escape(payload):
        return True
    dotted = LITERAL_KEY_RE.sub(lambda match: "." + match.group(2), payload)
    code = _without_regex_literals(payload)
    return NODE_REFLECTION_RE.search(dotted) is not None or any(
        _bracket_hides_name(code, match.start()) for match in re.finditer(r"\[", code)
    )


def _without_regex_literals(payload: str) -> str:
    """For the bracket check only, because the class in /[a-z]/ is no computed member access."""
    kept: list[str] = []
    recent: tuple[str | None, str | None] = (None, None)
    parens: list[bool] = []
    position = 0
    while position < len(payload):
        token = _token_at(payload, position, recent[1])
        if token is None:
            return payload
        text, position = token
        kept.append(text)
        if not text.isspace():
            recent = (recent[1], _significant(text, recent, parens))
    return "".join(kept)


def _significant(text: str, recent: tuple[str | None, str | None], parens: list[bool]) -> str:
    """Because if (x) /a/ opens a regex where f(x) /a/ divides, a paren remembers whether a control keyword opened it."""
    if text == "(":
        parens.append(recent[1] in CONTROL_KEYWORDS and recent[0] != ".")
    if text == ")" and parens and parens.pop():
        return CONTROL_CLOSE
    return text


def _token_at(payload: str, position: int, previous: str | None) -> tuple[str, int] | None:
    """None where the text is unclear, because masking a misread slash would hide live code."""
    if payload.startswith(HTML_COMMENT_MARKS, position):
        return None
    if payload.startswith("//", position):
        ends = [index for index in map(lambda end: payload.find(end, position), LINE_TERMINATORS) if index >= 0]
        return " ", min(ends, default=len(payload))
    if payload.startswith("/*", position):
        end = payload.find("*/", position + 2)
        return None if end < 0 else (" ", end + 2)
    if payload[position] != "/":
        match = TOKEN_RE.match(payload, position)
        return None if match is None else (match.group(), match.end())
    role = _slash_role(previous)
    if role == DIVISION:
        return "/", position + 1
    match = REGEX_LITERAL_RE.match(payload, position) if role == REGEX else None
    return None if match is None else (REGEX_STAND_IN, match.end())


def _slash_role(previous: str | None) -> str | None:
    """None when only a parser could tell, because only a control paren lets a regex follow a closing paren."""
    if previous is None or previous in REGEX_AFTER or previous == CONTROL_CLOSE:
        return REGEX
    operand = WORD_RE.fullmatch(previous) is not None and previous not in EXPRESSION_KEYWORDS
    return DIVISION if operand or previous == "]" or previous[0] in "'\"" else None


def _has_unicode_escape(payload: str) -> bool:
    """Because JavaScript reads \\u0063onstructor as constructor, a name check on the raw spelling cannot see it."""
    return "\\u" in payload


def _bracket_hides_name(payload: str, start: int) -> bool:
    """Only a plain literal key may follow a member access, because any other key names a member the text never spells out."""
    before = payload[:start].rstrip()
    rest = payload[start + 1:]
    if before and before[-1] not in ARRAY_OPENERS:
        return LITERAL_KEY_AT_RE.match(rest) is None
    return "+" in rest.partition("]")[0]
