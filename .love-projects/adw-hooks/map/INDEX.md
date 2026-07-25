# Codebase map

Advisory evidence only. `plan.json` remains authoritative.

## Stack
- `bin/agent-discipline`: python3 shebang CLI on argparse and pathlib, shipped as a plain script with no packaging metadata.
- `hooks/lib/scanner.py`: Pure Python 3 rule engine built on stdlib ast, re, fnmatch, and os with no third party imports.
- `hooks/run.sh`: Bash entry point that needs bash and python3 on PATH and execs one Python module per event.
- `install.sh`: Bash installer under set -eu, the only build or setup step the repo has.
- `opencode/agent-discipline-watcher.ts`: TypeScript plugin for the OpenCode runtime that shells out with node:child_process execFileSync.
- `pi/extensions/agent-discipline-watcher/index.ts`: TypeScript Pi extension that spawns python3 with an inline script through a promisified execFile.

## Dependencies
- `hooks/claude-settings.snippet.json`: Claude integration contract whose hook entries are merged into the user global settings.json.
- `hooks/codex-config.snippet.toml`: Codex integration contract whose hook tables are fenced into the user global config.toml.
- `hooks/merge-codex-config.py`: Uses stdlib tomllib to validate the merged TOML and silently skips validation when tomllib is absent.
- `hooks/merge-pi-settings.py`: Pi integration appends the extension file path into the extensions array of the Pi agent settings.
- `install.sh`: Installs into four client applications, Claude, Codex, OpenCode, and Pi, each behind its own flag pair.
- `opencode/agent-discipline-watcher.test.ts`: Only external test dependency in the repo, it imports bun:test, so the OpenCode suite needs Bun.

## Architecture
- `hooks/lib/config.py`: Config resolution walks parent directories for .agent-discipline.json, then layers an explicit config dict over those project settings.
- `hooks/lib/hookio.py`: Every hook process speaks one JSON protocol over stdin and stdout with deny, allow, and systemMessage shapes.
- `hooks/lib/reporting.py`: Each block writes the full finding list to a mode 0600 temp file and returns at most max_rows compact lines.
- `hooks/lib/scanner.py`: scan_all is the one funnel, unconditional rules run first, then the exemption check, then the per family line loops.
- `hooks/pre_commit.py`: PreCommit route lexes the Bash command with shlex, tracks cd and git -C, then scans staged ACM blobs through git show.
- `hooks/pre_write.py`: PreToolUse route pulls pending content out of tool_input, including apply_patch bodies, and denies before the write runs.
- `hooks/record.py`: PostToolUse route rereads the file from disk and exits 2 with the reason on stderr because it cannot undo the write.
- `hooks/run.sh`: Single dispatcher, a chain of event string comparisons that execs session_start.py, pre_write.py, pre_commit.py, or record.py.
- `opencode/agent-discipline-watcher.ts`: OpenCode adapter reuses run.sh over a subprocess instead of reimplementing rules, mapping camelCase args onto the Python payload.
- `pi/extensions/agent-discipline-watcher/index.ts`: Pi adapter skips run.sh and calls scan_all directly through an inline python3 script, a second and divergent entry path.

## Structure
- `.love-projects/adw-hooks/plan.json`: Planning worktree for the next hook expansion, holding plan.json as truth plus a rendered agent brief and per story files.
- `.requirements/20260706T000000Z_combined_watcher/REQUIREMENTS.md`: One dated REQUIREMENTS.md per change, the repo record of why each behaviour was added or removed.
- `bin/agent-discipline`: The single user facing CLI, symlinked into the user local bin directory by install.sh.
- `hooks/lib/hookio.py`: Shared layer holding config resolution, the stdin and stdout protocol, report formatting, and the rule engine.
- `hooks/run.sh`: One module per hook event plus the three client config merge scripts and both client snippets.
- `opencode/agent-discipline-watcher.test.ts`: OpenCode plugin and its Bun test kept together beside the plugin rather than under hooks.
- `pi/extensions/agent-discipline-watcher/index.ts`: Pi extension directory whose exact path is what merge-pi-settings.py writes into the Pi settings file.

## Conventions
- `.love-projects/adw-hooks/engine-room/agent-plan.md`: Work is identified by epic, story, and task IDs such as E2-W-T0, which recent commit subjects carry as a prefix.
- `README.md`: States the hook code holds itself to its own contract, every function under the cap and zero findings on its own files.
- `SKILL.md`: States the contract the repo enforces on agents, punctuation, plain English, and clean code, written as rules with no exceptions.
- `hooks/lib/config.py`: ALWAYS_ON_RULES records in code which two rules ignore every config switch and why.
- `hooks/lib/reporting.py`: Block messages carry path, line, rule, and action only, the offending snippet stays in the private full report.
- `hooks/lib/scanner.py`: Deferred work markers are assembled from split string halves so the scanner source never trips its own rule.
- `hooks/lib/scanner.py`: Only WHY comments are allowed, _what_comment_rows runs on every code file regardless of the clean_code switch.
- `hooks/lib/test_pi_extension_contract.py`: A test asserts the repo own README and SKILL prose carry no en dash, em dash, or doubled hyphen.

## Testing
- `README.md`: Documented verification is cd hooks then python3 -m pytest . lib -q, which currently passes with 91 tests.
- `hooks/lib/test_config_cli.py`: Drives bin/agent-discipline as a subprocess, covering interactive selection and parent config discovery.
- `hooks/lib/test_pi_extension_contract.py`: Asserts against the TypeScript source text rather than running it, so the Pi extension is never executed under test.
- `hooks/lib/test_regex_only_runtime.py`: Guard tests that assert deleted modules stay deleted, gate.py, ledger.py, and model_jury.py.
- `hooks/lib/test_scanner.py`: Rule level coverage for the scanner, the largest test file for the largest module.
- `hooks/test_hooks.py`: End to end hook tests import pre_write, record, pre_commit, and session_start and call run() with synthetic payloads.
- `hooks/test_merge_configs.py`: Largest test file in the repo, covering the Claude, Codex, and Pi merges including idempotent reruns.
- `opencode/agent-discipline-watcher.test.ts`: The only test that exercises the OpenCode adapter, and no repo file documents how to run it.

## Concerns
- `hooks/lib/reporting.py`: Every block leaves a JSON report in the system temp directory and nothing ever removes those files.
- `hooks/lib/scanner.py`: Rules are line oriented regex, so a banned construct split across two lines is never seen.
- `hooks/merge-claude-settings.py`: Rewrites the user settings.json with a plain write_text and no atomic replace, unlike the Codex merge which writes atomically.
- `hooks/merge-claude-settings.py`: prune drops any hook whose command contains knowledge-based-search or lean-ctx, so installing deletes hooks belonging to unrelated packages.
- `hooks/merge-pi-settings.py`: Same non atomic rewrite of the user Pi settings, with no validation of the merged result.
- `opencode/agent-discipline-watcher.ts`: install.sh copies this plugin instead of symlinking it, so the installed OpenCode copy goes stale after a repo update.
- `opencode/agent-discipline-watcher.ts`: runWatcher turns any non zero exit into a block, so an unrelated runtime failure blocks every write on OpenCode.
- `pi/extensions/agent-discipline-watcher/index.ts`: scan swallows every error and returns an empty list, so a broken python3 silently disables enforcement on Pi.
