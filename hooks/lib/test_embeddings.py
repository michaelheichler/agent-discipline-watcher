"""Locks every embedding failure mode to a deterministic fallback because no caller may hang on an external process."""
import os
import stat
import subprocess
import sys

import embeddings

CANDIDATES = [{"id": "c1", "text": "why marker missing here"}]
PROTOTYPES = [
    {"label": "WHY", "text": "kept because callers require stable ordering"},
    {"label": "WHAT", "text": "loads the cache"},
]

HELPER_OK = """#!/usr/bin/env python3
import json, sys
data = json.load(sys.stdin.buffer)
texts = data["texts"]
sys.stdout.write(json.dumps({"embeddings": [[float(len(t)), 1.0] for t in texts]}))
"""

HELPER_COUNTING = """#!/usr/bin/env python3
import json, sys
counter_path = sys.argv[1]
count = int(open(counter_path).read()) if __import__("os").path.exists(counter_path) else 0
open(counter_path, "w").write(str(count + 1))
data = json.load(sys.stdin.buffer)
texts = data["texts"]
sys.stdout.write(json.dumps({"embeddings": [[float(len(t)), 1.0] for t in texts]}))
"""

HELPER_TIMEOUT = """#!/usr/bin/env python3
import time
time.sleep(30)
"""

HELPER_BAD_EXIT = """#!/usr/bin/env python3
import sys
sys.exit(1)
"""

HELPER_MALFORMED = """#!/usr/bin/env python3
import sys
sys.stdout.write("not json")
"""


def _write_helper(tmp_path, name: str, source: str, argv=None) -> str:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def setup_function(_function) -> None:
    embeddings.clear_cache()
    os.environ.pop(embeddings.ENV_VAR, None)


def test_missing_env_returns_none(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(embeddings.ENV_VAR, raising=False)
    assert embeddings.enrich(CANDIDATES, PROTOTYPES) is None


def test_relative_or_non_executable_path_rejected(monkeypatch, tmp_path) -> None:
    script = tmp_path / "helper.py"
    script.write_text(HELPER_OK, encoding="utf-8")
    monkeypatch.setenv(embeddings.ENV_VAR, "relative/helper.py")
    assert embeddings.enrich(CANDIDATES, PROTOTYPES) is None
    monkeypatch.setenv(embeddings.ENV_VAR, str(script))
    assert embeddings.enrich(CANDIDATES, PROTOTYPES) is None


def test_successful_batch_enriches_with_nearest_prototype(monkeypatch, tmp_path) -> None:
    helper = _write_helper(tmp_path, "helper.py", HELPER_OK)
    monkeypatch.setenv(embeddings.ENV_VAR, helper)
    result = embeddings.enrich(CANDIDATES, PROTOTYPES)
    assert result is not None
    match = result["c1"]
    assert match["label"] in ("WHY", "WHAT")
    assert 0.0 <= match["similarity"] <= 1.0
    assert "example" in match


def test_malformed_output_degrades_to_none(monkeypatch, tmp_path) -> None:
    helper = _write_helper(tmp_path, "helper.py", HELPER_MALFORMED)
    monkeypatch.setenv(embeddings.ENV_VAR, helper)
    assert embeddings.enrich(CANDIDATES, PROTOTYPES) is None


def test_nonzero_exit_degrades_to_none(monkeypatch, tmp_path) -> None:
    helper = _write_helper(tmp_path, "helper.py", HELPER_BAD_EXIT)
    monkeypatch.setenv(embeddings.ENV_VAR, helper)
    assert embeddings.enrich(CANDIDATES, PROTOTYPES) is None


def test_timeout_kills_child_and_degrades_to_none(monkeypatch, tmp_path) -> None:
    helper = _write_helper(tmp_path, "helper.py", HELPER_TIMEOUT)
    monkeypatch.setenv(embeddings.ENV_VAR, helper)
    assert embeddings.enrich(CANDIDATES, PROTOTYPES, timeout=0.2) is None


def test_process_exits_after_one_invocation(monkeypatch, tmp_path) -> None:
    helper = _write_helper(tmp_path, "helper.py", HELPER_OK)
    monkeypatch.setenv(embeddings.ENV_VAR, helper)
    before = subprocess.run(["pgrep", "-f", str(helper)], capture_output=True, check=False)
    embeddings.enrich(CANDIDATES, PROTOTYPES)
    after = subprocess.run(["pgrep", "-f", str(helper)], capture_output=True, check=False)
    assert before.stdout == after.stdout == b""


def test_caching_avoids_a_second_helper_invocation(monkeypatch, tmp_path) -> None:
    counter = tmp_path / "count.txt"
    script = tmp_path / "helper.py"
    script.write_text(HELPER_COUNTING, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import subprocess, sys\n"
        f"sys.exit(subprocess.call([sys.executable, {str(script)!r}, {str(counter)!r}]))\n",
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv(embeddings.ENV_VAR, str(wrapper))
    embeddings.enrich(CANDIDATES, PROTOTYPES)
    embeddings.enrich(CANDIDATES, PROTOTYPES)
    assert counter.read_text() == "1"


def test_helper_identity_change_busts_the_cache(monkeypatch, tmp_path) -> None:
    counter = tmp_path / "count.txt"
    script = tmp_path / "helper.py"
    script.write_text(HELPER_COUNTING, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import subprocess, sys\n"
        f"sys.exit(subprocess.call([sys.executable, {str(script)!r}, {str(counter)!r}]))\n",
        encoding="utf-8",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv(embeddings.ENV_VAR, str(wrapper))
    embeddings.enrich(CANDIDATES, PROTOTYPES)
    wrapper.write_text(wrapper.read_text() + "\n", encoding="utf-8")
    embeddings.enrich(CANDIDATES, PROTOTYPES)
    assert counter.read_text() == "2"
