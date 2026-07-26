<!-- love-render src=plan.json sha=9a6a469f do not hand-edit -->

# E6-S7 AST-native forbidden-API and architecture rules

Epic E6: Repo verification tier (config-driven quality gates, trust-gated, observe-first). Sprint 6. Gate unit-testing.

## Why
As an operator, I want project-owned ast-grep or Semgrep rules run on changed files with rule ids and precise ranges, so code-pattern policy is structural, not regex-lexical.

## Done when
- the adapter runs project rules on changed files at PostToolUse and diff-wide at commit or TaskCompleted, blocks with rule id plus range, and reserves regex for non-code files

## Execution
- [ ] E6-S7-T1: lib/ast_rules.py adapter

