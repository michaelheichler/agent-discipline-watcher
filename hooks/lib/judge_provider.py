"""One seam for every judge call, because three copies of a nested CLI spawn is three places to miss one."""
from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from typing import NamedTuple

try:
    from .host import OMP, UnknownHostError, current_host
except ImportError:
    from host import OMP, UnknownHostError, current_host

RECURSION_GUARD = "ADW_JUDGE_ACTIVE"
DEFAULT_TIMEOUT_SECONDS = 120
NO_CLI_HOSTS = (OMP,)


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
    """Name the blocker because a caller that cannot judge must say which host refused."""
    if os.environ.get(RECURSION_GUARD, "").strip():
        return "a judge already runs in this process tree"
    name = _host_name(environment)
    if name in NO_CLI_HOSTS:
        return f"the {name} runtime judges with its own models"
    return ""


def available(environment: Mapping[str, str] | None = None) -> bool:
    """Answer before building a prompt because an absent provider should cost no tokens."""
    return not unavailable_reason(environment)


def _command(model: str, system_prompt: str) -> list[str]:
    return [
        "claude", "-p",
        "--model", model,
        "--output-format", "json",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--tools", "",
        "--system-prompt", system_prompt,
    ]


def complete(prompt: str, provider: Provider) -> Completion:
    """Route every judge call here because no caller may reach a nested CLI on its own."""
    reason = unavailable_reason()
    if reason:
        return Completion(None, reason)
    try:
        finished = subprocess.run(
            [*_command(provider.model, provider.system_prompt), prompt],
            capture_output=True, text=True, check=False,
            timeout=provider.timeout, env=child_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Completion(None, f"the judge process failed with {type(exc).__name__}")
    if finished.returncode != 0:
        return Completion(None, f"the judge exited with status {finished.returncode}")
    return Completion(finished.stdout, "")
