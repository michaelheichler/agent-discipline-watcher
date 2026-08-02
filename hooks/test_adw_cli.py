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
    assert "sample.md" in standalone.stdout
    assert "banned_dash [block]" in standalone.stdout


def test_standalone_json_output_and_search_work_in_subprocess(tmp_path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("needle context resolver\n", encoding="utf-8")

    report = _run(ADW_CLI, "review", "sample.py", "--format", "json", cwd=tmp_path)
    search = _run(ADW_CLI, "search", "context resolver", "sample.py", cwd=tmp_path)

    assert report.returncode == 0
    assert report.stdout.startswith('{"v":1,"s":')
    assert search.returncode == 0
    assert "\tcode\tsample.py:1\tneedle context resolver" in search.stdout


def test_install_script_links_both_commands() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert '"$HOME/.local/bin/agent-discipline"' in source
    assert '"$HOME/.local/bin/adw-cli"' in source
