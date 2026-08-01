# Readable Output Port

## As Is

Agent Discipline Watcher injects its discipline contract at session start. It does not carry a dedicated ruleset for readable user-facing replies or an evaluation harness that compares answer quality with and without that ruleset.

## To Be

The repository owns one readable output skill adapted from `ayghri/i-have-adhd`. Every supported client injects its body into the main agent at session start, while subagents continue to receive only the discipline contract. A paired evaluation harness measures readability without hiding quality regressions.

## Requirements

1. Port the five reading facts, ten rules and examples, six exceptions, and pre-send check into `skills/readable-output/SKILL.md` under the MIT license and required attribution.
2. Keep the rules always on for the main agent and absent from `SubagentStart` context.
3. Strip YAML frontmatter before injection and fail open if the skill cannot be read.
4. Deliver the same main-agent context through Claude, Codex, OpenCode, and Pi session-start paths.
5. Port the source evaluation cases, rubric, runner configuration, and runner with repository-local paths.

## Acceptance Criteria

1. The readable output skill produces no findings from `hooks/lib/scanner.py`.
2. Session start output contains the rules body without frontmatter, and a missing skill leaves the discipline contract intact.
3. Subagent start output does not contain the readable output heading or rules.
4. OpenCode and Pi inject the main-agent rules, while the Codex configuration keeps routing SessionStart through the shared hook.
5. Hook tests, evaluation runner tests, the OpenCode test, and pylint pass.

## Testing Plan

- Scan the skill directly with `scan_all`.
- Run the colocated SessionStart and SubagentStart tests.
- Run the full `hooks/` and `scripts/` pytest suites.
- Run the OpenCode test with its available TypeScript runner.
- Run pylint with the repository configuration over changed Python files.

## Implementation Plan

1. Add the attributed skill as the single rules source.
2. Extend main-agent session injection and its tests.
3. Extend OpenCode and Pi session-start adapters.
4. Port and validate the paired evaluation harness.
5. Update the README and run repository verification.
