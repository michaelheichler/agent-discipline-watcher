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


_FINDING_KEYS = frozenset({
    "family", "rule", "line", "detail", "force", "snippet", "action",
    "path", "severity", "surface", "_tool_use_id",
    "content_hash",
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

    def __post_init__(self) -> None:
        if not self.family:
            raise ValueError("finding family must not be empty")
        if not self.rule:
            raise ValueError("finding rule must not be empty")
        if self.line < 1:
            raise ValueError("finding line must be at least 1")
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

    def to_dict(self) -> dict:
        row: dict = {
            "family": self.family,
            "rule": self.rule,
            "line": self.line,
            "detail": self.detail,
        }
        if self.force is not None:
            row["force"] = self.force
        row["snippet"] = self.snippet
        row["action"] = self.action
        if self.path is not None:
            row["path"] = self.path
        if self.severity is not None:
            row["severity"] = self.severity
        if self.surface is not None:
            row["surface"] = self.surface
        if self.tool_use_id is not None:
            row["_tool_use_id"] = self.tool_use_id
        if self.content_hash is not None:
            row["content_hash"] = self.content_hash
        return row
