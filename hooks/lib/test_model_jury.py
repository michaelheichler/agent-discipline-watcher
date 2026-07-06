from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gate
import record
from ledger import record_findings, read_ledger


class EnglishPipeline:
    def __init__(self, fail=False):
        self.fail = fail
        self.sentences = []
        self.unloaded = False

    def _split_sentences(self, text):
        return [line.strip() for line in text.splitlines() if line.strip()]

    def scan_sentences_graded(self, sentences):
        self.sentences.extend(sentences)
        if self.fail:
            raise RuntimeError("english failed")
        return [{"sentence": sentences[0], "cat": "economy", "fix": "Trim it."}] if sentences else []

    def unload(self):
        self.unloaded = True


class CleanJudge:
    def __init__(self, fail=False):
        self.fail = fail
        self.paths = []
        self.unloaded = False

    def scan_code(self, path, text):
        self.paths.append(path)
        if self.fail:
            raise RuntimeError("clean failed")
        return [{
            "line": 1,
            "rule": "deep-clean-code",
            "snippet": text.splitlines()[0],
            "detail": "Simplify this code.",
            "force": False,
        }]

    def unload(self):
        self.unloaded = True


class HostClient:
    def __init__(self):
        self.released = []

    def release_turn(self, turn_id):
        self.released.append(turn_id)


@contextlib.contextmanager
def open_gate():
    yield True


def test_stop_jury_invokes_english_and_clean_models(tmp_path):
    prose = tmp_path / "note.md"
    code = tmp_path / "app.py"
    prose.write_text("This sentence has enough words.", encoding="utf-8")
    code.write_text("def value():\n    return 1\n", encoding="utf-8")
    english = EnglishPipeline()
    clean = CleanJudge()
    host = HostClient()
    cfg = _cfg(tmp_path, english, clean, host)
    record_findings(str(prose), [], cfg)
    record_findings(str(code), [], cfg)

    response = gate.run({"session_id": "s1"}, cfg)

    assert english.sentences == ["This sentence has enough words."]
    assert clean.paths == [str(code)]
    assert english.unloaded is True
    assert clean.unloaded is True
    assert host.released == ["s1"]
    assert "english/economy" in response["systemMessage"]
    assert "clean_code/deep_clean_code" in response["systemMessage"]


def test_stop_jury_unloads_after_model_failure(tmp_path):
    prose = tmp_path / "note.md"
    code = tmp_path / "app.py"
    prose.write_text("This sentence has enough words.", encoding="utf-8")
    code.write_text("def value():\n    return 1\n", encoding="utf-8")
    english = EnglishPipeline(fail=True)
    clean = CleanJudge(fail=True)
    cfg = _cfg(tmp_path, english, clean, HostClient())
    record_findings(str(prose), [], cfg)
    record_findings(str(code), [], cfg)

    assert gate.run({"session_id": "s2"}, cfg) == {}
    assert english.unloaded is True
    assert clean.unloaded is True


def test_record_keeps_clean_touched_file_for_stop_jury(tmp_path):
    code = tmp_path / "clean.py"
    code.write_text("def value():\n    return 1\n", encoding="utf-8")
    clean = CleanJudge()
    cfg = _cfg(tmp_path, EnglishPipeline(), clean, HostClient())

    record.run({"tool_input": {"file_path": str(code)}}, cfg)
    assert read_ledger(cfg) == [{"path": str(code), "findings": [], "touched": True}]

    response = gate.run({"session_id": "s3"}, cfg)
    assert clean.paths == [str(code)]
    assert "clean_code/deep_clean_code" in response["systemMessage"]


def test_blocking_stop_report_keeps_advisory_model_findings(tmp_path):
    prose = tmp_path / "note.md"
    prose.write_text("This sentence has enough words.", encoding="utf-8")
    forced = {
        "family": "punctuation",
        "rule": "banned_dash",
        "line": 1,
        "detail": "Bad punctuation.",
        "force": True,
        "snippet": "bad dash",
        "action": "Use ASCII punctuation.",
    }
    cfg = _cfg(tmp_path, EnglishPipeline(), CleanJudge(), HostClient())
    record_findings(str(prose), [forced], cfg)

    response = gate.run({"session_id": "s4"}, cfg)
    report_path = response["reason"].rsplit("Full report: ", 1)[1].strip()
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    keys = {(item["family"], item["rule"]) for item in report}

    assert response["decision"] == "block"
    assert "advisory findings in full report" in response["reason"]
    assert ("punctuation", "banned_dash") in keys
    assert ("english", "economy") in keys


def _cfg(tmp_path, english, clean, host):
    return {
        "ledger_path": str(tmp_path / "agent-discipline-watcher-ledger.json"),
        "_english_pipeline": english,
        "_clean_deep_judge": clean,
        "_english_model_gate": open_gate,
        "_clean_model_gate": open_gate,
        "_host_client": host,
    }


if __name__ == "__main__":
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        test_stop_jury_invokes_english_and_clean_models(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_stop_jury_unloads_after_model_failure(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_record_keeps_clean_touched_file_for_stop_jury(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_blocking_stop_report_keeps_advisory_model_findings(Path(directory))
