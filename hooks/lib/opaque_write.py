"""Blocks Bash write routes the gate cannot judge, because their payload never passes through text the scanner can read."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from lib.shell_parse import (
    HeredocEvent, SHELL_C_INTERPRETERS, _bare, _basename, _command_word_index, _interpreter_code_flags,
    _is_file_target, _literal_contents, _logical_lines, _payload_command_index, _pipeline_groups, _segment_text,
    _segments, _tokens, _write_path_writes, has_process_substitution, heredoc_events, interpreter_invocation,
)
from lib.python_payload import is_known_read_only_python
from lib.python_shell import isolated_python, python_startup, startup_finding

FindingFactory = Callable[[str], dict]
RecurseFn = Callable[[str], list[dict]]


@dataclass(frozen=True, slots=True)
class InterpreterStage:
    producers: tuple[tuple[str, ...], ...]
    consumer: tuple[str, ...]


WRITE_CAPABLE_TOKEN_RE = re.compile(
    r"\.write\(|\bwrite\(|\.write_text\(|\.write_bytes\(|\bexec\(|\beval\(|__|\bsubprocess\b|"
    r"\bimport\s+(?:os|shutil|pathlib)\b|\bfrom\s+(?:os|shutil|pathlib|io)\s+import\b|"
    r"\bos\.\w|\bshutil\.\w|\bpathlib\.\w|"
    r"\bfs\.\w|\bFile\.\w|\bIO\.\w|decode\(|`|"
    r"\brequire\(|\bfile_put_contents\(|\bfopen\(|\bfwrite\("
)
PYTHON_INTERPRETER_RE = re.compile(r"python(?:2|3)?(?:\.\d+)?$")
OPEN_CALL_RE = re.compile(r"\bopen\(")
READ_ONLY_MODE_CHARS = frozenset("rbtU")
ARG_TOKEN_RE = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|[()]|,|[^()',\"]+")


def _quoted_literal(text: str) -> str | None:
    """None here because a mode built at runtime cannot be judged from text alone, only a literal ever clears an open() call."""
    for quote in ('"""', "'''", '"', "'"):
        if text.startswith(quote) and text.endswith(quote) and len(text) >= 2 * len(quote):
            return text[len(quote):-len(quote)]
    return None


def _split_top_level_args(payload: str, args_start: int) -> list[str] | None:
    """None on an unterminated call, because a close paren that never arrives leaves no real argument list to split."""
    depth, position = 1, args_start
    args, current = [], []
    for match in ARG_TOKEN_RE.finditer(payload, args_start):
        if match.start() != position:
            return None
        token = match.group()
        position = match.end()
        if token == "(":
            depth += 1
            current.append(token)
            continue
        if token == "," and depth == 1:
            args.append("".join(current))
            current = []
            continue
        if token != ")":
            current.append(token)
            continue
        depth -= 1
        if depth == 0:
            args.append("".join(current))
            return args
        current.append(token)
    return None


def _open_call_mode_is_write_capable(payload: str, args_start: int) -> bool:
    """True on an unterminated call, because a paren or quote left open past the payload end cannot be judged safe."""
    args = _split_top_level_args(payload, args_start)
    if args is None:
        return True
    if len(args) < 2:
        return False
    mode_arg = args[1].strip()
    if mode_arg.startswith("mode="):
        mode_arg = mode_arg[len("mode="):].strip()
    literal = _quoted_literal(mode_arg)
    if literal is None:
        return True
    return not set(literal) <= READ_ONLY_MODE_CHARS


def _inline_open_calls_write_capable(payload: str) -> bool:
    return any(
        _open_call_mode_is_write_capable(payload, match.end())
        for match in OPEN_CALL_RE.finditer(payload)
    )


