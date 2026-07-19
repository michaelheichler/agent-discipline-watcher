# Forced Regex Results Only

## As Is

The deterministic scanner emits forced findings and three advisory findings: comma splice, quote punctuation, and the file-length warning. Reporting still contains advisory-only helpers. The combined clean-code rules do not catch the explicit narration starters named by the source skill. Skipped-test policing was intentionally removed in commit `a007720` after it matched ordinary skip calls.

## To Be

The scanner emits only certain findings, and every emitted finding blocks immediately in write, post-write, and pre-commit paths. Advisory rules and reporting are absent. Deterministic regex coverage includes skipped-test markers and explicit narration starters. Semantic guidelines that regex cannot prove remain skill guidance only.

## Requirements

1. Remove all non-forced scanner results and advisory reporting paths.
2. Preserve every existing forced punctuation, English, and clean-code rule.
3. Add deterministic explicit narration-comment rules from the source skills without restoring intentionally removed skipped-test policing.
4. Keep config installation and all immediate hook lifecycles unchanged.

## Acceptance Criteria

1. Every result from `scan_all` has `force` set to true, and former comma-splice, quote-punctuation, and file-warning inputs return no result.
2. Existing forced-rule tests continue to pass.
3. Comments beginning with `now`, `now we`, `this function`, `this method`, or `this class` block. Skip calls remain unpoliced.
4. PreToolUse, PostToolUse, PreCommit, and Pi still block emitted findings without any advisory branch.

## Testing Plan

- Change scanner and reporting contract tests first and prove they fail.
- Add focused positive and negative cases for skipped tests and narration comments.
- Run the full Python suite, shell syntax checks, self-scan, and live install audits.

## Implementation Plan

1. Replace advisory expectations with a forced-only invariant and run the focused tests.
2. Delete advisory rules and reporting helpers, then rerun focused tests.
3. Add the missing deterministic narration rule and keep the skipped-test removal regression.
4. Run full verification and install twice on Mac and x86-host.
