# Host gate repair plan

Repair all seven review findings for OMP, Claude Code, and Codex, including
the latched Stop guard. The user authorized implementation, Cubic review,
merge, a patch release, and installation locally and on tux@10.0.10.106.
Live tests use Haiku or Luna. Luna subagents work at max reasoning.

## Decisions

Resolve explicit tool targets without imposing another permission scope.
Keep regular-file validation and inode checks. Reconcile pending OMP files
after verification. Inspect installed tool contracts before adapting them.
Review both documents and comments. Connect OMP to a working model provider.
Permit proven read-only Python without admitting opaque writes.

## Order

Complete the numbered tasks in tasks/todo.md. Independent slices may run
in parallel with separate file ownership. Each fix starts with a failing
regression test and ends with a focused test run.

## Delivery

Run the full Python and Bun suites, shell checks, and pylint before opening
the PR. Address Cubic findings, merge, bump the patch version, and tag it.
Install the released copy for all three harnesses on both machines.
Archive old reports and preserve unrelated settings and credentials.
Never delete active hook state to release a failing check.

## Risks

Keep external reads safe against symlink races. Do not clear unresolved files
because an unrelated scan passed. Keep model failures visible and retryable.
Claude's proxy returned HTTP 407 in the review, so verify its login path.
Record infrastructure failures separately from ADW behavior.

