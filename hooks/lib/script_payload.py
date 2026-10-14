"""Because perl and ruby call file and process builtins without parentheses, the shared token list misses their write routes."""
from __future__ import annotations

import re

SCRIPT_INTERPRETERS = frozenset({"perl", "ruby"})
SCRIPT_WRITE_RE = re.compile(
    r"\b(?:open|sysopen|syswrite|rename|unlink|truncate|link|symlink|mkdir|rmdir|chmod|chown|utime|"
    r"system|exec|spawn|fork|syscall|qx|reopen|FileUtils|Pathname|Open3|Kernel|send|public_send|const_get|"
    r"eval|instance_eval|class_eval|module_eval|binding|ObjectSpace|CORE)\b|\b(?:File|IO)::|%x|\$\^I|\$-i"
)
DELIMITED = r"([^\w\s\\{}()\[\]<>])(?:\\[^\n]|(?!\1)[^\\\n$@])*\1(?:\\[^\n]|(?!\1)[^\\\n$@])*\1"
BRACKETED = r"\{(?:\\[^\n]|[^\\\n{}$@])*\}\s*\{(?:\\[^\n]|[^\\\n{}$@])*\}"
PERL_SUBSTITUTION_RE = re.compile(rf"\s*(?:s|tr|y)(?:{DELIMITED}|{BRACKETED})[gimsx]*\s*")


def script_write(payload: str) -> bool:
    return SCRIPT_WRITE_RE.search(payload) is not None


def perl_substitution(script: str) -> bool:
    """Because interpolation and (?{ }) blocks run code, the script may hold one s, tr or y operator with no $, @ or code group."""
    return PERL_SUBSTITUTION_RE.fullmatch(script) is not None and "(?" not in script and "`" not in script
