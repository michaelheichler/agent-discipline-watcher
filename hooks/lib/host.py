"""One detector for the running host, because a scattered env probe let two adapters claim one session."""
from __future__ import annotations

import os
from collections.abc import Mapping

CLAUDE = "claude"
CODEX = "codex"
OMP = "omp"
COWORK = "cowork"
SUPPORTED = (CLAUDE, CODEX, OMP, COWORK)

OMP_ENV = "OMPCODE"
CLAUDE_ENV = "CLAUDECODE"
CODEX_ENV = "ADW_CODEX_HOOK"
COWORK_ENV = "CLAUDE_CODE_IS_COWORK"


class UnknownHostError(RuntimeError):
    """Name the failure because a silent default would load an adapter that gates nothing."""


def _flag(environment: Mapping[str, str] | None, name: str) -> bool:
    env = os.environ if environment is None else environment
    return bool(env.get(name, "").strip())


def is_omp_host(environment: Mapping[str, str] | None = None) -> bool:
    """Read the OMP marker because that host must judge with its own models."""
    return _flag(environment, OMP_ENV)


def is_codex_host(environment: Mapping[str, str] | None = None) -> bool:
    """Read the bridge marker because Codex runs under a borrowed environment."""
    return _flag(environment, CODEX_ENV)


def is_cowork_host(environment: Mapping[str, str] | None = None) -> bool:
    """Split Cowork from Claude because its VM never reads the host home directory."""
    return _flag(environment, COWORK_ENV)


def is_claude_host(environment: Mapping[str, str] | None = None) -> bool:
    """Ignore the compat marker under OMP because OMP sets it too."""
    return _flag(environment, CLAUDE_ENV) and not is_omp_host(environment)


_ORDER = (
    (OMP, is_omp_host),
    (CODEX, is_codex_host),
    (COWORK, is_cowork_host),
    (CLAUDE, is_claude_host),
)


def current_host(environment: Mapping[str, str] | None = None) -> str:
    """Return one name because a runtime that loads two adapters gates each write twice."""
    for name, detect in _ORDER:
        if detect(environment):
            return name
    raise UnknownHostError("no supported host marker is present")
