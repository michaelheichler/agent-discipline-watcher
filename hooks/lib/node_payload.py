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
NODE_REFLECTION_RE = re.compile(
    r"\b(?:getBuiltinModule|_load|_linkedBinding|binding|dlopen|mainModule|constructor|prototype|getPrototypeOf|"
    r"getOwnProperty\w*|require|import|Function|eval|Reflect|module|global|globalThis|this|arguments|WebAssembly)\b|"
    r"\bprocess\b(?!\s*\.\s*(?:version|versions|platform|arch|pid|argv|env|execPath|release|uptime|cwd|exit)\b)"
)
LITERAL_KEY_RE = re.compile(r"""\[\s*(['"])([A-Za-z_$][\w$]*)\1\s*\]""")
LITERAL_KEY_AT_RE = re.compile(r"""\s*(?:\d+|'[^'\\\n]*'|"[^"\\\n]*")\s*\]""")
ARRAY_OPENERS = frozenset("(,=:[{;")


def node_json_read(name: str, payload: str, directories: Sequence[str]) -> bool:
    """Whole payload only, because a JSON require in a shape with no other code adds no trust to the token list."""
    if name not in NODE_INTERPRETERS or NODE_JSON_READ_RE.fullmatch(payload) is None:
        return False
    required = JSON_REQUIRE_PATH_RE.search(payload)
    return bool(directories) and required is not None and all(
        _plain_json_file(os.path.join(directory, required.group(2))) for directory in directories
    )


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
    dotted = LITERAL_KEY_RE.sub(lambda match: "." + match.group(2), payload)
    return NODE_REFLECTION_RE.search(dotted) is not None or any(
        _bracket_hides_name(payload, match.start()) for match in re.finditer(r"\[", payload)
    )


def _bracket_hides_name(payload: str, start: int) -> bool:
    """Only a plain literal key may follow a member access, because any other key names a member the text never spells out."""
    before = payload[:start].rstrip()
    rest = payload[start + 1:]
    if before and before[-1] not in ARRAY_OPENERS:
        return LITERAL_KEY_AT_RE.match(rest) is None
    return "+" in rest.partition("]")[0]
