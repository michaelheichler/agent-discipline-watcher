import json

import pytest

from lib import omp_review


ENABLED = {"data_boundary": {"enabled": True}, "adw_model": "anthropic/claude-haiku"}
COMMENT = "Returns the result because the caller needs a value."


def payload_for(path):
    return {"cwd": str(path.parent), "session_id": "omp-test", "tool_input": {"file_path": str(path)}}


def prepare(path, config=None):
    return omp_review.run({"operation": "prepare", "payload": payload_for(path)}, config or ENABLED)


def validate(path, prepared, output, index=0):
    return omp_review.run({
        "operation": "validate", "payload": payload_for(path),
        "digest": prepared["digest"], "request_id": index, "output": json.dumps(output),
    }, ENABLED)


def test_disabled_boundary_does_not_read_source(tmp_path, monkeypatch):
    def unexpected_read(_path):
        raise AssertionError("source must remain unread")

    monkeypatch.setattr(omp_review, "read_source", unexpected_read)
    assert prepare(tmp_path / "missing.py", {"data_boundary": {"enabled": False}}) == {
        "enabled": False, "requests": [],
    }


@pytest.mark.parametrize("suffix,prefix", [(".py", "#"), (".ts", "//")])
def test_every_comment_is_reviewed_and_bound_to_its_line(tmp_path, suffix, prefix):
    path = tmp_path / f"source{suffix}"
    path.write_text(f"{prefix} {COMMENT}\n{prefix} {COMMENT}\n", encoding="utf-8")
    prepared = prepare(path)
    assert len(prepared["requests"]) == 1
    assert "0. " + COMMENT in prepared["requests"][0]["prompt"]
    assert "1. " + COMMENT in prepared["requests"][0]["prompt"]
    result = validate(path, prepared, {"items": [
        {"index": 0, "verdict": "states_why", "reason": "A constraint."},
        {"index": 1, "verdict": "describes_code", "reason": "Describes the returned value."},
    ]})
    assert result["decision"] == "block"
    assert f"{path}:2:" in result["reason"]


def test_missing_candidate_verdict_is_a_failure(tmp_path):
    path = tmp_path / "source.py"
    path.write_text(f"# {COMMENT}\n# {COMMENT}\n", encoding="utf-8")
    prepared = prepare(path)
    with pytest.raises(ValueError, match="every candidate"):
        validate(path, prepared, {"items": [{"index": 0, "verdict": "states_why", "reason": "Constraint."}]})


def test_comment_batches_include_candidates_beyond_the_old_limit(tmp_path):
    path = tmp_path / "source.py"
    path.write_text((f"# {COMMENT}\n" * 43), encoding="utf-8")
    prepared = prepare(path)
    assert [request["candidate_count"] for request in prepared["requests"]] == [40, 3]


def test_document_review_preserves_boundaries_and_one_note_budget(tmp_path):
    path = tmp_path / "draft.md"
    path.write_text("A complete sentence.\n" * 1300 + "Final tail.", encoding="utf-8")
    prepared = prepare(path)
    documents = [request for request in prepared["requests"] if request["kind"] == "document"]
    assert len(documents) == 1
    assert path.read_text(encoding="utf-8") in documents[0]["prompt"]
    assert "Final tail." in documents[-1]["prompt"]


def test_ambiguous_document_quote_requires_more_context(tmp_path):
    path = tmp_path / "draft.md"
    path.write_text("Ready.\nFirst section.\nReady.\nSecond section.", encoding="utf-8")
    prepared = prepare(path)
    with pytest.raises(ValueError, match="ambiguous"):
        validate(path, prepared, {"notes": [{"quote": "Ready.", "problem": "Unclear status.", "fix": "Name the ready component."}]})


def test_large_finding_batch_keeps_every_row_in_a_report(tmp_path, monkeypatch):
    from lib import reporting

    monkeypatch.setattr(reporting, "_reports_dir", lambda: tmp_path / "reports")
    path = tmp_path / "source.py"
    path.write_text((f"# {COMMENT}\n" * 40), encoding="utf-8")
    prepared = prepare(path)
    result = validate(path, prepared, {"items": [
        {"index": index, "verdict": "describes_code", "reason": "Describes the implementation. " * 25}
        for index in range(40)
    ]})
    assert len(result["reason"]) <= 900
    report = next((tmp_path / "reports").glob("*.json"))
    assert str(report) in result["reason"]
    rows = json.loads(report.read_text(encoding="utf-8"))
    assert len(rows) == 40
    assert f"{path}:40:" in rows[-1]["message"]


def test_fabricated_document_quote_is_rejected(tmp_path):
    path = tmp_path / "draft.md"
    path.write_text("The release ships on Friday.", encoding="utf-8")
    prepared = prepare(path)
    with pytest.raises(ValueError, match="quote"):
        validate(path, prepared, {"notes": [{"quote": "The release is cancelled.", "problem": "Contradiction.", "fix": "Correct it."}]})


def test_changed_file_cannot_accept_a_stale_clean_result(tmp_path):
    path = tmp_path / "draft.md"
    path.write_text("The release ships on Friday.", encoding="utf-8")
    prepared = prepare(path)
    path.write_text("The release ships next week.", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        validate(path, prepared, {"notes": []})


def test_oversized_source_is_not_reported_as_clean(tmp_path):
    path = tmp_path / "draft.md"
    path.write_text("a" * (128 * 1024 + 1), encoding="utf-8")
    with pytest.raises(ValueError, match="read"):
        prepare(path)


def test_unparseable_python_cannot_silently_drop_its_comments(tmp_path):
    path = tmp_path / "source.py"
    path.write_text(f"# {COMMENT}\ndef broken(\n", encoding="utf-8")
    with pytest.raises(ValueError, match="parse Python source"):
        prepare(path)
