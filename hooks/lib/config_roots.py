"""One root list per host, kept out of the core because a host name there is how rulesets drift."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from .host import CLAUDE, CODEX, COWORK, OMP, current_host
except ImportError:
    from host import CLAUDE, CODEX, COWORK, OMP, current_host

STATE_ENV = "ADW_STATE_ROOT"
PLUGIN_ROOT_ENV = "CLAUDE_PLUGIN_ROOT"
DEFAULTS_LEAF = "defaults"
HOME_ROOT_HOSTS = (CLAUDE, CODEX, OMP)


def state_root(environment: dict[str, str] | None = None) -> Path:
    """Read the override first because a test must never touch the real home directory."""
    env = os.environ if environment is None else environment
    override = env.get(STATE_ENV, "").strip()
    return Path(override).expanduser() if override else Path.home() / ".adw"


def _home_roots(name: str, environment: dict[str, str] | None) -> tuple[Path, ...]:
    root = state_root(environment)
    return (root / "hosts" / name, root)


def _bundled_roots(environment: dict[str, str] | None) -> tuple[Path, ...]:
    env = os.environ if environment is None else environment
    plugin_root = env.get(PLUGIN_ROOT_ENV, "").strip()
    return (Path(plugin_root) / DEFAULTS_LEAF,) if plugin_root else ()


def roots_for(name: str, environment: dict[str, str] | None = None) -> tuple[Path, ...]:
    """Give Cowork the shipped copy because its VM never mounts the host home directory."""
    if name == COWORK:
        return _bundled_roots(environment)
    if name in HOME_ROOT_HOSTS:
        return _home_roots(name, environment)
    raise ValueError(f"no configuration roots declared for {name}")


def roots(environment: dict[str, str] | None = None) -> tuple[Path, ...]:
    """Resolve the host once because a runtime serves exactly one of them."""
    return roots_for(current_host(environment), environment)
