"""Blocks Bash write routes the gate cannot judge, because their payload never passes through text the scanner can read."""
from __future__ import annotations

import re
from collections.abc import Callable

from lib.shell_parse import (
    HeredocEvent, SHELL_C_INTERPRETERS, _bare, _basename, _command_word_index, _interpreter_code_flags,
    _is_file_target, _literal_contents, _logical_lines, _payload_command_index, _pipeline_groups, _segment_text,
    _segments, _write_path_writes, has_process_substitution, heredoc_events, interpreter_invocation,
)

FindingFactory = Callable[[str], dict]
RecurseFn = Callable[[str], list[dict]]

WRITE_CAPABLE_TOKEN_RE = re.compile(
    r"open\(|\.write\(|\bwrite\(|\.write_text\(|\.write_bytes\(|\bexec\(|\beval\(|__|\bsubprocess\b|"
    r"\bimport\s+(?:os|shutil|pathlib)\b|\bfrom\s+(?:os|shutil|pathlib|io)\s+import\b|"
    r"\bos\.\w|\bshutil\.\w|\bpathlib\.\w|"
    r"\bfs\.\w|\bFile\.\w|\bIO\.\w|decode\(|`|"
    r"\brequire\(|\bfile_put_contents\(|\bfopen\(|\bfwrite\("
)
DECODE_FLAGS: dict[str, frozenset[str]] = {
    "base64": frozenset({"-d", "--decode"}),
    "xxd": frozenset({"-r"}),
}
DECODE_ALWAYS_VERBS = frozenset({"uudecode"})
DECODE_OUTPUT_FLAGS = frozenset({"-o", "--output", "-out"})
OPENSSL_DECODE_SUBCOMMANDS = frozenset({"enc", "base64"})
OPENSSL_DECODE_FLAGS = frozenset({"-d", "-decrypt"})
INPLACE_VERBS = frozenset({"sed", "perl", "ruby"})
AWK_VERBS = frozenset({"awk", "gawk"})
# Each verb gets its own consuming set because sed's -E takes no argument while perl and ruby's -e/-E/-I do.
VALUE_CONSUMING_FLAGS: dict[str, frozenset[str]] = {
    "sed": frozenset({"e"}),
    "perl": frozenset({"I", "e", "E"}),
    "ruby": frozenset({"I", "e", "E"}),
}
MUTATING_VERB_RE = re.compile(
    r"\b(?:tee|cp|mv|ln|rm|truncate|chmod|chown|dd|shred|unlink)\b|\bsed\s+-i", re.IGNORECASE
)


def _is_positional_argument(token: str) -> bool:
    """Exclude a redirect or heredoc operator token here, because it names a stream, not code for the interpreter to run."""
    bare = _bare(token)
    return not bare.startswith(("-", "<", ">"))


def _bare_interpreter_name(segment: list[str]) -> str | None:
    """Return the interpreter name only when it has no positional argument, because a named script argument reads from a file, not stdin."""
    index = _payload_command_index(segment)
    if index >= len(segment):
        return None
    name = _basename(segment[index])
    if _interpreter_code_flags(name) is None:
        return None
    trailing = segment[index + 1:]
    if any(_is_positional_argument(token) for token in trailing):
        return None
    return name


def _is_bare_interpreter_segment(segment: list[str]) -> bool:
    """Report only an interpreter with no positional argument, because a named script argument reads from a file, not stdin."""
    return _bare_interpreter_name(segment) is not None


def inline_interpreter_findings(command: str, make_finding: FindingFactory) -> list[dict]:
    """Blocks the payload, because an interpreter's inline code can call write APIs the text scanner never inspects, and an unreadable payload cannot be judged safe."""
    findings = []
    for segment in _segments(command):
        invocation = interpreter_invocation(segment)
        if invocation is None or invocation.interpreter in SHELL_C_INTERPRETERS:
            continue
        if invocation.payload is None or WRITE_CAPABLE_TOKEN_RE.search(invocation.payload):
            findings.append(make_finding("inline_interpreter_write"))
    return findings


