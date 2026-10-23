"""A Jinja minus is arithmetic, not a dash, because Home Assistant YAML holds templates beside the prose values ADW must still read."""
from __future__ import annotations

import pytest

from lib.scanner import scan_all

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _lines(text: str, rule: str, path: str = "automations.yaml") -> list[int]:
    return [row["line"] for row in scan_all(path, text, {}) if row["rule"] == rule]


@pytest.mark.parametrize("template", (
    pytest.param("{{ clear * (1 - 0.75 * cloud ** 3.4) }}", id="expression"),
    pytest.param("{% set x = a - b %}", id="statement"),
))
def test_a_minus_inside_a_jinja_template_is_not_a_spaced_hyphen(template: str) -> None:
    text = f"sensor:\n  state: >\n    {template}\n"

    assert _lines(text, "spaced_hyphen") == []


@pytest.mark.parametrize("text", (
    pytest.param("value: >\n  {{ clear *\n     (1 - 0.75 * cloud ** 3.4)\n  }}\n", id="expression"),
    pytest.param("value: >\n  {% set result =\n     clear * (1 - 0.75 * cloud ** 3.4)\n  %}\n", id="statement"),
))
def test_a_minus_inside_a_jinja_template_spanning_lines_is_not_a_spaced_hyphen(text: str) -> None:
    assert _lines(text, "spaced_hyphen") == []


@pytest.mark.parametrize(("text", "expected"), (
    pytest.param(
        "sensor:\n  state: >\n    {{ clear * (1 - 0.75 * cloud ** 3.4) }}\n  message: First - next\n",
        [4],
        id="template-and-prose-on-separate-lines",
    ),
    pytest.param(
        "notify:\n  message: >\n    Heating at {{ 100 - loss }} percent - check the boiler\n",
        [3],
        id="template-and-prose-on-one-line",
    ),
    pytest.param(
        "state: >\n  {{ x\n     - y }} plain - prose\n",
        [3],
        id="prose-after-a-template-spanning-lines",
    ),
))
def test_a_prose_value_beside_a_jinja_template_still_flags_its_spaced_hyphen(text: str, expected: list[int]) -> None:
    assert _lines(text, "spaced_hyphen") == expected


def test_a_spaced_hyphen_in_a_plain_config_value_is_flagged() -> None:
    assert _lines("message: First - next\n", "spaced_hyphen") == [1]


@pytest.mark.parametrize(("text", "expected"), (
    pytest.param(f"state: >\n  {{{{ x {EM_DASH} y }}}}\n", [2], id="one-line-template"),
    pytest.param(f"state: >\n  {{{{ x\n     {EM_DASH} y }}}}\n", [3], id="template-spanning-lines"),
))
def test_a_banned_dash_inside_a_jinja_template_is_still_reported(text: str, expected: list[int]) -> None:
    assert _lines(text, "banned_dash") == expected


@pytest.mark.parametrize("text", (
    pytest.param(f'value: "{{{{ a {EM_DASH} b }}}}"\n', id="quoted-template"),
    pytest.param(f'message: "Fenster offen {EM_DASH} bitte schließen"\n', id="quoted-message"),
))
def test_a_banned_dash_inside_a_quoted_config_value_is_reported(text: str) -> None:
    assert _lines(text, "banned_dash") == [1]


@pytest.mark.parametrize("text", (
    pytest.param(f'glyphs: ["0123456789{EN_DASH}"]\n', id="digits-then-dash"),
    pytest.param(f'glyphs: ["0123456789.-{EN_DASH} Ug"]\n', id="digits-symbols-dash-letters"),
))
def test_a_dash_listed_as_a_font_glyph_in_a_quoted_config_value_is_not_reported(text: str) -> None:
    assert _lines(text, "banned_dash") == []


def test_a_quoted_config_value_without_a_dash_stays_clean() -> None:
    assert scan_all("automations.yaml", 'message: "Fenster offen, bitte schließen"\n', {}) == []


def test_a_banned_dash_quoted_in_markdown_prose_stays_unreported() -> None:
    text = f'He said "the window is open {EM_DASH} please close it" and left.\n'

    assert _lines(text, "banned_dash", path="doc.md") == []
