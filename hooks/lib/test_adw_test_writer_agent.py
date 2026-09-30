"""Guard the mission because a hand-edit would fork the source."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from install_runtime import install
from lib import adw_test_writer_agent as writer

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_PATH = ROOT / "agents" / "adw-test-writer.md"
CODEX_PATH = ROOT / "hosts" / "codex" / "agents" / "adw-test-writer.toml"
OMP_PATH = ROOT / "pi" / "extensions" / "agent-discipline-watcher" / "agents" / "adw-test-writer.md"


def _frontmatter(text: str) -> str:
    """Cut the block because the body is markdown, not YAML."""
    return text.split("---\n", 2)[1]


def _scalar(block: str, key: str) -> str:
    """Read one key because a test should check one field at a time."""
    for line in block.splitlines():
        if line.startswith(f"{key}:") and line.strip() != f"{key}:":
            return line.split(":", 1)[1].strip()
    return ""


def _list_items(block: str, key: str) -> list[str]:
    """Read one list because tools and autoloadSkills both use dashes."""
    lines = block.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"{key}:")
    items = []
    for line in lines[start + 1:]:
        if not line.startswith("  - "):
            break
        items.append(line[4:].strip())
    return items


def test_claude_agent_file_equals_the_render() -> None:
    """Compare bytes because a hand-edit would drift from the render."""
    assert CLAUDE_PATH.read_text(encoding="utf-8") == writer.render_claude_agent()


def test_codex_role_file_equals_the_render() -> None:
    """Compare bytes because a hand-edit would drift from the render."""
    assert CODEX_PATH.read_text(encoding="utf-8") == writer.render_codex_role()


def test_omp_agent_file_equals_the_render() -> None:
    """Compare bytes because a hand-edit would drift from the render."""
    assert OMP_PATH.read_text(encoding="utf-8") == writer.render_omp_agent()


def test_claude_frontmatter_parses_and_carries_required_keys() -> None:
    """Parse the block because a bad indent breaks Claude's loader."""
    block = _frontmatter(CLAUDE_PATH.read_text(encoding="utf-8"))
    for key in ("name", "description", "model", "effort"):
        assert _scalar(block, key), key


def test_omp_frontmatter_parses_and_grants_the_write_tool() -> None:
    """Parse the block because a bad indent breaks OMP's loader."""
    block = _frontmatter(OMP_PATH.read_text(encoding="utf-8"))
    assert "write" in _list_items(block, "tools")
    assert _list_items(block, "autoloadSkills")


def test_codex_role_parses_as_toml_with_the_reasoning_keys() -> None:
    """Parse with tomllib because a bad quote breaks Codex's loader."""
    parsed = tomllib.loads(CODEX_PATH.read_text(encoding="utf-8"))
    required = {"name", "description", "developer_instructions", "model", "model_reasoning_effort"}
    assert required <= parsed.keys()


def test_all_three_renders_carry_the_same_mission_text() -> None:
    """Compare the body because three renders must never fork the mission."""
    mission = writer.mission_text()
    assert mission in writer.render_claude_agent()
    assert mission in writer.render_codex_role()
    assert mission in writer.render_omp_agent()


def test_mission_steps_stay_numbered_from_one_in_order() -> None:
    """Check the prefixes because a reordered step misleads the reader."""
    prefixes = [line.split(".", 1)[0] for line in writer.mission_lines()]
    assert prefixes == [str(number) for number in range(1, len(prefixes) + 1)]


def _stub_skill_source(root: Path) -> Path:
    """Build a stub tree because the real skill file may not exist yet."""
    source = root / "source"
    stub_skill = source / writer.SKILL_PATH
    stub_skill.parent.mkdir(parents=True)
    stub_skill.write_text("stub skill for the fake install\n", encoding="utf-8")
    return source


def test_claude_names_a_skill_id_that_resolves_in_the_plugin_checkout(tmp_path: Path) -> None:
    """Check the plugin root because Claude reads the skill there, with no install step."""
    source = _stub_skill_source(tmp_path)
    assert (source / writer.SKILL_PATH).is_file()
    assert writer.CLAUDE_SKILL_ID == f"{writer.PLUGIN_NAME}:{writer.SKILL_NAME}"
    assert writer.CLAUDE_SKILL_ID in writer.render_claude_agent()


def test_codex_and_omp_name_a_path_that_exists_after_a_fake_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake-install a stub skill because a mission must name a real reading, not a guess."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    source = _stub_skill_source(tmp_path)
    install_dir = fake_home / ".adw" / "install" / writer.PLUGIN_NAME
    install(source, install_dir)

    installed_reading = Path(writer.INSTALLED_SKILL_PATH.replace("$HOME", str(fake_home)))
    assert installed_reading.is_file()
    assert writer.INSTALLED_SKILL_PATH in writer.render_codex_role()
    assert writer.INSTALLED_READ_FIRST_LINE in writer.render_omp_agent()