def interpreter_stdin_findings(command: str, make_finding: FindingFactory, recurse: RecurseFn) -> list[dict]:
    """Blocks the body, because a heredoc or pipe feeding an interpreter's stdin reaches the same write APIs an inline payload does. A shell consumer's literal body is itself a shell command, so it re-enters the full gate one level deep instead of being judged by the interpreter token regex, the way a literal shell -c payload already is."""
    findings = []
    for event in heredoc_events(command):
        findings.extend(_heredoc_stdin_findings(event, make_finding, recurse))
    for line, _, _ in _logical_lines(command):
        for group in _pipeline_groups(line):
            findings.extend(_pipe_interpreter_findings(group, make_finding, recurse))
    return findings


def _heredoc_stdin_findings(event: HeredocEvent, make_finding: FindingFactory, recurse: RecurseFn) -> list[dict]:
    """Judge one heredoc's body against its actual consumer, because a shell consumer reads its own stdin as a nested command while any other interpreter reads it as inline code."""
    name = _bare_interpreter_name(event.consumer_segment)
    if name is None:
        return []
    if name in SHELL_C_INTERPRETERS:
        if event.dynamic:
            return [make_finding("interpreter_heredoc_write")]
        return recurse(event.body)
    if event.dynamic or WRITE_CAPABLE_TOKEN_RE.search(event.body):
        return [make_finding("interpreter_heredoc_write")]
    return []


def _pipe_interpreter_findings(group: list[list[str]], make_finding: FindingFactory, recurse: RecurseFn) -> list[dict]:
    """Judge every bare interpreter stage that has a producer ahead of it, because stdin reaches a middle stage exactly as it reaches the last one."""
    findings = []
    for index in range(1, len(group)):
        if _is_bare_interpreter_segment(group[index]):
            findings.extend(_stage_interpreter_findings(group[:index], group[index], make_finding, recurse))
    return findings


def _stage_interpreter_findings(
    producers: list[list[str]], consumer: list[str], make_finding: FindingFactory, recurse: RecurseFn,
) -> list[dict]:
    """Judge one interpreter stage's stdin against its own producer text, because a shell consumer reads its stdin as a nested command while any other interpreter reads it as inline code."""
    producer_texts = _literal_contents(producers)
    if len(producer_texts) != len(producers) or None in producer_texts:
        return [make_finding("interpreter_heredoc_write")]
    joined = "\n".join(producer_texts)
    if _bare_interpreter_name(consumer) in SHELL_C_INTERPRETERS:
        return recurse(joined)
    if WRITE_CAPABLE_TOKEN_RE.search(joined):
        return [make_finding("interpreter_heredoc_write")]
    return []


def dynamic_heredoc_findings(command: str, make_finding: FindingFactory) -> list[dict]:
    """Blocks the heredoc, because its dynamic or unterminated body cannot be read before it lands in the target file."""
    findings = []
    for event in heredoc_events(command):
        if _is_bare_interpreter_segment(event.consumer_segment):
            continue
        if event.dynamic and event.group_has_write_target:
            findings.append(make_finding("dynamic_heredoc_write"))
    return findings


def _is_decode_segment(segment: list[str]) -> bool:
    index = _command_word_index(segment)
    if index >= len(segment):
        return False
    verb = _basename(segment[index])
    if verb in DECODE_ALWAYS_VERBS:
        return True
    args = segment[index + 1:]
    if verb == "openssl":
        return _openssl_decodes(args)
    flags = DECODE_FLAGS.get(verb)
    return flags is not None and any(_bare(token) in flags for token in args)


def _openssl_decodes(args: list[str]) -> bool:
    """Require an enc or base64 subcommand plus a decrypt flag, because openssl enc without -d encrypts."""
    if not args or _bare(args[0]) not in OPENSSL_DECODE_SUBCOMMANDS:
        return False
    return any(_bare(token) in OPENSSL_DECODE_FLAGS for token in args[1:])


def _decode_writes_file(segment: list[str]) -> bool:
    """Treat uudecode and -o/-out destinations as writes, because those tools land bytes on disk with no redirect token. Skip xxd, because xxd -o is a display offset rather than a file."""
    index = _command_word_index(segment)
    if index >= len(segment):
        return False
    verb = _basename(segment[index])
    if verb in DECODE_ALWAYS_VERBS:
        return True
    if verb == "xxd":
        return False
    return _has_file_output_flag(segment[index + 1:])


