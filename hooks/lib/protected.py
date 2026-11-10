"""Hard-blocked here because an agent that can edit its own watcher's live config or install can also disable the watcher."""
from __future__ import annotations

import json
import os
import re
import stat
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path

try:
    from . import config_roots as config_paths
except ImportError:
    import config_roots as config_paths

try:
    # Because lib.protected cannot resolve bare imports.
    from . import families
    from .config import ALWAYS_BLOCKING_RULES, flatten_settings
    from .findings import finding_row
    from .payloads import exact_string_dict
    from .regular_file import read_regular_text
except ImportError:
    import families
    from config import ALWAYS_BLOCKING_RULES, flatten_settings
    from findings import finding_row
    from payloads import exact_string_dict
    from regular_file import read_regular_text

CONFIG_SEAL_BASENAME = ".agent-discipline.json"
TESTS_POLICY_KEYS = ("tests", "tests_allow_until")
TEST_WRITER_STEM = "adw-test-writer"
AGENT_FILE_SUFFIXES = frozenset({".md", ".toml"})
AUTH_ENV = "ADW_ALLOW_PROTECTED_EDIT"
AUTH_SETTING = "protected_paths_authorized"
TRUTHY = frozenset({"1", "true", "yes", "on"})

WATCHER_NAME_PREFIX = "agent-discipline"
# Because same-name working checkouts must stay editable.
CLIENT_HOME_DIRS = frozenset({".claude", ".codex", ".pi", ".omp", ".agents", ".config", ".local"})
# Because only host files wired by install.sh or pi/install.sh can unwire ADW.
WIRING_FILES = frozenset({
    (".claude", "settings.json"),
    (".claude", "settings.local.json"),
    (".codex", "config.toml"),
    (".codex", "hooks.json"),
    (".pi", "agent", "settings.json"),
    (".omp", "agent", "settings.json"),
})
# Because JSON and TOML wiring both name ADW or its hook runner.
WATCHER_WIRING_RE = re.compile(r"agent-discipline|/hooks/run\.sh")
# Per line, so that an edit fragment matches like a whole file.
TEST_WRITER_NAME_RE = re.compile(
    r"""^\s*["']?name["']?\s*[:=]\s*["']?adw-test-writer["']?\s*(?:#.*)?$""",
    re.IGNORECASE | re.MULTILINE,
)

INSTALL_ACTION = (
    "Change the repo source and reinstall instead of editing the live install. If this edit "
    "is intentional, ask the human to export "
    + AUTH_ENV
    + " in the hook environment, which releases every self-protection rule, not just this one."
)
WIRING_ACTION = (
    "Keep the agent-discipline-watcher hook entries in place. Edit this file around them, "
    "or reinstall to change how the watcher is wired."
)
SEAL_ACTION = "Fix the reported finding instead of changing the gate config."
POLICY_ACTION = "The user sets this policy. Ask the human to run adw-config in a terminal."
STATE_ACTION = "Leave watcher state under host control and repair the reported finding."
DEFINITION_ACTION = (
    "The test gate trusts this agent file, so the user owns it. Ask the human to edit it in a terminal."
)
SWITCH_ACTION = (
    "Keep the watcher plugin enabled, its hooks on, and the escape variable out of these "
    "settings. Ask the human to make this change in a terminal."
)
GRANT_ACTION = (
    "The config key no longer grants anything. Ask the human to export "
    + AUTH_ENV
    + " in the hook environment, which is the only supported escape."
)


@dataclass(frozen=True, slots=True)
class ProtectedWrite:
    path: str
    home: str | os.PathLike[str] | None
    content: str | None


@dataclass(frozen=True, slots=True)
class ResolvedProtectedWrite:
    resolved: Path
    requested: ProtectedWrite


class UnresolvableTildePath(ValueError):
    """Raised when a ~user token cannot be expanded, since the target cannot be verified as safe."""


def _env_authorized() -> bool:
    return os.environ.get(AUTH_ENV, "").strip().lower() in TRUTHY


def authorized(config: dict | None = None) -> bool:
    """Return whether a human granted the escape. The config argument is inert because a config file is a file the agent can write."""
    del config
    return _env_authorized()


def grants_escape(text: str | None) -> bool:
    """Checked because a rule kill switch or self-authorization key written to the gate config would let an agent turn off its own hard blocks."""
    if not text:
        return False
    try:
        settings = flatten_settings(json.loads(text))
    except (ValueError, TypeError):
        return False
    if settings.get(AUTH_SETTING):
        return True
    gates = exact_string_dict(settings.get("rule_gates"))
    if any(rule in ALWAYS_BLOCKING_RULES and state != "enforce" for rule, state in gates.items()):
        return True
    if "state_root" in settings or "ledger_root" in settings:
        return True
    return _silences_every_family(settings)


