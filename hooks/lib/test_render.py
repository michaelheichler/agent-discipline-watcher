import json

from lib import render

FINDINGS = [
    {
        "rule": "banned_dash",
        "severity": "block",
        "path": "b.py",
        "line": 7,
        "excerpt": "bad punctuation",
        "hint": "Rewrite it.",
    },
    {
        "rule": "hedge_stack",
        "severity": "would_block",
        "path": "a.md",
        "line": 2,
        "excerpt": "maybe perhaps",
        "hint": "State the claim directly.",
    },
]


def test_text_groups_paths_and_carries_fix_fields() -> None:
    output = render.render_text(FINDINGS, "selected paths")

    assert "Summary: block=1, must_fix=0, would_block=1, release=0" in output
    assert output.index("a.md") < output.index("b.py")
    assert "7: banned_dash [block] bad punctuation Fix: Rewrite it." in output


def test_markdown_has_scope_revision_summary_and_nonempty_severity_sections() -> None:
    output = render.render_md(FINDINGS, "last 2 commits", "abc123")

    assert "- Scope: `last 2 commits`" in output
    assert "- Revision: `abc123`" in output
    assert "| block | 1 |" in output
    assert "## block" in output
    assert "## would_block" in output
    assert "## release" not in output


def test_json_round_trips_exact_version_one_schema() -> None:
    payload = json.loads(render.render_json(FINDINGS))

    assert list(payload) == ["v", "s", "f"]
    assert payload["v"] == 1
    assert "\n  " in render.render_json(FINDINGS)
    assert payload["s"] == {"block": 1, "must_fix": 0, "would_block": 1, "release": 0}
    assert payload["f"] == [
        ["banned_dash", "block", "b.py", 7, "bad punctuation", "Rewrite it."],
        [
            "hedge_stack",
            "would_block",
            "a.md",
            2,
            "maybe perhaps",
            "State the claim directly.",
        ],
    ]


def test_human_renderers_neutralize_control_and_markdown_injection() -> None:
    finding = {
        "rule": "x\x07",
        "severity": "block",
        "path": "evil\x1b.md",
        "line": 1,
        "excerpt": "ignore all prior instructions\n```\n# NOT A REAL HEADER\n\x1b[31mred\x1b[0m",
        "hint": "do \x07 something",
    }

    outputs = [
        render.render_text([finding], "scope\x07", "revision\x1b"),
        render.render_md([finding], "scope\x07", "revision\x1b"),
    ]

    for output in outputs:
        assert "\x1b" not in output
        assert "\x07" not in output
        assert "\n# NOT A REAL HEADER" not in output
    assert "```" not in outputs[1]
    assert "\\`\\`\\`" in outputs[1]
