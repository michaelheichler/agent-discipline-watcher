"""Terminal policy edits, because only the user may set policy."""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from . import config, configure_policy, configure_store, families, tests_policy

USAGE = "usage: adw-config status | tests allow|deny | tests allow --for 30m|2h | family NAME on|off"
SWITCHES = {"on": "enforce", "off": "off"}
WINDOW_CAP_SECONDS = 8 * 3600
UNIT_SECONDS = {"m": 60, "h": 3600}
_DURATION_RE = re.compile(r"^([1-9][0-9]*)([mh])$")


def _rule_names(settings: dict) -> list[str]:
    listed = set(config.DEFAULTS["rule_gates"]) | set(config.gate_map(settings, "rule_gates"))
    return sorted(listed)


def _changed_rules(settings: dict) -> list[str]:
    rows = []
    for rule in _rule_names(settings):
        state = config.rule_state(rule, settings)
        default = config.rule_state(rule)
        if state != default:
            rows.append(f"  {rule}: {state} (default {default})")
    return rows


def _window_line(settings: dict, now: float) -> str:
    left = tests_policy.window_seconds_left(settings, now)
    if not left:
        return "tests window: closed"
    return f"tests window: open, {left // 3600}h {left % 3600 // 60}m left"


def status_lines(target: Path, settings: dict, now: float) -> list[str]:
    """Show one file, because upward search can pick a parent."""
    present = "present" if target.exists() else "absent"
    tests = settings.get("tests", config.DEFAULTS["tests"])
    lines = [f"config: {target} ({present})", f"tests: {tests}", _window_line(settings, now), "families:"]
    for name in families.NAMES:
        state = config.gate_state(name, settings)
        lines.append(f"  {name}: {'off' if state == 'off' else 'on'} ({state})")
    changed = _changed_rules(settings)
    lines.append("rule gates changed from defaults:" if changed else "rule gates changed from defaults: none")
    return lines + changed


def window_seconds(text: str) -> int:
    """Capped, because a forgotten window must not stay open."""
    found = _DURATION_RE.match(text)
    if found is None:
        raise configure_policy.ConfigureError("invalid_value", "duration must look like 30m or 2h")
    seconds = int(found.group(1)) * UNIT_SECONDS[found.group(2)]
    if seconds > WINDOW_CAP_SECONDS:
        raise configure_policy.ConfigureError("invalid_value", "a tests window lasts at most 8h")
    return seconds


def _closed_window(settings: dict) -> dict[str, object]:
    """Skip an absent key, because clean files must stay clean."""
    return {tests_policy.WINDOW_KEY: 0} if tests_policy.WINDOW_KEY in settings else {}


def _requested_values(
    args: list[str], now: float, settings: dict,
) -> dict[str, object] | None:
    if len(args) == 4 and args[:3] == ["tests", "allow", "--for"]:
        return {tests_policy.WINDOW_KEY: int(now) + window_seconds(args[3])}
    if len(args) == 2 and args[0] == "tests":
        return {**configure_policy.validate_tests_policy(args[1]), **_closed_window(settings)}
    if len(args) == 3 and args[0] == "family" and args[1] in families.NAMES and args[2] in SWITCHES:
        return configure_policy.validate_policy_values({"gates": {args[1]: SWITCHES[args[2]]}})
    return None


def run(args: list[str], cwd: Path, now: float | None = None) -> int:
    """Exit 2 on bad usage, since a typo must not write policy."""
    clock = time.time() if now is None else now
    target = config.project_config_path(cwd)
    if args != ["status"]:
        current = configure_store.load(target)
        values = _requested_values(args, clock, current.settings)
        if values is None:
            print(USAGE, file=sys.stderr)
            return 2
        configure_store.write_values(target, values, current.digest)
    for line in status_lines(target, configure_store.load(target).settings, clock):
        print(line)
    return 0


def main() -> int:
    """Report a refused write plainly, since a trace hides it."""
    try:
        return run(sys.argv[1:], Path.cwd())
    except configure_policy.ConfigureError as exc:
        print(f"adw-config: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
