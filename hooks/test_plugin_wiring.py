"""Plugin wiring tests: every registered event reaches a real module through run.sh, with no checkout path baked in."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
CLAUDE_MERGE = ROOT / "hooks" / "merge-claude-settings.py"
PLUGIN_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
RUN_SH = ROOT / "hooks" / "run.sh"
STUB_MARKER = "adw-stub"
REPO_SLUG = "michaelheichler/agent-discipline-watcher"

# Taken from the Claude Code hooks reference, because an unknown event key can break config parsing rather than no-op.
SUPPORTED_EVENTS = frozenset({
    "SessionStart", "Setup", "UserPromptSubmit", "UserPromptExpansion", "PreToolUse",
    "PermissionRequest", "PermissionDenied", "PostToolUse", "PostToolUseFailure",
    "PostToolBatch", "Notification", "MessageDisplay", "SubagentStart", "SubagentStop",
    "TaskCreated", "TaskCompleted", "Stop", "StopFailure", "TeammateIdle",
    "InstructionsLoaded", "ConfigChange", "CwdChanged", "FileChanged",
    "WorktreeCreate", "WorktreeRemove", "PreCompact", "PostCompact",
    "Elicitation", "ElicitationResult", "SessionEnd",
})
# Limited to the events the hooks reference lists, because an if filter on any other event never runs.
IF_CAPABLE_EVENTS = frozenset({
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied",
})


def dispatch_map() -> dict[str, str]:
    raw = RUN_SH.read_text(encoding="utf-8").split('DISPATCH="', 1)[1].split('"', 1)[0]
    return dict(pair.split(":", 1) for pair in raw.split())


def all_hooks(config: dict) -> list[tuple[str, dict]]:
    rows = []
    for event, groups in config["hooks"].items():
        for group in groups:
            rows.extend((event, entry) for entry in group["hooks"])
    return rows


def hook_commands(config: dict) -> list[tuple[str, dict]]:
    """Filter to command entries because an agent entry has no route through run.sh to assert against."""
    return [(event, entry) for event, entry in all_hooks(config) if entry.get("type") == "command"]


def route_of(entry: dict) -> str:
    return entry["command"].rsplit(" ", 1)[1]


def load_claude_merger():
    spec = importlib.util.spec_from_file_location("agent_discipline_claude_merge", CLAUDE_MERGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def merged_watcher_hooks(skill_dir: str) -> dict:
    return load_claude_merger().watcher_hooks(skill_dir)


class PluginManifestTests(unittest.TestCase):
    def test_session_end_releases_the_active_session_lease(self):
        config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        commands = [entry["command"] for event, entry in hook_commands(config) if event == "SessionEnd"]
        self.assertEqual(commands, ['"${CLAUDE_PLUGIN_ROOT}"/hooks/run.sh SessionEnd'])

    def test_hook_description_matches_deterministic_runtime(self):
        config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        self.assertNotIn("semantic", config["description"].lower())

    def test_manifest_does_not_redeclare_the_auto_discovered_hooks_file(self):
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "agent-discipline-watcher")
        self.assertTrue(HOOKS_JSON.is_file(), "hooks/hooks.json is the documented default location")
        declared = manifest.get("hooks")
        if declared is None:
            return
        entries = [declared] if isinstance(declared, str) else list(declared)
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertNotEqual(
                    (ROOT / str(entry)).resolve(), HOOKS_JSON.resolve(),
                    "the standard hooks/hooks.json loads automatically, so naming it again fails the plugin load",
                )

    def test_marketplace_entry_tracks_the_git_remote(self):
        catalog = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        entries = [row for row in catalog["plugins"] if row["name"] == "agent-discipline-watcher"]
        self.assertEqual(len(entries), 1)
        source = entries[0]["source"]
        self.assertEqual(source["source"], "github", "a local source breaks push-driven updates")
        self.assertEqual(source["repo"], REPO_SLUG)

    def test_marketplace_repo_matches_the_configured_origin(self):
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=str(ROOT),
            capture_output=True, text=True, check=False,
        )
        if remote.returncode != 0:
            self.skipTest("no origin remote configured")
        url = remote.stdout.strip().removesuffix(".git")
        self.assertTrue(url.endswith(REPO_SLUG), f"{url} does not match {REPO_SLUG}")

    def test_marketplace_entry_has_no_pinned_version(self):
        catalog = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        self.assertNotIn("version", catalog["plugins"][0])

    def test_manifest_uses_commit_sha_updates(self):
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        self.assertNotIn("version", manifest)


class PluginHookRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        self.dispatch = dispatch_map()

    def test_every_event_key_is_documented(self):
        unknown = set(self.config["hooks"]) - SUPPORTED_EVENTS
        self.assertEqual(unknown, set(), "an undocumented event key can break config parsing")

    def test_if_filters_only_appear_on_events_that_evaluate_them(self):
        for event, entry in hook_commands(self.config):
            if "if" in entry:
                self.assertIn(event, IF_CAPABLE_EVENTS, f"{event} never evaluates an if filter")

    def test_no_checkout_path_is_embedded(self):
        text = HOOKS_JSON.read_text(encoding="utf-8")
        self.assertNotIn("__SKILL_DIR__", text)
        self.assertNotIn(str(ROOT), text)
        self.assertNotIn("/Users/", text)
        self.assertNotIn("/home/", text)

    def test_every_command_routes_through_the_plugin_root(self):
        for event, entry in hook_commands(self.config):
            with self.subTest(event=event):
                self.assertTrue(entry["command"].startswith('"${CLAUDE_PLUGIN_ROOT}"/hooks/run.sh '))

    def test_every_registered_route_exists_in_dispatch(self):
        for event, entry in hook_commands(self.config):
            route = route_of(entry)
            with self.subTest(event=event, route=route):
                self.assertIn(route, self.dispatch, f"{route} is registered but run.sh cannot route it")
                self.assertTrue((ROOT / "hooks" / self.dispatch[route]).is_file())

    def test_every_dispatch_route_is_registered_or_a_compatibility_alias(self):
        registered = {route_of(entry) for _, entry in hook_commands(self.config)}
        aliases = {"PreCommit"}
        self.assertEqual(set(self.dispatch) - aliases, registered)
        self.assertEqual(self.dispatch["PreCommit"], self.dispatch["PreToolUse"])

    def test_claude_merge_watcher_hooks_describe_the_same_routes(self):
        merged = merged_watcher_hooks("/tmp/skill-dir")
        self.assertEqual(set(merged), set(self.config["hooks"]))
        plugin_routes = sorted(route_of(entry) for _, entry in hook_commands(self.config))
        merged_config = {"hooks": merged}
        merged_routes = sorted(route_of(entry) for _, entry in hook_commands(merged_config))
        self.assertEqual(plugin_routes, merged_routes)
        self.assertIn('\\"/tmp/skill-dir\\"/hooks/run.sh', json.dumps(merged))

    def test_claude_merge_watcher_hooks_share_if_filters(self):
        merged_config = {"hooks": merged_watcher_hooks("/tmp/skill-dir")}
        plugin_filters = {route_of(e): e.get("if") for _, e in hook_commands(self.config)}
        merged_filters = {route_of(e): e.get("if") for _, e in hook_commands(merged_config)}
        self.assertEqual(plugin_filters, merged_filters)

    def test_post_tool_use_command_uses_response_feedback_not_prompt_option(self):
        entries = [entry for event, entry in hook_commands(self.config) if event == "PostToolUse"]
        self.assertTrue(entries)
        self.assertTrue(all("continueOnBlock" not in entry for entry in entries))


    def test_pretool_command_does_not_use_prompt_hook_continuation_option(self):
        entries = [entry for event, entry in hook_commands(self.config) if event == "PreToolUse"]
        self.assertTrue(entries)
        self.assertTrue(all("continueOnBlock" not in entry for entry in entries))


class PluginCommandExecutionTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        self.dispatch = dispatch_map()
        self.tmp = tempfile.TemporaryDirectory()
        stub = Path(self.tmp.name) / "python3"
        stub.write_text(
            f'#!/bin/sh\nif [ "$1" = "-c" ]; then printf "3.99.0\\n"; exit 0; fi\necho "{STUB_MARKER} $@"\n'
        )
        stub.chmod(0o755)
        self.env = os.environ.copy()
        self.env["PATH"] = self.tmp.name + os.pathsep + self.env.get("PATH", "")
        self.env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)

    def tearDown(self):
        self.tmp.cleanup()

    def test_each_registered_command_invokes_its_module(self):
        for event, entry in hook_commands(self.config):
            route = route_of(entry)
            with self.subTest(event=event, route=route):
                result = subprocess.run(
                    entry["command"], shell=True, env=self.env, cwd=str(ROOT),
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith(STUB_MARKER), result.stdout)
                self.assertTrue(result.stdout.strip().endswith(self.dispatch[route]), result.stdout)

    def test_a_plugin_root_with_spaces_still_resolves(self):
        staging = Path(self.tmp.name) / "with space"
        shutil.copytree(ROOT / "hooks", staging / "hooks")
        shutil.copy2(ROOT / ".python-version", staging / ".python-version")
        env = dict(self.env, CLAUDE_PLUGIN_ROOT=str(staging))
        command = '"${CLAUDE_PLUGIN_ROOT}"/hooks/run.sh PreToolUse'
        result = subprocess.run(command, shell=True, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().endswith("pre_tool.py"), result.stdout)


class PostToolUseWiringTests(unittest.TestCase):

    def setUp(self):
        self.config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))

    def _agent_entries(self):
        return [entry for event, entry in all_hooks(self.config) if event == "PostToolUse" and entry.get("type") == "agent"]

    def test_the_command_post_tool_use_handler_still_exists(self):
        dispatch = dispatch_map()
        command_routes = {route_of(entry) for event, entry in hook_commands(self.config) if event == "PostToolUse"}
        self.assertIn("PostToolUse", command_routes)
        self.assertEqual(dispatch["PostToolUse"], "record.py")

    def test_no_unconditional_agent_handler_is_registered_on_post_tool_use(self):
        self.assertEqual(self._agent_entries(), [])

    def test_plugin_and_claude_merge_scan_bash_post_tool_use(self):
        merged = {"hooks": merged_watcher_hooks("/tmp/skill-dir")}
        for config in (self.config, merged):
            groups = config["hooks"]["PostToolUse"]
            self.assertTrue(any("Bash" in group.get("matcher", "") for group in groups))


class PluginLoaderTests(unittest.TestCase):
    """Exercises the real loader, because plugin validate and plugin install both accept a manifest the loader rejects."""

    def setUp(self):
        if shutil.which("claude") is None:
            self.skipTest("claude CLI not on PATH")
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        market = self.home / "market"
        (market / ".claude-plugin").mkdir(parents=True)
        (market / "plugin").symlink_to(ROOT)
        catalog = {
            "name": "adw-loader-probe",
            "owner": {"name": "test"},
            "plugins": [{
                "name": "agent-discipline-watcher",
                "source": "./plugin",
                "description": "loader probe",
            }],
        }
        (market / ".claude-plugin" / "marketplace.json").write_text(json.dumps(catalog), encoding="utf-8")
        self.market = market

    def tearDown(self):
        self.tmp.cleanup()

    def _claude(self, *args: str) -> str:
        env = dict(os.environ, HOME=str(self.home))
        result = subprocess.run(
            ["claude", "plugin", *args], capture_output=True, text=True,
            check=False, timeout=180, env=env,
        )
        return result.stdout + result.stderr

    def test_the_plugin_loads_without_error_in_a_sandbox_profile(self):
        self._claude("marketplace", "add", str(self.market))
        self._claude("install", "agent-discipline-watcher@adw-loader-probe")
        listing = re.sub(r"\x1b\[[0-9;]*m", "", self._claude("list"))
        block = listing.split("agent-discipline-watcher@adw-loader-probe", 1)
        self.assertEqual(len(block), 2, listing)
        detail = block[1][:400]
        self.assertNotIn("failed to load", detail, detail)
        self.assertIn("enabled", detail, detail)


class PluginValidatorTests(unittest.TestCase):
    def test_official_validator_accepts_the_manifests(self):
        binary = shutil.which("claude")
        if binary is None:
            self.skipTest("claude CLI not on PATH")
        # No --strict, because the CLAUDE.md warning is a known, accepted dev-workflow file.
        for target in (str(ROOT), str(PLUGIN_MANIFEST)):
            with self.subTest(target=target):
                result = subprocess.run(
                    [binary, "plugin", "validate", target],
                    capture_output=True, text=True, check=False, timeout=120,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Validation passed", re.sub(r"\x1b\[[0-9;]*m", "", result.stdout))


if __name__ == "__main__":
    unittest.main()
