# As Is

The scanner classifies selected function calls as skipped tests. This rule produced false positives and was changed on Tux without approval.

# To Be

The watcher does not classify any skip call as a finding.

# Requirements

1. Remove skipped-test detection from the scanner.
2. Preserve every other scanner rule.
3. Publish the canonical change before updating Tux.

# Acceptance Criteria

1. Skip calls produce no `skipped_test` finding.
2. The full hook suite passes.
3. GitHub contains the commit and Tux runs that commit.

# Testing Plan

Run a focused assertion before and after the change. Add one regression test, then run the complete hook suite on Mac and Tux.

# Implementation Plan

1. Prove the existing scanner reports a skip finding.
2. Delete the regex and its rule registration.
3. Add and run the focused regression test.
4. Run all hook tests, commit, push, and fast-forward Tux.
