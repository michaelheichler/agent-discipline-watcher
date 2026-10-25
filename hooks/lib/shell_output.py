from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from lib.shell_parse import (
    PIPE_OPERATORS, SHELL_C_INTERPRETERS, WRAPPER_COMMANDS,
    _bare, _basename, _logical_lines, _payload_command_index,
    _skip_prefixes, _tokens, _write_path_words, _write_path_writes, interpreter_invocation,
)
from lib.shell_syntax import _is_literal_token

PYTHON_INTERPRETER_RE = re.compile(r"python(?:2|3)?(?:\.\d+)?$")
MAX_OUTPUT_GROUP_DEPTH = 64
STAGE_SEPARATORS = frozenset({";", "&&", "||", "&", *PIPE_OPERATORS})
DATA_OUTPUT_EXTENSIONS = frozenset({".csv", ".json", ".jsonl", ".log", ".out", ".tsv", ".txt"})


@dataclass(slots=True)
class OutputStage:
    tokens: list[str] = field(default_factory=list)
    groups: list[OutputPipeline] = field(default_factory=list)
    subshell: bool = False


@dataclass(slots=True)
class OutputPipeline:
    stages: list[OutputStage] = field(default_factory=list)
    background: bool = False


class OutputNestingError(ValueError):
    pass


@dataclass(slots=True)
class _GroupBuilder:
    """Because a separator closes the open stage, the open pipeline, or both, the walk keeps them together."""

    depth: int
    groups: list[OutputPipeline] = field(default_factory=list)
    group: OutputPipeline = field(default_factory=OutputPipeline)
    stage: OutputStage = field(default_factory=OutputStage)

    def at_command_start(self) -> bool:
        return not self.stage.tokens and not self.stage.groups

    def take(self, token: str, tokens: Iterator[str]) -> None:
        if token == "(" or (token == "{" and self.at_command_start()):
            self.stage.subshell = token == "("
            self.stage.groups = _output_token_groups(tokens, ")" if self.stage.subshell else "}", self.depth + 1)
        elif token in STAGE_SEPARATORS:
            self._separate(token)
        else:
            self.stage.tokens.append(token)

    def _separate(self, token: str) -> None:
        self._close_stage()
        if token not in PIPE_OPERATORS:
            self._close_group(token == "&")

    def finish(self) -> list[OutputPipeline]:
        self._close_stage()
        self._close_group(False)
        return self.groups

    def _close_stage(self) -> None:
        if self.stage.tokens or self.stage.groups:
            self.group.stages.append(self.stage)
        self.stage = OutputStage()

    def _close_group(self, background: bool) -> None:
        if self.group.stages:
            self.group.background = background
            self.groups.append(self.group)
            self.group = OutputPipeline()


def _has_python_source(stage: OutputStage, depth: int = 0) -> bool:
    if any(_has_python_source(inner, depth) for group in stage.groups for inner in group.stages):
        return True
    segment = stage.tokens
    index = _payload_command_index(segment)
    if index < len(segment) and PYTHON_INTERPRETER_RE.fullmatch(_basename(segment[index])):
        return True
    invocation = interpreter_invocation(segment)
    if invocation is None or invocation.interpreter not in SHELL_C_INTERPRETERS:
        return False
    if depth >= 2 or invocation.payload is None:
        return True
    return any(_has_python_source(inner, depth + 1) for group in _output_pipeline_groups(invocation.payload) for inner in group.stages)


def _command_tokens(command: str) -> list[str]:
    tokens: list[str] = []
    for line, _, _ in _logical_lines(command):
        current = _tokens(line)
        if not current:
            continue
        if tokens and tokens[-1] not in {*PIPE_OPERATORS, "&&", "||"}:
            tokens.append(";")
        tokens.extend(current)
    return tokens


def _output_pipeline_groups(command: str) -> list[OutputPipeline]:
    return _output_token_groups(iter(_command_tokens(command)))


def _output_token_groups(tokens: Iterator[str], closing: str | None = None, depth: int = 0) -> list[OutputPipeline]:
    if depth >= MAX_OUTPUT_GROUP_DEPTH:
        raise OutputNestingError
    built = _GroupBuilder(depth)
    for token in tokens:
        if token == closing and (token == ")" or built.at_command_start()):
            break
        built.take(token, tokens)
    return built.finish()


def _persistent_file_output(stage: OutputStage) -> bool:
    index = _skip_prefixes(stage.tokens, WRAPPER_COMMANDS - {"exec"})
    if index < len(stage.tokens) and _basename(stage.tokens[index]) == "exec":
        return _payload_command_index(stage.tokens) == len(stage.tokens) and bool(_write_path_writes(stage.tokens))
    if stage.subshell:
        return False
    return any(
        not group.background and len(group.stages) == 1 and _persistent_file_output(group.stages[0])
        for group in stage.groups
    )


def _source_output(tokens: list[str]) -> bool:
    """A literal data file passes, because the post-run scan reads it like any redirect target and no gate reads it as code."""
    return any(not _data_output(word) for word, _append in _write_path_words(tokens))


def _data_output(raw: str) -> bool:
    return _is_literal_token(raw) and PurePosixPath(_bare(raw)).suffix.lower() in DATA_OUTPUT_EXTENSIONS


def python_output_write(command: str) -> bool:
    try:
        return _python_group_output_write(_output_pipeline_groups(command))
    except OutputNestingError:
        return True


def _python_group_output_write(groups: list[OutputPipeline], incoming_python: bool = False) -> bool:
    file_output = False
    for group in groups:
        if _python_stages_write(group.stages, incoming_python, file_output):
            return True
        if not group.background and len(group.stages) == 1:
            file_output = file_output or _persistent_file_output(group.stages[0])
    return False


def _python_stages_write(stages: list[OutputStage], python_output: bool, file_output: bool) -> bool:
    """Python output carries down the pipeline, because a later stage that writes a file stores what Python printed."""
    for stage in stages:
        if _python_group_output_write(stage.groups, python_output):
            return True
        python_output = python_output or _has_python_source(stage)
        if python_output and (file_output or _source_output(stage.tokens)):
            return True
    return False