UNIVERSAL_GLOBS = frozenset({"*", "**", "*/*", "**/*", "*/**", "**/**", "/**", "./**"})


def _silences_every_family(settings: dict) -> bool:
    return (
        _gated_off_everywhere(settings)
        or _killed_everywhere(settings)
        or _exempted_everywhere(settings)
    )


def _gated_off(settings: dict, family_gates: dict, leaf: str) -> bool:
    names = families.scope(leaf)
    for name in names:
        if name in family_gates:
            return family_gates[name] != "enforce"
    return any(settings.get(name) is False for name in names)


def _gated_off_everywhere(settings: dict) -> bool:
    family_gates = exact_string_dict(settings.get("gates"))
    return all(_gated_off(settings, family_gates, leaf) for leaf in families.LEAVES)


def _killed_everywhere(settings: dict) -> bool:
    switches = exact_string_dict(settings.get("kill_switches"))
    return all(
        any(bool(switches.get(name)) for name in families.scope(leaf)) for leaf in families.LEAVES
    )


def _exempted_everywhere(settings: dict) -> bool:
    paths = settings.get("exempt_paths")
    if isinstance(paths, list) and any(
        isinstance(entry, str) and entry.strip() in UNIVERSAL_GLOBS for entry in paths
    ):
        return True
    exemptions = exact_string_dict(settings.get("exempt_families"))
    for glob, listed in exemptions.items():
        if glob.strip() not in UNIVERSAL_GLOBS or not isinstance(listed, list):
            continue
        named = (entry for entry in listed if isinstance(entry, str))
        if families.leaves_of(named) == frozenset(families.LEAVES):
            return True
    return False


def _protected_write(path: str, values: tuple[object, ...], fields: dict[str, object]) -> ProtectedWrite:
    if len(values) > 3:
        raise TypeError("path_findings accepts at most four legacy arguments")
    names = ("config", "home", "content")
    legacy = dict(zip(names, values, strict=False))
    for name, value in fields.items():
        if name not in names or name in legacy:
            raise TypeError(f"path_findings got an invalid keyword: {name}")
        legacy[name] = value
    home = legacy.get("home")
    content = legacy.get("content")
    if home is not None and not isinstance(home, (str, os.PathLike)):
        raise TypeError("path_findings home must be a path or None")
    if content is not None and not isinstance(content, str):
        raise TypeError("path_findings content must be a string or None")
    return ProtectedWrite(path, home, content)


def path_findings(write: ProtectedWrite | str, *values: object, **fields: object) -> list[dict]:
    """Return blocking findings for a pending write target, with config inert because only the environment can release these rules."""
    if isinstance(write, str):
        write = _protected_write(write, values, fields)
    elif values or fields:
        raise TypeError("ProtectedWrite cannot be combined with legacy arguments")
    if not write.path or write.path == "<pending>":
        return []
    try:
        resolved = _resolve(write.path, write.home)
    except UnresolvableTildePath:
        if _env_authorized():
            return []
        return [finding_row(family="self_protection", rule="watcher_install_surface", line=1, detail="Unresolvable ~user path in " + write.path, snippet=write.path.strip()[:180], action=INSTALL_ACTION)]
    if resolved is None or _env_authorized():
        return []
    return _resolved_findings(write, resolved) or _hardlink_findings(write, resolved)


def _resolved_findings(write: ProtectedWrite, resolved: Path) -> list[dict]:
    return (
        _definition_findings(write, resolved)
        or _switch_off_findings(write, resolved)
        or _write_target_findings(ResolvedProtectedWrite(resolved, write))
    )


def _hardlink_findings(write: ProtectedWrite, resolved: Path) -> list[dict]:
    """Compare identities because realpath cannot expose a hard-link alias."""
    try:
        metadata = resolved.stat()
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError:
        return _identity_refusal(write)
    if metadata.st_nlink < 2 or not stat.S_ISREG(metadata.st_mode):
        return []
    identity = (metadata.st_dev, metadata.st_ino)
    try:
        if TEST_WRITER_NAME_RE.search(write.content or "") or TEST_WRITER_NAME_RE.search(read_regular_text(resolved, errors="replace")):
            return [finding_row(family="self_protection", rule="test_writer_definition", line=1, detail="Test writer definition in " + write.path, snippet=write.path.strip()[:180], action=DEFINITION_ACTION)]
        home = config_paths.home_root(write.home)
        candidates = _protected_identities(home, _identity_stamp(home)).get(identity, ())
        candidates = (*candidates, *_seal_aliases(resolved, identity))
    except OSError:
        return _identity_refusal(write)
    return _alias_findings(write, resolved, candidates)


