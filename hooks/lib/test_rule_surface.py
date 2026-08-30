from __future__ import annotations

from lib.config import Outcome, SURFACE_ALL, effective_config, resolve_outcome, rule_state

RULE = "banned_adverb"


def _finding(surface: str | None = None) -> dict:
    finding = {"rule": RULE, "family": "english", "snippet": "actually"}
    return finding if surface is None else {**finding, "surface": surface}


def _config(gate: object) -> dict:
    return effective_config({"rule_gates": {RULE: gate}})


def test_a_flat_state_still_applies_to_every_surface() -> None:
    """Keep the old shape working because every shipped config writes a plain string."""
    cfg = _config("observe")

    assert resolve_outcome(_finding(), cfg) is Outcome.WOULD_BLOCK
    assert resolve_outcome(_finding("commit"), cfg) is Outcome.WOULD_BLOCK


def test_a_surface_map_applies_only_to_the_surface_it_names() -> None:
    """Split by surface because a rule measured on prose has no measurement on a commit body."""
    cfg = _config({"commit": "observe", SURFACE_ALL: "enforce"})

    assert resolve_outcome(_finding("commit"), cfg) is Outcome.WOULD_BLOCK
    assert resolve_outcome(_finding("prose"), cfg) is Outcome.BLOCK


def test_a_surface_map_without_a_match_falls_back_to_the_catch_all() -> None:
    """Fall back because naming one surface must not silence the rest."""
    cfg = _config({"commit": "off", SURFACE_ALL: "enforce"})

    assert resolve_outcome(_finding("prose"), cfg) is Outcome.BLOCK
    assert resolve_outcome(_finding(), cfg) is Outcome.BLOCK


def test_a_surface_map_with_no_catch_all_leaves_other_surfaces_to_the_family() -> None:
    """Defer to the family because an unnamed surface was never configured, not configured off."""
    cfg = _config({"commit": "off"})

    assert resolve_outcome(_finding("commit"), cfg) is Outcome.RELEASE
    assert resolve_outcome(_finding("prose"), cfg) is Outcome.BLOCK


def test_turning_a_rule_off_for_prose_reaches_an_untagged_finding() -> None:
    """Treat untagged as prose, because only the commit path tags and a prose rule set to off must obey."""
    cfg = _config({"prose": "off"})

    assert resolve_outcome(_finding(), cfg) is Outcome.RELEASE
    assert resolve_outcome(_finding("prose"), cfg) is Outcome.RELEASE


def test_a_surface_the_scanner_never_tags_is_refused_at_configure_time() -> None:
    """Refuse it because accepting a surface nothing produces lets a user configure nothing and see no error."""
    from lib.configure_policy import ConfigureError, _rule_gate_value

    try:
        _rule_gate_value(RULE, {"comment": "off"})
    except ConfigureError as error:
        assert "prose, commit, or all" in str(error)
    else:
        raise AssertionError("an unproduced surface must not validate")


def test_a_malformed_surface_value_is_ignored_rather_than_obeyed() -> None:
    """Ignore it because a typo must never read as a request to stop enforcing."""
    cfg = _config({"commit": "sometimes"})

    assert resolve_outcome(_finding("commit"), cfg) is Outcome.BLOCK


def test_an_always_blocking_rule_ignores_every_surface_map() -> None:
    """Block regardless because a per-surface map would otherwise be a new way to switch these off."""
    cfg = effective_config({"rule_gates": {"state_deletion": {"commit": "off", SURFACE_ALL: "off"}}})
    finding = {"rule": "state_deletion", "family": "self_protection", "surface": "commit"}

    assert resolve_outcome(finding, cfg) is Outcome.BLOCK


def test_a_commit_message_finding_carries_the_commit_surface() -> None:
    """Tag it at the source because resolve_outcome cannot infer a surface from a path alone."""
    import pre_commit

    command = 'git commit -m "Fix it" -m "This was actually broken by the change."'
    findings = pre_commit._message_findings(command, effective_config({}))

    assert findings
    assert {finding["surface"] for finding in findings} == {"commit"}


def test_the_shipped_defaults_still_block_a_commit_body() -> None:
    """Pin the default because adding a per-surface knob must not quietly loosen the gate."""
    import pre_commit

    command = 'git commit -m "Fix it" -m "This was actually broken by the change."'
    cfg = effective_config({})
    findings = pre_commit._message_findings(command, cfg)

    assert any(resolve_outcome(finding, cfg) is Outcome.BLOCK for finding in findings)


def test_rule_state_reports_the_surface_it_was_asked_about() -> None:
    """Answer per surface because the judged gate reads this to decide which rules to send."""
    cfg = {"rule_gates": {RULE: {"commit": "off", SURFACE_ALL: "judged"}}}

    assert rule_state(RULE, cfg, surface="commit") == "off"
    assert rule_state(RULE, cfg) == "judged"
