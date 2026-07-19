from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_stop_runtime_is_regex_only():
    gate = (ROOT / "hooks" / "gate.py").read_text()
    launcher = (ROOT / "hooks" / "run.sh").read_text()

    assert "model_jury" not in gate
    assert "judge_touched" not in gate
    assert "skill-model-loader" not in launcher
    assert "SML_PYTHON" not in launcher


def test_model_jury_module_is_removed():
    assert not (ROOT / "hooks" / "lib" / "model_jury.py").exists()
