"""Terminal policy edits, because only the user may set policy."""
from __future__ import annotations

import sys
from pathlib import Path

from . import config, configure_policy, configure_store, families

USAGE = "usage: adw-config status | tests allow|deny | family NAME on|off"
SWITCHES = {"on": "enforce", "off": "off"}


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


def status_lines(target: Path, settings: dict) -> list[str]:
    """Show one file, because upward search can pick a parent."""
    present = "present" if target.exists() else "absent"
    lines = [f"config: {target} ({present})", f"tests: {settings.get('tests', config.DEFAULTS['tests'])}", "families:"]
    for name in families.NAMES:
        state = config.gate_state(name, settings)
        lines.append(f"  {name}: {'off' if state == 'off' else 'on'} ({state})")
    changed = _changed_rules(settings)
    lines.append("rule gates changed from defaults:" if changed else "rule gates changed from defaults: none")
    return lines + changed


def _requested_values(args: list[str]) -> dict[str, object] | None:
    if len(args) == 2 and args[0] == "tests":
        return configure_policy.validate_tests_policy(args[1])
    if len(args) == 3 and args[0] == "family" and args[1] in families.NAMES and args[2] in SWITCHES:
        return configure_policy.validate_policy_values({"gates": {args[1]: SWITCHES[args[2]]}})
    return None


def run(args: list[str], cwd: Path) -> int:
    """Exit 2 on bad usage, since a typo must not write policy."""
    target = config.project_config_path(cwd)
    if args != ["status"]:
        values = _requested_values(args)
        if values is None:
            print(USAGE, file=sys.stderr)
            return 2
        configure_store.write_values(target, values, configure_store.load(target).digest)
    for line in status_lines(target, configure_store.load(target).settings):
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
