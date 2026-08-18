import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADW_CLI = ROOT / "bin" / "adw-cli"
AGENT_DISCIPLINE = ROOT / "bin" / "agent-discipline"


def _run(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_both_review_entry_points_delegate_to_shared_engine(tmp_path) -> None:
    source = tmp_path / "sample.md"
    source.write_text("bad" + "\N{EM DASH}" + "line\n", encoding="utf-8")

    standalone = _run(ADW_CLI, "review", "sample.md", cwd=tmp_path)
    integrated = _run(AGENT_DISCIPLINE, "review", "sample.md", cwd=tmp_path)

    assert standalone.returncode == integrated.returncode == 1
    assert standalone.stdout == integrated.stdout
    assert json.loads(standalone.stdout)["s"]["block"] == 1
    assert "sample.md" in standalone.stdout


def test_standalone_json_output_and_search_work_in_subprocess(tmp_path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("needle context resolver\n", encoding="utf-8")

    report = _run(ADW_CLI, "review", "sample.py", "--format", "json", cwd=tmp_path)
    search = _run(ADW_CLI, "search", "context resolver", "sample.py", cwd=tmp_path)

    assert report.returncode == 0
    assert json.loads(report.stdout)["v"] == 1
    assert report.stdout.startswith("{\n")
    text_source = tmp_path / "sample.md"
    text_source.write_text("bad" + "\N{EM DASH}" + "line\n", encoding="utf-8")
    text_report = _run(ADW_CLI, "review", "sample.md", "--format", "text", cwd=tmp_path)
    assert text_report.returncode == 1
    assert "banned_dash [block]" in text_report.stdout

    assert search.returncode == 0
    assert "\tcode\tsample.py:1\tneedle context resolver" in search.stdout



def test_install_script_links_both_commands(tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    result = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "-y", "--no-claude", "--no-codex"],
        cwd=ROOT,
        env={**os.environ, "HOME": str(home)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    agent_discipline_link = home / ".local" / "bin" / "agent-discipline"
    adw_cli_link = home / ".local" / "bin" / "adw-cli"
    assert agent_discipline_link.resolve() == AGENT_DISCIPLINE.resolve()
    assert adw_cli_link.resolve() == ADW_CLI.resolve()
    rc_block = (home / ".zshrc").read_text(encoding="utf-8")
    assert "agent-discipline-watcher" in rc_block
    assert '$HOME/.agents/skills/agent-discipline-watcher/scripts/adw-completion.bash' in rc_block
    completion = ROOT / "scripts" / "adw-completion.bash"
    assert completion.exists()
    assert "adw-cli" in completion.read_text(encoding="utf-8")
