"""Focused contract tests for the OMP Configure bridge.

These tests cover the bridge boundary without invoking the OMP process. The
shell dispatcher has its route coverage in test_run_dispatch.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import configure
from lib import config


def _digest(path: Path) -> str:
    """Return the CAS digest used by the bridge for an existing file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _capability(tmp_path: Path, monkeypatch) -> None:
    """Install one owner-only capability file and its matching child environment."""
    monkeypatch.setattr(configure, "_omp_parent_is_trusted", lambda: True)
    token = "omp-save-token"
    path = tmp_path / ".omp-capability"
    path.write_text(token, encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv(configure.CAPABILITY_ENV, token)
    monkeypatch.setenv(configure.CAPABILITY_FILE_ENV, str(path))


def _request(cwd: Path, values: dict[str, object], digest: str | None) -> dict[str, object]:
    """Build the fixed write request sent by the OMP save action."""
    return {
        "operation": "write",
        "cwd": str(cwd),
        "expected_digest": digest,
        "values": values,
    }


def test_bun_omp_parent_is_trusted(monkeypatch) -> None:
    """Accept Bun only when it launched the installed OMP command."""
    launcher = str(Path(configure.pwd.getpwuid(os.getuid()).pw_dir) / ".bun/bin/omp")
    monkeypatch.setenv("HOME", str(Path("/tmp") / "attacker-home"))
    responses = iter(
        (
            SimpleNamespace(returncode=0, stdout="bun\n"),
            SimpleNamespace(returncode=0, stdout=f"bun {launcher} --no-session\n"),
        )
    )

    def fake_run(command, **_kwargs):
        """Return the process identity fields requested by the trust check."""
        assert command[:3] == ["/bin/ps", "-p", str(os.getppid())]
        return next(responses)

    monkeypatch.setattr(configure.subprocess, "run", fake_run)

    assert configure._omp_parent_is_trusted() is True


def test_arbitrary_bun_parent_is_not_trusted(monkeypatch) -> None:
    """Reject Bun when its command line does not identify OMP."""
    responses = iter(
        (
            SimpleNamespace(returncode=0, stdout="bun\n"),
            SimpleNamespace(returncode=0, stdout="bun /tmp/worker.js\n"),
        )
    )

    monkeypatch.setattr(configure.subprocess, "run", lambda *_args, **_kwargs: next(responses))

    assert configure._omp_parent_is_trusted() is False


def test_validate_returns_checked_policy_values() -> None:
    """Validate returns accepted policy values without touching project files."""
    result = configure.run({"operation": "validate", "values": {"adw_model": "claude-sonnet-5", "max_rows": 12}})

    assert result == {
        "ok": True,
        "operation": "validate",
        "values": {"adw_model": "claude-sonnet-5", "max_rows": 12},
    }


def test_describe_exposes_metadata_and_redacts_runtime(monkeypatch) -> None:
    """Describe returns policy metadata without returning configured URL contents."""
    monkeypatch.setenv("ADW_EMBEDDING_URL", "https://user:secret@example.test/review?token=hidden")
    monkeypatch.setenv("ADW_PYTHON", "/private/runtime/python3")
    monkeypatch.setenv("ADW_ALLOW_PROTECTED_EDIT", "1")

    result = configure.run({"operation": "describe"})

    assert result["ok"] is True
    assert result["operation"] == "describe"
    assert "punctuation" in result["editable_fields"]
    assert any(row["name"] == "what_comment" and row["locked"] for row in result["rules"])
    assert result["runtime"]["python"] == {"configured": True, "executable": "python3"}
    assert result["runtime"]["embedding"] == {"configured": True}
    assert "secret" not in json.dumps(result)
    assert "ADW_ALLOW_PROTECTED_EDIT" not in json.dumps(result)


def test_read_resolves_upward_and_excludes_unknown_keys(tmp_path: Path) -> None:
    """Read uses the hook resolver and keeps opaque project fields off the response."""
    root = tmp_path / "project"
    child = root / "nested"
    child.mkdir(parents=True)
    target = root / config.CONFIG_NAME
    target.write_text(
        json.dumps(
            {
                "checks": {"english": False, "vendor_only": "opaque"},
                "gates": {"punctuation": "observe"},
                "unknown_runtime_policy": {"secret": "opaque"},
            }
        ),
        encoding="utf-8",
    )

    result = configure.run({"operation": "read", "cwd": str(child)})

    assert result["ok"] is True
    assert result["config_path"] == str(target)
    assert result["values"]["english"] is False
    assert result["values"]["gates"] == {"punctuation": "observe"}
    assert "unknown_runtime_policy" not in json.dumps(result)
    assert "vendor_only" not in json.dumps(result)
    assert result["effective"]["english"] is False
    assert result["family_states"]["punctuation"] == "observe"


def test_malformed_legacy_family_values_fail_closed(tmp_path: Path) -> None:
    """A non-boolean legacy family value cannot disable a family through file loading."""
    for value in ([], 0, "", None, "false"):
        target = tmp_path / config.CONFIG_NAME
        target.write_text(json.dumps({"english": value}), encoding="utf-8")

        result = configure.run({"operation": "read", "cwd": str(tmp_path)})
        effective = config.effective_config(cwd=tmp_path)

        assert result["error"]["code"] == "invalid_project_config"
        assert effective["english"] is True


def test_oversized_project_file_is_rejected_before_parse(tmp_path: Path) -> None:
    """A project file above the loader bound is rejected without a decoder walk."""
    target = tmp_path / config.CONFIG_NAME
    target.write_bytes(b"{" + b" " * config.MAX_PROJECT_CONFIG_BYTES + b"}")

    result = configure.run({"operation": "read", "cwd": str(tmp_path)})

    assert result["error"]["code"] == "invalid_project_config"


def test_forged_env_capability_cannot_write(tmp_path: Path, monkeypatch) -> None:
    """A bare or forged environment token is not sufficient for a policy write."""
    target = tmp_path / config.CONFIG_NAME
    target.write_text(json.dumps({"unknown": "keep"}), encoding="utf-8")
    before = target.read_bytes()
    monkeypatch.setenv(configure.CAPABILITY_ENV, "forged-token")
    monkeypatch.delenv(configure.CAPABILITY_FILE_ENV, raising=False)

    result = configure.run(_request(tmp_path, {"english": False}, _digest(target)))

    assert result["error"]["code"] == "capability_required"
    assert target.read_bytes() == before


def test_direct_shell_route_rejects_forged_environment(tmp_path: Path) -> None:
    """Invoking run.sh directly with a forged token cannot authorize a write."""
    target = tmp_path / config.CONFIG_NAME
    target.write_text(json.dumps({"english": True}), encoding="utf-8")
    environment = os.environ.copy()
    environment[configure.CAPABILITY_ENV] = "forged-token"
    environment.pop(configure.CAPABILITY_FILE_ENV, None)
    request = _request(tmp_path, {"english": False}, _digest(target))

    completed = subprocess.run(
        [str(Path(__file__).with_name("run.sh")), configure.CONFIGURE_EVENT],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["error"]["code"] == "capability_required"
    assert json.loads(target.read_text(encoding="utf-8"))["english"] is True


def test_direct_shell_route_ignores_forged_ps(tmp_path: Path) -> None:
    """A PATH-provided ps cannot impersonate OMP for a shell caller."""
    target = tmp_path / config.CONFIG_NAME
    target.write_text(json.dumps({"english": True}), encoding="utf-8")
    capability = tmp_path / "forged-capability"
    capability.write_text("forged-token", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ps = fake_bin / "ps"
    fake_ps.write_text("#!/bin/sh\nprintf 'omp\n'\n", encoding="utf-8")
    fake_ps.chmod(0o755)
    environment = os.environ.copy()
    environment[configure.CAPABILITY_ENV] = "forged-token"
    environment[configure.CAPABILITY_FILE_ENV] = str(capability)
    environment["ADW_PYTHON"] = sys.executable
    environment["PATH"] = f"{fake_bin}:{environment.get('PATH', '')}"
    request = _request(tmp_path, {"english": False}, _digest(target))

    completed = subprocess.run(
        [str(Path(__file__).with_name("run.sh")), configure.CONFIGURE_EVENT],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["error"]["code"] == "capability_required"
    assert json.loads(target.read_text(encoding="utf-8"))["english"] is True

def test_direct_shell_route_rejects_forged_complete_capability(tmp_path: Path) -> None:
    """A shell-created owner-only token file cannot impersonate the OMP save boundary."""
    target = tmp_path / config.CONFIG_NAME
    target.write_text(json.dumps({"english": True}), encoding="utf-8")
    capability = tmp_path / "forged-capability"
    capability.write_text("forged-token", encoding="utf-8")
    capability.chmod(0o600)
    environment = os.environ.copy()
    environment[configure.CAPABILITY_ENV] = "forged-token"
    environment[configure.CAPABILITY_FILE_ENV] = str(capability)
    request = _request(tmp_path, {"english": False}, _digest(target))

    completed = subprocess.run(
        [str(Path(__file__).with_name("run.sh")), configure.CONFIGURE_EVENT],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["error"]["code"] == "capability_required"
    assert json.loads(target.read_text(encoding="utf-8"))["english"] is True


def test_write_uses_cas_and_preserves_unknown_keys(tmp_path: Path, monkeypatch) -> None:
    """A capability-gated write updates known values while retaining opaque data."""
    target = tmp_path / config.CONFIG_NAME
    target.write_text(
        json.dumps({"unknown": {"keep": True}, "checks": {"english": True}}),
        encoding="utf-8",
    )
    _capability(tmp_path, monkeypatch)

    result = configure.run(_request(tmp_path, {"english": False}, _digest(target)))
    saved = json.loads(target.read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["written"] is True
    assert saved["unknown"] == {"keep": True}
    assert saved["checks"]["english"] is False
    assert result["digest"] == _digest(target)


def test_root_edits_are_rejected_without_dropping_opaque_roots(tmp_path: Path, monkeypatch) -> None:
    """Root paths remain untouched and hidden while an attempted edit is refused."""
    target = tmp_path / config.CONFIG_NAME
    target.write_text(
        json.dumps(
            {
                "state_root": "/private/state",
                "ledger_root": "/private/ledger",
                "opaque": {"keep": True},
            }
        ),
        encoding="utf-8",
    )
    before = target.read_bytes()
    _capability(tmp_path, monkeypatch)

    result = configure.run(
        _request(tmp_path, {"state_root": "/tmp/other", "english": False}, _digest(target))
    )

    assert result["error"]["code"] == "protected_field"
    assert target.read_bytes() == before
    assert "state_root" not in json.dumps(configure.run({"operation": "read", "cwd": str(tmp_path)}))


def test_always_blocking_rule_cannot_be_downgraded(tmp_path: Path, monkeypatch) -> None:
    """The bridge rejects a protected rule edit before replacing the project file."""
    target = tmp_path / config.CONFIG_NAME
    target.write_text(json.dumps({"rule_gates": {"what_comment": "enforce"}}), encoding="utf-8")
    before = target.read_bytes()
    _capability(tmp_path, monkeypatch)

    result = configure.run(
        _request(tmp_path, {"rule_gates": {"what_comment": "observe"}}, _digest(target))
    )

    assert result["error"]["code"] == "protected_rule"
    assert target.read_bytes() == before


def test_digest_conflict_does_not_overwrite(tmp_path: Path, monkeypatch) -> None:
    """A stale expected digest is rejected after the capability is consumed."""
    target = tmp_path / config.CONFIG_NAME
    target.write_text(json.dumps({"english": True}), encoding="utf-8")
    stale = _digest(target)
    target.write_text(json.dumps({"english": False}), encoding="utf-8")
    before = target.read_bytes()
    _capability(tmp_path, monkeypatch)

    result = configure.run(_request(tmp_path, {"english": True}, stale))

    assert result["error"]["code"] == "digest_conflict"
    assert target.read_bytes() == before


def test_capability_replay_is_refused(tmp_path: Path, monkeypatch) -> None:
    """The one-shot capability file cannot authorize a second save."""
    target = tmp_path / config.CONFIG_NAME
    target.write_text(json.dumps({"english": True}), encoding="utf-8")
    _capability(tmp_path, monkeypatch)
    request = _request(tmp_path, {"english": False}, _digest(target))

    first = configure.run(request)
    second = configure.run(request)

    assert first["ok"] is True
    assert second["error"]["code"] == "capability_required"


def test_atomic_failure_keeps_original_file(tmp_path: Path, monkeypatch) -> None:
    """A failed replacement leaves the original config bytes intact."""
    target = tmp_path / config.CONFIG_NAME
    target.write_text(json.dumps({"english": True}), encoding="utf-8")
    before = target.read_bytes()
    _capability(tmp_path, monkeypatch)

    def fail_replace(_source, _destination):
        """Raise the simulated replacement failure."""
        raise OSError("replacement failed")

    monkeypatch.setattr(configure.os, "replace", fail_replace)
    result = configure.run(_request(tmp_path, {"english": False}, _digest(target)))

    assert result["error"]["code"] == "write_failed"
    assert target.read_bytes() == before
    assert os.path.exists(os.fspath(target))