def _identity_refusal(write: ProtectedWrite) -> list[dict]:
    """Block uncertainty because an unreadable protected file may share the target inode."""
    return [finding_row(family="self_protection", rule="watcher_install_surface", line=1, detail="Cannot verify protected identity for " + write.path, snippet=write.path.strip()[:180], action=INSTALL_ACTION)]


def _alias_findings(write: ProtectedWrite, resolved: Path, candidates: tuple[Path, ...]) -> list[dict]:
    for candidate in candidates:
        # Because filesystem names can contain literal tildes.
        normalized = Path(os.path.realpath(candidate))
        if normalized == resolved:
            continue
        alias = ProtectedWrite(str(candidate), write.home, write.content)
        findings = _resolved_findings(alias, normalized)
        if findings:
            return findings
    return []


def _seal_aliases(target: Path, identity: tuple[int, int]) -> tuple[Path, ...]:
    candidates = []
    for parent in set((*target.parents, Path.cwd(), *Path.cwd().parents)):
        candidate = parent / CONFIG_SEAL_BASENAME
        metadata = _existing_metadata(candidate)
        if metadata is not None and (metadata.st_dev, metadata.st_ino) == identity:
            candidates.append(candidate)
    return tuple(candidates)


def _existing_metadata(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return None


def _identity_stamp(home: Path) -> tuple[tuple[int, ...] | None, ...]:
    stamps = []
    roots = (*_protected_roots(home), *(home.joinpath(*parts) for parts in WIRING_FILES))
    for root in roots:
        metadata = _existing_metadata(root)
        stamps.append(None if metadata is None else (
            metadata.st_dev, metadata.st_ino, metadata.st_mtime_ns, metadata.st_ctime_ns,
        ))
    return tuple(stamps)


@lru_cache(maxsize=16)
def _protected_identities(home: Path, stamp: tuple) -> dict[tuple[int, int], tuple[Path, ...]]:
    """Cache stable roots because each payload may name several aliases."""
    del stamp
    identities: dict[tuple[int, int], tuple[Path, ...]] = {}
    for candidate in _protected_candidates(home):
        metadata = _existing_metadata(candidate)
        if metadata is None or metadata.st_nlink < 2 or not stat.S_ISREG(metadata.st_mode):
            continue
        identity = (metadata.st_dev, metadata.st_ino)
        identities[identity] = (*identities.get(identity, ()), candidate)
    return identities


def _protected_candidates(home: Path):
    """Inspect ADW-owned trees because unrelated directories cannot contain owned state."""
    yield from (home.joinpath(*parts) for parts in WIRING_FILES)
    for client in CLIENT_HOME_DIRS:
        for directory in (home / client / "agents", home / client / "agent" / "agents"):
            yield from _agent_candidates(directory)
    for root in _protected_roots(home):
        yield from _owned_candidates(root)


def _agent_candidates(directory: Path):
    try:
        entries = tuple(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.suffix.lower() in AGENT_FILE_SUFFIXES and not entry.is_symlink():
            yield entry


def _protected_roots(home: Path) -> tuple[Path, ...]:
    roots = [config_paths.data_root(home), home / ".agent-discipline", config_paths.install_root(home)]
    for client in (".claude", ".config/claude-code"):
        base = home / client
        roots.extend(base / relative for relative in (
            "plugins/cache/agent-discipline-watcher",
            "plugins/marketplaces/agent-discipline-watcher",
            "plugins/agent-discipline-watcher",
            "skills/agent-discipline-watcher",
        ))
    roots.extend(home / relative for relative in (
        ".codex/skills/agent-discipline-watcher",
        ".agents/skills/agent-discipline-watcher",
        ".pi/agent/extensions/agent-discipline-watcher",
        ".omp/agent/extensions/agent-discipline-watcher",
        ".local/bin/agent-discipline",
    ))
    return tuple(roots)


def _owned_candidates(root: Path):
    metadata = _existing_metadata(root)
    if metadata is None:
        return
    if stat.S_ISREG(metadata.st_mode):
        yield root
        return
    for directory, children, files in os.walk(root, followlinks=False, onerror=_walk_error):
        parent = Path(directory)
        children[:] = [name for name in children if not (parent / name).is_symlink()]
        for name in files:
            candidate = parent / name
            if not candidate.is_symlink():
                yield candidate


def _walk_error(error: OSError) -> None:
    """Fail closed because an unreadable owned subtree can hide an alias source."""
    if not isinstance(error, (FileNotFoundError, NotADirectoryError)):
        raise error


def _definition_findings(write: ProtectedWrite, resolved: Path) -> list[dict]:
    """Both routes, because a symlink can hide the agent file."""
    literal = _literal(write.path, write.home)
    if not (_is_test_writer_definition(literal, write.content) or _is_test_writer_definition(resolved, write.content)):
        return []
    return [finding_row(family="self_protection", rule="test_writer_definition", line=1, detail="Test writer definition in " + write.path, snippet=write.path.strip()[:180], action=DEFINITION_ACTION)]


def _switch_off_findings(write: ProtectedWrite, resolved: Path) -> list[dict]:
    if not _switches_watcher_off((_literal(write.path, write.home), resolved), write.content):
        return []
    return [finding_row(family="self_protection", rule="watcher_wiring_removal", line=1, detail="Write switches the watcher off in " + write.path, snippet=write.path.strip()[:180], action=SWITCH_ACTION)]


def _write_target_findings(write: ResolvedProtectedWrite) -> list[dict]:
    resolved = write.resolved
    path = write.requested.path
    home = write.requested.home
    content = write.requested.content
    if _is_gate_config(resolved) and grants_escape(content):
        return [finding_row(family="self_protection", rule="config_seal", line=1, detail="Self-granted gate escape in " + path, snippet=path.strip()[:180], action=GRANT_ACTION)]
    if _is_gate_config(resolved) and _changes_tests_policy(resolved, content):
        return [finding_row(family="self_protection", rule="config_seal", line=1, detail="Tests policy edit in " + path, snippet=path.strip()[:180], action=POLICY_ACTION)]
    if _is_state_path(resolved, home):
        return [finding_row(family="self_protection", rule="state_mutation", line=1, detail="Watcher state path in " + path, snippet=path.strip()[:180], action=STATE_ACTION)]
    if _reaches_install_surface(_literal(path, home), resolved, home):
        return [finding_row(family="self_protection", rule="watcher_install_surface", line=1, detail="Live watcher install path in " + path, snippet=path.strip()[:180], action=INSTALL_ACTION)]
    # Because filesystem names can contain literal tildes.
    if _unwires_watcher(resolved, Path(os.path.realpath(config_paths.home_root(home))), content):
        return [finding_row(family="self_protection", rule="watcher_wiring_removal", line=1, detail="Write drops the watcher hooks from " + path, snippet=path.strip()[:180], action=WIRING_ACTION)]
    return (
        [finding_row(family="self_protection", rule="config_seal", line=1, detail="Gate config edit in " + path, snippet=path.strip()[:180], action=SEAL_ACTION)]
        if _is_unreadable_config_write(resolved, content)
        else []
    )


def is_install_surface_path(
    path: str,
    home: str | os.PathLike[str] | None = None,
) -> bool:
    """Needed because the Bash gate only has a raw command string, not a parsed tool_input path, so it must resolve install paths from text instead."""
    try:
        literal = _literal(path, home)
        resolved = _resolve(path, home)
    except UnresolvableTildePath:
        return True
    if resolved is None:
        return False
    return _reaches_install_surface(literal, resolved, home)


def _literal(path: str, home: str | os.PathLike[str] | None) -> Path | None:
    """Expanded but not resolved, because the install rule reads the route the human typed rather than the checkout a symlink points at."""
    try:
        candidate = Path(path)
    except (TypeError, ValueError):
        return None
    text = str(candidate)
    if text == "~" or text.startswith("~/"):
        candidate = config_paths.home_relative(text, home)
    elif text.startswith("~"):
        candidate = _expand_other_user(text)
    if not candidate.is_absolute():
        candidate = Path(os.getcwd()) / candidate
    return candidate


def _resolve(path: str, home: str | os.PathLike[str] | None) -> Path | None:
    candidate = _literal(path, home)
    # Because filesystem names can contain literal tildes.
    return None if candidate is None else Path(os.path.realpath(candidate))


def _expand_other_user(text: str) -> Path:
    expanded = os.path.expanduser(text)
    if expanded == text:
        raise UnresolvableTildePath(text)
    return Path(expanded)


def _relative_parts(path: Path, home: Path) -> list[str] | None:
    try:
        relative = path.relative_to(home)
    except ValueError:
        return None
    return [part.lower() for part in relative.parts]


def _reaches_install_surface(literal: Path | None, resolved: Path, home: str | os.PathLike[str] | None) -> bool:
    """Judged on the typed route as well as the resolved one, because every install is a symlink whose target is the checkout the human still has to edit, while a symlink aimed into an install must not slip past."""
    if literal is not None and _is_install_surface(literal, config_paths.home_root(home)):
        return True
    # Because filesystem names can contain literal tildes.
    return _is_install_surface(resolved, Path(os.path.realpath(config_paths.home_root(home))))


def _is_install_surface(path: Path, home: Path) -> bool:
    parts = _relative_parts(path, home)
    if not parts or parts[0] not in CLIENT_HOME_DIRS:
        return False
    return any(part.startswith(WATCHER_NAME_PREFIX) for part in parts[1:])


def _unwires_watcher(resolved: Path, home: Path, content: str | None) -> bool:
    """Judged by content rather than by path, because these files also carry host settings the agent is entitled to change."""
    parts = _relative_parts(resolved, home)
    if parts is None or tuple(parts) not in WIRING_FILES:
        return False
    if not _has_watcher_wiring(resolved):
        return False
    return content is None or not WATCHER_WIRING_RE.search(content)


def _is_claude_settings(path: Path | None) -> bool:
    if path is None:
        return False
    name = path.name.lower()
    return path.parent.name.lower() == ".claude" and name.startswith("settings") and name.endswith(".json")


def _switches_watcher_off(paths: tuple[Path | None, Path], content: str | None) -> bool:
    """Parsed, because the plugin name survives a false toggle."""
    if not content or not any(_is_claude_settings(path) for path in paths):
        return False
    try:
        settings = json.loads(content)
    except ValueError:
        return False
    if not isinstance(settings, dict):
        return False
    if settings.get("disableAllHooks") not in (None, False):
        return True
    env = settings.get("env")
    if isinstance(env, dict) and AUTH_ENV in env:
        return True
    plugins = settings.get("enabledPlugins")
    return isinstance(plugins, dict) and any(
        key.lower().startswith(WATCHER_NAME_PREFIX) and value is not True
        for key, value in plugins.items()
    )


def _has_watcher_wiring(path: Path) -> bool:
    """Because unreadable wiring cannot clear a write, treat it as wired."""
    try:
        return bool(WATCHER_WIRING_RE.search(read_regular_text(path)))
    except FileNotFoundError:
        return False
    except (OSError, UnicodeDecodeError):
        return True


def _tests_value(text: str | None) -> object:
    try:
        settings = flatten_settings(json.loads(text or "{}"))
    except (ValueError, TypeError):
        return None
    return tuple(settings.get(key) for key in TESTS_POLICY_KEYS)


def _changes_tests_policy(path: Path, content: str | None) -> bool:
    """Compared to disk, because allow and deny are both user calls."""
    if content is None:
        return False
    try:
        current = read_regular_text(path)
    except FileNotFoundError:
        current = None
    except (OSError, UnicodeDecodeError):
        return True
    return _tests_value(content) != _tests_value(current)


def _is_test_writer_definition(path: Path | None, content: str | None) -> bool:
    """By name too, because hosts read the name from the file."""
    if path is None or path.suffix.lower() not in AGENT_FILE_SUFFIXES:
        return False
    if not any(part.lower() == "agents" for part in path.parent.parts):
        return False
    if path.stem.lower() == TEST_WRITER_STEM or TEST_WRITER_NAME_RE.search(content or ""):
        return True
    return _declares_test_writer_on_disk(path)


def _declares_test_writer_on_disk(path: Path) -> bool:
    """Unreadable counts as declared, since it cannot be cleared."""
    try:
        return bool(TEST_WRITER_NAME_RE.search(read_regular_text(path)))
    except (FileNotFoundError, NotADirectoryError):
        return False
    except (OSError, UnicodeDecodeError):
        return True


def _is_gate_config(path: Path) -> bool:
    return path.name.lower() == CONFIG_SEAL_BASENAME


def _is_state_path(path: Path, home: str | os.PathLike[str] | None) -> bool:
    """Because unmigrated machines keep state there, the legacy root stays guarded."""
    base = config_paths.home_root(home)
    for root in (base / ".adw", base / ".agent-discipline"):
        try:
            # Because filesystem names can contain literal tildes.
            path.relative_to(Path(os.path.realpath(root)))
        except ValueError:
            continue
        return True
    return False


def _is_unreadable_config_write(path: Path, content: str | None) -> bool:
    """Fails closed on an unreadable body against an existing config because it could carry any escape, while a readable benign edit stays the human's to make."""
    if not _is_gate_config(path) or (content is not None and content.strip()):
        return False
    try:
        return path.exists()
    except OSError:
        return True
