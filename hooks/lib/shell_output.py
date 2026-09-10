from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from lib.shell_parse import (
    PIPE_OPERATORS, SHELL_C_INTERPRETERS, WRAPPER_COMMANDS,
    _basename, _logical_lines, _payload_command_index,
    _skip_prefixes, _tokens, _write_path_writes, interpreter_invocation,
)

PYTHON_INTERPRETER_RE = re.compile(r"python(?:2|3)?(?:\.\d+)?$")
MAX_OUTPUT_GROUP_DEPTH = 64


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
    groups: list[OutputPipeline] = []
    group = OutputPipeline()
    stage = OutputStage()
    for token in tokens:
        command_start = not stage.tokens and not stage.groups
        if token == closing and (token == ")" or command_start):
            break
        if token == "(" or (token == "{" and command_start):
            stage.subshell = token == "("
            stage.groups = _output_token_groups(tokens, ")" if stage.subshell else "}", depth + 1)
        elif token in {";", "&&", "||", "&", *PIPE_OPERATORS}:
            if stage.tokens or stage.groups:
                group.stages.append(stage)
            stage = OutputStage()
            if token not in PIPE_OPERATORS and group.stages:
                group.background = token == "&"
                groups.append(group)
                group = OutputPipeline()
        else:
            stage.tokens.append(token)
    if stage.tokens or stage.groups:
        group.stages.append(stage)
    if group.stages:
        groups.append(group)
    return groups


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


def python_output_write(command: str) -> bool:
    try:
        return _python_group_output_write(_output_pipeline_groups(command))
    except OutputNestingError:
        return True


def _python_group_output_write(groups: list[OutputPipeline], incoming_python: bool = False) -> bool:
    file_output = False
    for group in groups:
        python_output = incoming_python
        for stage in group.stages:
            if _python_group_output_write(stage.groups, python_output):
                return True
            python_output = python_output or _has_python_source(stage)
            if python_output and (file_output or _write_path_writes(stage.tokens)):
                return True
        if not group.background and len(group.stages) == 1:
            file_output = file_output or _persistent_file_output(group.stages[0])
    return False
