<!-- love-render src=plan.json sha=3d899cf9 do not hand-edit -->

# E6-S8 Commit-message gate

Epic E6: Repo verification tier (config-driven quality gates, trust-gated, observe-first). Sprint 6. Gate code-review.

## Why
As an operator, I want commit messages extracted from -m payloads and scanned (discipline families plus an optional conventional-commit format) before Bash executes, so commit text meets the same bar as file text.

## Done when
- pre_commit.py extracts every -m and message-file payload with its existing shell-aware parser, scans with the scanner families, applies the optional format policy from config, and lets editor-only forms pass unless strict mode is on

## Execution
- [ ] E6-S8-T1: Commit-message extraction and scan in pre_commit

