from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TypedDict


class Outcome(StrEnum):
    """A StrEnum, because ledger rows are read back and compared as bare strings by consumers outside this process."""
    BLOCK = "block"
    INJECT = "inject"
    WOULD_BLOCK = "would_block"
    NO_EDITS = "no_edits"
    RELEASE = "release"


class VerdictKind(StrEnum):
    BLOCK = "block"
    OBSERVE = "observe"
    RELEASE = "release"


class _RequiredFindingDict(TypedDict):
    family: str
    rule: str
    line: int
    detail: str
    snippet: str
    action: str


class FindingDict(_RequiredFindingDict, total=False):
    force: bool
    path: str
    severity: str
    surface: str
    _tool_use_id: str
    content_hash: str
    match: str
    language: str
    end_line: int


_FINDING_KEYS = frozenset({
    "family", "rule", "line", "detail", "force", "snippet", "action",
    "path", "severity", "surface", "_tool_use_id",
    "content_hash", "match", "language", "end_line",
})
_REQUIRED_KEYS = frozenset(_RequiredFindingDict.__annotations__)
BLOCK_RULES = frozenset({
    "low_sentence_variance", "uniform_paragraph_endings", "oversized_list", "three_item_list",
    "choppy_sentences", "de_parataxis", "de_uniform_rhythm", "de_uniform_paragraphs",
    "de_repeated_connector", "de_exclamation_staccato", "dash_cluster",
    "prose_comment_block", "docstring_narration", "function_too_long", "hollow_test",
    "assert_in_loop", "if_statements_in_tests", "multiple_act_sections_in_unit_test",
})


@dataclass(frozen=True, slots=True)
class Rule:
    detail: str
    action: str

    def __post_init__(self) -> None:
        if not self.detail:
            raise ValueError("rule detail must not be empty")
        if not self.action:
            raise ValueError("rule action must not be empty")


@dataclass(frozen=True, slots=True)
class Finding:
    family: str
    rule: str
    line: int
    detail: str
    force: bool | None
    snippet: str
    action: str
    path: str | None
    severity: str | None
    tool_use_id: str | None
    content_hash: str | None = None
    surface: str | None = None
    match: str | None = None
    language: str | None = None
    end_line: int | None = None

    def __post_init__(self) -> None:
        if not self.family:
            raise ValueError("finding family must not be empty")
        if not self.rule:
            raise ValueError("finding rule must not be empty")
        if self.line < 1:
            raise ValueError("finding line must be at least 1")
        if self.end_line is not None and self.end_line < self.line:
            raise ValueError("finding end_line must not precede line")
        if not self.detail:
            raise ValueError("finding detail must not be empty")
        if not self.action:
            raise ValueError("finding action must not be empty")

    @classmethod
    def from_dict(cls, row: FindingDict) -> Finding:
        unexpected = set(row) - _FINDING_KEYS
        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise ValueError(f"finding has unsupported keys: {names}")
        try:
            return cls(
                family=row["family"],
                rule=row["rule"],
                line=row["line"],
                detail=row["detail"],
                force=row.get("force"),
                snippet=row["snippet"],
                action=row["action"],
                path=row.get("path"),
                severity=row.get("severity"),
                tool_use_id=row.get("_tool_use_id"),
                content_hash=row.get("content_hash"),
                surface=row.get("surface"),
                match=row.get("match"),
                language=row.get("language"),
                end_line=row.get("end_line"),
            )
        except KeyError as error:
            raise ValueError(f"finding is missing required key: {error.args[0]}") from error

    def with_detail(self, detail: str) -> Finding:
        return replace(self, detail=detail)

    def with_path(self, path: str) -> Finding:
        return replace(self, path=path)

    def with_tool_use_id(self, tool_use_id: str) -> Finding:
        return replace(self, tool_use_id=tool_use_id)

    def with_content_hash(self, content_hash: str) -> Finding:
        return replace(self, content_hash=content_hash)

    def with_end_line(self, end_line: int) -> Finding:
        return replace(self, end_line=end_line)

    def to_dict(self) -> dict:
        fields = (
            ("family", self.family), ("rule", self.rule), ("line", self.line),
            ("end_line", self.end_line), ("detail", self.detail), ("force", self.force),
            ("snippet", self.snippet), ("match", self.match), ("action", self.action),
            ("path", self.path), ("severity", self.severity), ("surface", self.surface),
            ("language", self.language), ("_tool_use_id", self.tool_use_id),
            ("content_hash", self.content_hash),
        )
        return {key: value for key, value in fields if value is not None or key in _REQUIRED_KEYS}


def spanning(row: dict, end_line: int | None) -> dict:
    """Strict, because provenance reads BLOCK_RULES to decide which findings skip match narrowing."""
    if row["rule"] not in BLOCK_RULES:
        raise ValueError("spanning finding names an undeclared block rule: " + row["rule"])
    return row if end_line is None else Finding.from_dict(row).with_end_line(end_line).to_dict()
