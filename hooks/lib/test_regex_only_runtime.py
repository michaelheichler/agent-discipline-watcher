from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_stop_runtime_is_removed():
    launcher = (ROOT / "hooks" / "run.sh").read_text()

    assert not (ROOT / "hooks" / "gate.py").exists()
    assert not (ROOT / "hooks" / "lib" / "ledger.py").exists()
    assert "run.sh Stop" not in launcher
    assert "skill-model-loader" not in launcher
    assert "SML_PYTHON" not in launcher


def test_model_jury_module_is_removed():
    assert not (ROOT / "hooks" / "lib" / "model_jury.py").exists()