def _payload_is_write_capable(interpreter: str, payload: str) -> bool:
    if PYTHON_INTERPRETER_RE.fullmatch(interpreter):
        return not is_known_read_only_python(payload, isolated=True)
    return bool(WRITE_CAPABLE_TOKEN_RE.search(payload) or _inline_open_calls_write_capable(payload))


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
VALUE_CONSUMING_FLAGS: dict[str, frozenset[str]] = {
    "sed": frozenset({"e", "f"}),
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
    findings = []
    for segment in _segments(command):
        index = _payload_command_index(segment)
        if index < len(segment) and PYTHON_INTERPRETER_RE.fullmatch(_basename(segment[index])) and python_startup(segment).unsupported_inline:
            findings.append(startup_finding(make_finding, "inline_interpreter_write"))
            continue
        invocation = interpreter_invocation(segment)
        if invocation is None or invocation.interpreter in SHELL_C_INTERPRETERS:
            continue
        if PYTHON_INTERPRETER_RE.fullmatch(invocation.interpreter) and not isolated_python(segment):
            findings.append(startup_finding(make_finding, "inline_interpreter_write"))
            continue
        if (
            invocation.payload is None
            or _payload_is_write_capable(invocation.interpreter, invocation.payload)
        ):
            findings.append(make_finding("inline_interpreter_write"))
    return findings


def interpreter_stdin_findings(command: str, make_finding: FindingFactory, recurse: RecurseFn) -> list[dict]:
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
    if PYTHON_INTERPRETER_RE.fullmatch(name) and not isolated_python(event.consumer_segment):
        return [startup_finding(make_finding, "interpreter_heredoc_write")]
    if event.dynamic or _payload_is_write_capable(name, event.body):
        return [make_finding("interpreter_heredoc_write")]
    return []


def _pipe_interpreter_findings(group: list[list[str]], make_finding: FindingFactory, recurse: RecurseFn) -> list[dict]:
    """Judge every bare interpreter stage that has a producer ahead of it, because stdin reaches a middle stage exactly as it reaches the last one."""
    findings = []
    for index in range(1, len(group)):
        if _is_bare_interpreter_segment(group[index]):
            stage = InterpreterStage(
                tuple(tuple(segment) for segment in group[:index]),
                tuple(group[index]),
            )
            findings.extend(_stage_interpreter_findings(stage, make_finding, recurse))
    return findings


def _stage_interpreter_findings(
    stage: InterpreterStage,
    make_finding: FindingFactory,
    recurse: RecurseFn,
) -> list[dict]:
    """Judge one interpreter stage's stdin against its own producer text, because a shell consumer reads its stdin as a nested command while any other interpreter reads it as inline code."""
    producers = [list(segment) for segment in stage.producers]
    producer_texts = _literal_contents(producers)
    if len(producer_texts) != len(producers) or None in producer_texts:
        return [make_finding("interpreter_heredoc_write")]
    joined = "\n".join(producer_texts)
    if _bare_interpreter_name(list(stage.consumer)) in SHELL_C_INTERPRETERS:
        return recurse(joined)
    name = _bare_interpreter_name(list(stage.consumer))
    if name is not None and PYTHON_INTERPRETER_RE.fullmatch(name) and not isolated_python(stage.consumer):
        return [startup_finding(make_finding, "interpreter_heredoc_write")]
    if name is not None and _payload_is_write_capable(name, joined):
        return [make_finding("interpreter_heredoc_write")]
    return []


def dynamic_heredoc_findings(command: str, make_finding: FindingFactory) -> list[dict]:
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


def _decode_pipe_findings_for_line(line: str, make_finding: FindingFactory) -> list[dict]:
    findings: list[dict] = []
    for group in _pipeline_groups(line):
        decode_segments = [segment for segment in group if _is_decode_segment(segment)]
        writes_decoded_bytes = bool(decode_segments) and (
            any(_write_path_writes(segment) for segment in group)
            or any(_decode_writes_file(segment) for segment in decode_segments)
        )
        if writes_decoded_bytes:
            findings.append(make_finding("decode_pipe_write"))
    return findings


def decode_pipe_findings(command: str, make_finding: FindingFactory) -> list[dict]:
    findings: list[dict] = []
    for line, _, _ in _logical_lines(command):
        findings.extend(_decode_pipe_findings_for_line(line, make_finding))
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
        if expecting_value and bare.startswith("inplace"):
            return True
        if expecting_value:
            expecting_value = False
            continue
        if bare == "--inplace" or bare.startswith("--inplace="):
            return True
        if bare in ("-i", "--include"):
            expecting_value = True
            continue
        if bare.startswith("-i") and not bare.startswith("--") and bare[2:].startswith("inplace"):
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


def _has_python_source(segment: list[str], depth: int = 0) -> bool:
    index = _payload_command_index(segment)
    if index < len(segment) and PYTHON_INTERPRETER_RE.fullmatch(_basename(segment[index])):
        return True
    invocation = interpreter_invocation(segment)
    if invocation is None or invocation.interpreter not in SHELL_C_INTERPRETERS:
        return False
    if depth >= 2 or invocation.payload is None:
        return True
    return any(_has_python_source(inner, depth + 1) for group in _output_pipeline_groups(invocation.payload) for inner in group)


def _output_pipeline_groups(line: str) -> list[list[list[str]]]:
    tokens: list[str] = []
    groups: list[str] = []
    for token in _tokens(line):
        command_start = not tokens or tokens[-1] in {";", "&&", "||", "|", "&"}
        if token == "(" or (token == "{" and command_start):
            groups.append(")" if token == "(" else "}")
        elif groups and token == groups[-1] and (token == ")" or command_start):
            groups.pop()
        else:
            tokens.append("|" if groups and token in {";", "&&", "||", "&"} else token)
    return _pipeline_groups(" ".join(tokens))


def _python_output_write(line: str) -> bool:
    return any(
        any(_write_path_writes(segment) for segment in group)
        and any(_has_python_source(segment) for segment in group)
        for group in _output_pipeline_groups(line)
    )


def opaque_source_findings(command: str, make_finding: FindingFactory) -> list[dict]:
    findings = [make_finding("opaque_source_write") for segment in _segments(command) if _dd_file_output(segment)]
    for line, _, _ in _logical_lines(command):
        if _python_output_write(line) or (has_process_substitution(line) and _line_is_mutating(line)):
            findings.append(make_finding("opaque_source_write"))
    return findings
