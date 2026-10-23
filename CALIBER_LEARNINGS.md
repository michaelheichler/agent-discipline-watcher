# Caliber Learnings

Accumulated patterns and anti-patterns from development sessions.
Auto-managed by [caliber](https://github.com/caliber-ai-org/ai-setup) — do not edit manually.

- **[convention]** Keep machine-specific maintenance records outside the shared repository.
- **[convention]** Preserve unrelated settings and credentials during ADW maintenance.
- **[gotcha]** `claude plugin validate . --strict` exits 1 even on a clean tree. Two warnings cause this, and the user accepts both. The first is that `.claude-plugin/plugin.json` has no `version`, because ADW ships commit revisions instead of a version file. The second is that the root `CLAUDE.md` is not loaded as plugin context. Judge the run by its warning list rather than its exit code. Any third warning is a real failure.
- **[convention]** Every file in `commands/` needs a YAML frontmatter block with at least `description`, or the strict plugin validator fails. Quote `argument-hint` values, as in `argument-hint: "[--check]"`, because YAML reads an unquoted `[...]` as a list.
- **[pattern]** To reproduce the CI pylint run locally, run `uvx --python 3.11 --with pytest --from pylint pylint $(git ls-files '*.py')` from the repo root. Pylint exits nonzero on any single message. One leftover row drops the score to 9.95, and that fails CI.
- **[gotcha]** Piping pylint or pytest through `tail` hides their exit code. In the agent shell (zsh), `${PIPESTATUS[0]}` comes back empty. To get the real code, run the command without a pipe and then `echo $?`, or redirect its output to `/dev/null` or a file first.
- **[gotcha]** The full Python 3.11 suite (`cd hooks && uvx --python 3.11 --with pytest pytest . lib -q`) takes about 10 minutes, measured at 5663 tests in 594 s. That is right at the 600000 ms foreground Bash limit. Start it with `run_in_background: true` and read the task output file when it exits. For quick checks, run only the test files that cover your change.
- **[gotcha]** ADW's own gate blocks file writes made through inline interpreters, such as `python3 -c "open(...).write(...)"`, as `inline_interpreter_write`. Make every file change with the Edit or Write tool, even a trivial one like trimming a trailing newline.
- **[pattern]** To commit only part of the tree, stage it with pathspec excludes in one call, for example `git add -A -- . ':(exclude)CHANGELOG.md' ':(exclude).story/handovers'`. Then run `git commit` in the next call with no paths. The commit gate rejects path arguments on `git commit` but allows them on `git add`.
- **[pattern]** When other agents may edit the tree during a long QA run, record `shasum -a 256` of the files under test before the run and again after it. Matching hashes prove that the suite tested the tree you are about to commit.
