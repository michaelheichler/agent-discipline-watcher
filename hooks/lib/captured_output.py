"""Because a tool that prints what it read or ran emits text nobody in this session typed, its captured output enters as an imported copy."""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from lib.shell_lines import command_lines
from lib.shell_parse import _journal_words
from lib.shell_syntax import (
    VERSIONED_PYTHON_RE, _bare, _basename, _is_literal_token, _payload_command_index, _pipeline_groups,
    _without_redirects, interpreter_invocation,
)

LOCAL_TOOLS = frozenset({
    "mosquitto_sub", "journalctl", "ffmpeg", "ffprobe", "esphome", "pio", "platformio", "idf.py",
    "vitest", "playwright", "pytest", "jest",
})
# Because these name a subcommand that only shows state the agent did not type.
VIEW_SUBCOMMANDS = {
    "docker": frozenset({"logs", "inspect", "ps", "images", "version", "info", "stats"}),
    "podman": frozenset({"logs", "inspect", "ps", "images", "version", "info", "stats"}),
    "kubectl": frozenset({"logs", "get", "describe", "top", "version"}),
}
GH_VIEWS = frozenset({"view", "list", "status", "diff", "checks"})
GH_DATA_FLAGS = ("-f", "-F", "--field", "--raw-field", "--input", "-X", "--method")
NPX_TOOLS = frozenset({"vitest", "playwright", "jest", "tsc", "eslint", "prettier", "esphome"})
PACKAGE_RUNNERS = {
    "npm": frozenset({"test", "t", "run", "run-script"}),
    "pnpm": frozenset({"test", "t", "run"}),
    "yarn": frozenset({"test", "run"}),
    "bun": frozenset({"test", "run"}),
}
MAKEFILES = ("GNUmakefile", "makefile", "Makefile")
MAKE_FILE_FLAGS = ("-f", "--file", "--makefile", "-C", "--directory")
SCRIPT_INTERPRETERS = frozenset({
    "python", "python2", "python3", "node", "nodejs", "ruby", "perl", "bash", "sh", "zsh", "dash", "ksh", "tsx", "ts-node",
})
TRUSTED_MODULES = frozenset({"pytest"})
REMOTE_READERS = frozenset({
    "cat", "head", "tail", "ls", "journalctl", "systemctl", "dmesg", "df", "ps", "uptime", "ip", "ha", "hass-cli",
    "mosquitto_sub", "docker", "free", "uname",
})
SSH_VALUE_OPTIONS = frozenset({"-b", "-c", "-D", "-E", "-e", "-F", "-I", "-i", "-J", "-L", "-l", "-m", "-O", "-o", "-p", "-Q", "-R", "-S", "-W", "-w"})
LOCAL_HOST_RE = re.compile(r"^(?:[^@]*@)?(?:localhost|127(?:\.\d+){3}|::1|0\.0\.0\.0|\[::1\])$", re.IGNORECASE)
REMOTE_OPERATOR_RE = re.compile(r"[;&|<>`$()]")
PASSTHROUGH_STAGES = frozenset({
    "tee", "grep", "egrep", "fgrep", "rg", "head", "tail", "sort", "uniq", "cut", "wc", "nl", "column", "strings", "tr", "cat",
})
UNSAFE_NAME_CHARS = frozenset("$`*?[~{")
# Because these carry words the agent typed or a file it fed into the capture.
AGENT_TEXT_RE = re.compile(r"<<|<\(|>\(|\$\(|`|(?<![\w./-])(?:echo|printf)(?![\w.-])")
INPUT_REDIRECT_RE = re.compile(r"^\d*<")
INLINE_CODE_RE = re.compile(
    r"(?<![\w./-])(?:python[\d.]*|node(?:js)?|ruby|perl|php|deno|bun|tsx|(?:ba|z|da|k)?sh)"
    r"(?:\s+\S+)*?\s+-(?:c|e|E|p|r|-eval|-print)(?![\w-])"
)
DIRECTORY_CHANGE_RE = re.compile(r"(?<![\w./-])(?:cd|pushd|popd)(?![\w.-])")
MODULE_FLAG = "-m"
GIT_SECONDS = 5


def captured_outputs(command: str, base: Path) -> list[str]:
    """Nothing after a directory change, because a relative target would then resolve against the wrong folder."""
    if DIRECTORY_CHANGE_RE.search(command):
        return []
    found: list[str] = []
    for line in command_lines(command):
        for group in _pipeline_groups(line.text):
            found.extend(str(base / path) for path in _group_targets(group, base))
    return found


