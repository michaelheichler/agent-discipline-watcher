# Readability Scanner Rules

## As Is

The readable-output contract shapes main-agent replies through injected instructions. The scanner cannot measure its mechanically checkable rules. Code comments also miss the same direct-language checks.

## To Be

The English and clean-code scanner families report six distinct readability rules. Every rule starts in `observe`. The readable-output contract serves ADHD, autistic, dyslexic, and English-language learners without presenting usability conventions as cognitive laws.

## Requirements

1. Add `ai_closer`, `greeting_opener`, `hedge_stack`, and `corporate_idiom` as distinct English rules.
2. Keep single hedges legal and report only stacked hedge pairs.
3. Report sentences over 40 words and Markdown list runs over eight items through configurable thresholds.
4. Skip fenced code, Markdown tables, and link-reference lines during structural prose checks.
5. Run the four lexical readability rules on extracted code comments under `clean_code`.
6. Ship all six rules in `observe` with independent rule gates.
7. Widen the readable-output contract and add rule 11 for double negatives and nested clauses.
8. Document evidence tiers, rejected scanner candidates, and the limits of numeric heuristics.

## Acceptance Criteria

1. Positive and negative tests cover every new lexical rule.
2. Tests prove that one use of `might` or `perhaps` does not trigger `hedge_stack`.
3. Structural tests cover both fence styles, tables, link references, and threshold overrides.
4. Comment findings keep the same rule IDs and use the `clean_code` family.
5. The evaluation case file validates with the two new readability cases.
6. Repository prose produces no enforced scanner findings.
7. Session start injects the updated contract with rule 11.
8. Hook tests, script tests, and pylint pass.

## Testing Plan

- Run `python3 -m pytest hooks/ scripts/`.
- Run pylint with `.pylintrc` on changed Python files.
- Run `python3 scripts/run_evals.py validate`.
- Scan the README, readable-output skill, and this requirement file.
- Feed a SessionStart payload through `hooks/run.sh` and inspect the contract.

## Implementation Plan

1. Add the lexical rules and structural scanner.
2. Register thresholds and observe gates.
3. Wire readability checks into comment extraction.
4. Add scanner tests and evaluation cases.
5. Update the skill and evidence documentation.
6. Run the complete verification loop.
