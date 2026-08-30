"""One seam for every judge call, because three copies of a spawn is three places to miss one."""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import NamedTuple

try:
    from .host import OMP, UnknownHostError, current_host
except ImportError:
    from host import OMP, UnknownHostError, current_host

RECURSION_GUARD = "ADW_JUDGE_ACTIVE"
DEFAULT_TIMEOUT_SECONDS = 120
SELF_JUDGING_HOSTS = (OMP,)
NO_PYTHON_PROVIDER = (
    "python holds no judge provider, because the host agent hook judges instead"
)


class Completion(NamedTuple):
    """Carry the reason beside the text because an empty result must never read as a clean verdict."""

    text: str | None
    reason: str


class Provider(NamedTuple):
    """Bundle the settings because one judge answers many prompts under one configuration."""

    model: str
    system_prompt: str
    timeout: float = DEFAULT_TIMEOUT_SECONDS


def child_environment() -> dict[str, str]:
    """Drop the API key because the session login is the account the user already chose to spend."""
    env = {key: value for key, value in os.environ.items() if key != "ANTHROPIC_API_KEY"}
    env[RECURSION_GUARD] = "1"
    return env


def _host_name(environment: Mapping[str, str] | None) -> str | None:
    try:
        return current_host(environment)
    except UnknownHostError:
        return None


def unavailable_reason(environment: Mapping[str, str] | None = None) -> str:
    """Name the blocker because a caller that cannot judge must say why rather than report a clean file."""
    if os.environ.get(RECURSION_GUARD, "").strip():
        return "a judge already runs in this process tree"
    name = _host_name(environment)
    if name in SELF_JUDGING_HOSTS:
        return f"the {name} runtime judges with its own models"
    return NO_PYTHON_PROVIDER


def available(environment: Mapping[str, str] | None = None) -> bool:
    """Answer before building a prompt because an absent provider should cost no tokens."""
    return not unavailable_reason(environment)


def complete(_prompt: str, _provider: Provider) -> Completion:
    """Kept as the one seam three callers already import, because a spawn added anywhere else bills the user's account."""
    return Completion(None, unavailable_reason())
