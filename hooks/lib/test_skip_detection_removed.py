from lib.scanner import scan_all


def test_skip_calls_are_not_policed():
    text = "pytest.skip(reason)\ncursor.skip(offset)\n"
    rows = scan_all("sample.py", text, {"punctuation": False, "english": False})
    assert "skipped_test" not in {item["rule"] for item in rows}