def _group_targets(group: list[list[str]], base: Path) -> list[str]:
    """Truncating literal targets only, because an append keeps the agent's earlier text in the same file."""
    text = " ".join(token for segment in group for token in segment)
    if AGENT_TEXT_RE.search(text) or INLINE_CODE_RE.search(text) or _feeds_input(group):
        return []
    if not _is_producer(group[0], base) or not all(_is_passthrough(segment, base) for segment in group[1:]):
        return []
    words = [pair for segment in group for pair in _journal_words(segment)]
    return [
        _bare(word) for word, append in words
        if not append and _is_literal_token(word) and not UNSAFE_NAME_CHARS.intersection(_bare(word))
    ]


def _feeds_input(group: list[list[str]]) -> bool:
    """Because a < redirect hands a file the agent may have written to the producer."""
    return any(INPUT_REDIRECT_RE.match(token) for segment in group for token in segment)


def _command(segment: list[str]) -> tuple[str, list[str]]:
    index = _payload_command_index(segment)
    if index >= len(segment):
        return "", []
    return _basename(segment[index]), [_bare(token) for token in _without_redirects(segment[index + 1:])]


def _is_producer(segment: list[str], base: Path) -> bool:
    verb, args = _command(segment)
    if verb in SCRIPT_INTERPRETERS or VERSIONED_PYTHON_RE.fullmatch(verb):
        return interpreter_invocation(segment) is None and _runs_pristine_script(args, base)
    first = args[0] if args else ""
    checks = {
        "ssh": lambda: _ssh_reads(args),
        "gh": lambda: _gh_views(args),
        "npx": lambda: first in NPX_TOOLS,
        "make": lambda: not any(arg.startswith(MAKE_FILE_FLAGS) for arg in args) and _pristine_makefile(base),
    }
    if verb in checks:
        return checks[verb]()
    if verb in VIEW_SUBCOMMANDS:
        return first in VIEW_SUBCOMMANDS[verb]
    if verb in PACKAGE_RUNNERS:
        return first in PACKAGE_RUNNERS[verb] and _pristine(base / "package.json", base)
    return verb in LOCAL_TOOLS


def _ssh_reads(args: list[str]) -> bool:
    """A remote host and a plain reader only, because localhost serves the agent's own files and a remote shell runs any text."""
    position = 0
    while position < len(args) and args[position].startswith("-"):
        position += 2 if args[position] in SSH_VALUE_OPTIONS else 1
    if position + 1 >= len(args) or LOCAL_HOST_RE.match(args[position]):
        return False
    remote = " ".join(args[position + 1:])
    if REMOTE_OPERATOR_RE.search(remote) or AGENT_TEXT_RE.search(remote):
        return False
    try:
        words = shlex.split(remote)
    except ValueError:
        return False
    return bool(words) and _basename(words[0]) in REMOTE_READERS


def _gh_views(args: list[str]) -> bool:
    """Because gh api echoes fields the agent sends, only a request without data counts."""
    if len(args) >= 2 and args[1] in GH_VIEWS:
        return True
    return bool(args) and args[0] == "api" and not any(arg.startswith(GH_DATA_FLAGS) for arg in args[1:])


def _pristine_makefile(base: Path) -> bool:
    """Named from the listing, because a case-blind disk answers for makefile while git tracks Makefile."""
    try:
        listed = {entry.name for entry in base.iterdir()}
    except OSError:
        return False
    found = next((base / name for name in MAKEFILES if name in listed), None)
    return found is not None and _pristine(found, base)


def _runs_pristine_script(args: list[str], base: Path) -> bool:
    """Because a script the agent wrote prints whatever it put there, only a committed, unchanged file or a known module counts."""
    for index, arg in enumerate(args):
        if arg == MODULE_FLAG:
            return index + 1 < len(args) and args[index + 1] in TRUSTED_MODULES
        if not arg.startswith("-"):
            return _is_literal_token(arg) and _pristine(base / arg, base)
    return False


def _pristine(path: Path, base: Path) -> bool:
    """Committed and unchanged, because an untracked or edited file may hold the agent's own text."""
    if not path.is_file():
        return False
    try:
        tracked = subprocess.run(
            ["git", "-C", str(base), "ls-files", "--error-unmatch", "--", str(path)],
            capture_output=True, timeout=GIT_SECONDS, check=False,
        )
        changed = subprocess.run(
            ["git", "-C", str(base), "diff", "--quiet", "HEAD", "--", str(path)],
            capture_output=True, timeout=GIT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return tracked.returncode == 0 and changed.returncode == 0


def _is_passthrough(segment: list[str], base: Path) -> bool:
    """Because grep or cat over a file the agent wrote prints the agent's own words, no stage may read a local file."""
    verb, args = _command(segment)
    if verb not in PASSTHROUGH_STAGES:
        return False
    return verb == "tee" or not any(arg != "-" and (base / arg).exists() for arg in args if not arg.startswith("-"))
