# As Is

The watcher scans prompt snapshots extracted by tweakcc. Those snapshots include upstream prose and command examples. Findings from those files block unrelated configuration work.

# To Be

The watcher ignores files below any `.tweakcc/system-prompts` directory. It continues scanning tweakcc configuration and user-authored scripts.

# Requirements

1. Exempt extracted tweakcc prompt snapshots by default.
2. Keep all other configured checks unchanged.

# Acceptance Criteria

1. A path below `.tweakcc/system-prompts` produces no findings.
2. The same text outside that directory still produces its normal findings.

# Testing Plan

Add a scanner regression test for the exempt path and a control path. Run the scanner test module, then the complete hook test suite.

# Implementation Plan

1. Add the failing regression test and run it.
2. Add one default exempt path pattern and rerun the focused test.
3. Run the full hook suite and a live Stop gate check.