def _has_file_output_flag(tokens: list[str]) -> bool:
    """Accept GNU -o/--output and openssl -out, because those flags name a file without using > or tee."""
    expecting = False
    for token in tokens:
        bare = _bare(token)
        if expecting:
            return _is_file_target(bare)
        if bare in DECODE_OUTPUT_FLAGS:
            expecting = True
            continue
        if bare.startswith("--output="):
            return _is_file_target(bare.partition("=")[2])
        if bare.startswith("-out=") and len(bare) > 5:
            return _is_file_target(bare[5:])
    return False


def decode_pipe_findings(command: str, make_finding: FindingFactory) -> list[dict]:
    """Blocks the pipe, because the decoded bytes never pass through a stage the scanner can read before they reach the file."""
    findings = []
    for line, _, _ in _logical_lines(command):
        for group in _pipeline_groups(line):
            decode_segments = [segment for segment in group if _is_decode_segment(segment)]
            if decode_segments and (
                any(_write_path_writes(segment) for segment in group)
                or any(_decode_writes_file(segment) for segment in decode_segments)
            ):
                findings.append(make_finding("decode_pipe_write"))
    return findings


def _cluster_has_inplace(verb: str, letters: str) -> bool:
    """Stop at the first letter that consumes an attached value for this verb, because the rest of the token is that flag's argument, not more short flags."""
    value_consuming = VALUE_CONSUMING_FLAGS.get(verb, frozenset())
    for letter in letters:
        if letter == "i":
            return True
        if letter in value_consuming:
            return False
    return False


def _awk_has_inplace(tokens: list[str]) -> bool:
    """Judges only the inplace extension, because gawk's -i otherwise loads read-only include libraries that must stay allowed."""
    expecting_value = False
    for token in tokens:
        bare = _bare(token)
        if expecting_value:
            if bare.startswith("inplace"):
                return True
            expecting_value = False
            continue
        if bare == "--inplace" or bare.startswith("--inplace="):
            return True
        if bare in ("-i", "--include"):
            expecting_value = True
        elif bare.startswith("-i") and not bare.startswith("--") and bare[2:].startswith("inplace"):
            return True
    return False


def _has_inplace_flag(segment: list[str]) -> bool:
    index = _command_word_index(segment)
    if index >= len(segment):
        return False
    verb = _basename(segment[index])
    if verb in AWK_VERBS:
        return _awk_has_inplace(segment[index + 1:])
    if verb not in INPLACE_VERBS:
        return False
    for token in segment[index + 1:]:
        bare = _bare(token)
        if bare == "--in-place" or bare.startswith("--in-place="):
            return True
        if bare.startswith("-") and not bare.startswith("--") and _cluster_has_inplace(verb, bare[1:]):
            return True
    return False


def inplace_edit_findings(command: str, make_finding: FindingFactory) -> list[dict]:
    """Blocks the invocation, because an in-place editor mutates its target file directly, bypassing the Edit tool."""
    return [make_finding("inplace_edit_write") for segment in _segments(command) if _has_inplace_flag(segment)]


def _dd_file_output(segment: list[str]) -> bool:
    index = _command_word_index(segment)
    if index >= len(segment) or _basename(segment[index]) != "dd":
        return False
    for token in segment[index + 1:]:
        bare = _bare(token)
        if bare.startswith("of="):
            return _is_file_target(bare[3:])
    return False


def _line_is_mutating(line: str) -> bool:
    """Read the whole line's segments here, because process substitution splits a segment's own redirect onto a neighbor."""
    segments = _segments(line)
    return any(_write_path_writes(segment) for segment in segments) or any(
        MUTATING_VERB_RE.search(_segment_text(segment)) for segment in segments
    )


def opaque_source_findings(command: str, make_finding: FindingFactory) -> list[dict]:
    """Blocks the source, because a dd file output or a process-substitution source hides its payload behind another process the scanner cannot read."""
    findings = [make_finding("opaque_source_write") for segment in _segments(command) if _dd_file_output(segment)]
    for line, _, _ in _logical_lines(command):
        if has_process_substitution(line) and _line_is_mutating(line):
            findings.append(make_finding("opaque_source_write"))
    return findings
