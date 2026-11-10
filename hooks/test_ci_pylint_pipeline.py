"""Propagate lint failures because a rounded score cannot override the linter's exit status."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import yaml


WORKFLOW = Path(__file__).resolve().parent.parent / ".github/workflows/pylint.yml"


def pylint_step() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    return next(step["run"] for step in steps if "pylint $(git" in step.get("run", ""))


def test_ci_cannot_accept_a_failing_linter_with_a_rounded_perfect_score(tmp_path) -> None:
    script = 'pylint() { printf "Your code has been rated at 10.00/10\\n"; return 2; }\n'
    script += pylint_step()

    result = subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path,
                            env={**os.environ, "HOME": str(tmp_path)},
                            check=False, capture_output=True, text=True)

    assert result.returncode == 2
