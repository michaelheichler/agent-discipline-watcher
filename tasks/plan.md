# Host gate repair plan

Repair all seven review findings for OMP, Claude Code, and Codex, including
the latched Stop guard. The user authorized implementation, Cubic review,
merge, a patch release, and installation locally and on the designated remote host.
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

Run the full Python and Bun suites before opening the PR. Check shell syntax
and pylint too. Address Cubic findings before merging, then bump and tag the patch version.
Install the released copy for all three harnesses on both machines.
Archive old reports and preserve unrelated settings and credentials.
Never delete active hook state to release a failing check.

## Risks

Keep external reads safe against symlink races. Do not clear unresolved files
because an unrelated scan passed. Keep model failures visible and retryable.
Claude's proxy returned HTTP 407 in the review, so verify its login path.
Record infrastructure failures separately from ADW behavior.

## Remote verification follow-up

The remote installation exposed a native Claude hook failure. Agent hooks
forward short model aliases to the API without resolving them. Replace those
aliases with supported API identifiers, prove the rendered configuration in
tests, and verify Haiku through the installed native hook before releasing
the follow-up patch. Keep injected Luna names and command handlers unchanged.

The installed native hook also needs an explicit structured response. Remove
the plain JSON completion cue and direct native reviewers to the harness's
StructuredOutput tool. Verify the installed result after a reviewed release.

## OMP JavaScript dispatch

OMP code mode wraps ordinary tools in JavaScript eval calls. ADW must admit
literal calls through the tool bridge while keeping direct JavaScript file
access blocked. Recognize a bounded dispatch grammar, retain each nested
tool's gate, and verify both read success and write rejection on OMP.

## Controlled maintenance

Keep ordinary configuration edits available through the existing content
checks. Add an installed updater for the latest published ADW release from
the fixed official repository. It accepts host choices only, stages the exact
release revision, and owns installation paths and subprocess environment.

The updater must preserve pending state and unrelated host settings. Claude
must use the same pinned revision, with plugin installation verified before
legacy wiring removal. Generic installer commands retain their current guard.
Use Terminal for the first installation of the updater.

## Cursor rule classification

Treat `.mdc` as Markdown in both prose classification and YAML frontmatter
masking. Verify an unchanged Cursor rule through post-edit and Stop, then
prove ordinary body violations still block. Reproduce the reported glob
case with OMP and a cheap model before pushing.

OMP implements `xd://report_issue` as a native report device. Route only that
exact write destination to OMP without filesystem checks. Preserve its own
consent prompt. Verify that failed reports cannot create pending file scans
and that ordinary file writes keep their gates.

`hooks/lib/scanner.py:1` reports `file_length_warning`. Keep this parsing fix
narrow. Before the scanner reaches 750 lines, move its file-format predicates
and constants into one shared module, with classification tests unchanged.
