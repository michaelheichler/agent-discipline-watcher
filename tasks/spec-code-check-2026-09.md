# Spec for the Code Check family and principle explanations

Draft for review, written on 2026-09-30. The plan lives in [plan-code-check-2026-09.md](plan-code-check-2026-09.md).
The tickets live in [todo-code-check-2026-09.md](todo-code-check-2026-09.md).
The rule source is the [Khorikov test catalog](../docs/research/2026-09-30-khorikov-test-catalog.md).

## Objective

Agents write tests that protect nothing. One agent session can add 500 tests that pin names and literals.
Each of those tests costs maintenance and catches no regression. ADW blocks bad prose and bad comments today.
It does not judge whether a test is worth keeping.

This work adds a third rule family, Code Check. It judges tests against the four pillars from Khorikov,
"Unit Testing Principles, Practices, and Patterns". It also judges code against clean code principles.

Every Code Check finding carries a short plain-text explanation of the principle it breaks.
The explanation comes from DevIQ or from webpro/programming-principles. The agent reads it and can fix the test.
The human who watches the session reads the same text and can judge whether the gate reduces slop.

The ADW test suite is the first corpus. It holds 2012 `def test_` functions on 2026-09-30.

### Example the gate must catch

```rust
fn every_sex_the_profile_form_offers_keeps_the_mechanistic_method_ready() {
    for sex in ["männlich", "weiblich", "divers", "keine-angabe"] {
        let (mut profile, events, command, cutoff) = saved();
        profile["sex"] = json!(sex);
        let prepared = prepare_from_saved(&profile, &events, &command, cutoff).unwrap();
        let response = forecast_pathways(&prepared.request()).unwrap();
        assert_eq!(response["pathways"][0]["status"], "ready", "{sex}: {response}");
    }
}
```

### Two rules the user named

1. `hardcoded_name_presence`. The test only asserts that a hard-coded name or key appears somewhere, and the expected value is a literal too. It pins text, not behavior.
2. `hardcoded_literal_in_source`. The test asserts that the code or the configuration contains a fixed literal. It restates the source.

## Capability map

| Module id | Responsibility | Depends on |
| --- | --- | --- |
| model-currency | Luna resolves to the newest `gpt-N-luna`, Claude judges resolve to the newest Haiku or Sonnet, and every verdict records the resolved model | none |
| embedding-cost | Measure one embedding load cycle, then keep the worker warm across turns with an idle timeout | none |
| rule-families | Split the rule set into Prose, Comment Check, and Code Check | none |
| test-audit-static | Khorikov rules that regex or AST can decide, measured on the ADW suite | rule-families |
| principle-kb | Local knowledge base built from DevIQ and programming-principles, and the explanation text in each finding | rule-families |
| test-audit-semantic | Khorikov rules that need meaning, through the embedding vote and the Luna judge | test-audit-static, embedding-cost, model-currency |

Build order is model-currency, embedding-cost, rule-families, then test-audit-static and principle-kb, then test-audit-semantic.

## Assumptions

1. The user wrote "Mein Ziel ist es, eine Testexplosion mit über 500 sinnlosen Tests zu haben". This spec reads it as the goal to prevent that explosion.
2. Code Check starts with Python and Rust test files. Python covers the ADW suite. Rust covers the example above.
3. This public repository never holds the explanation text. Neither source repository carries a license file, so the text stays under its authors' copyright. This is an inference and not legal advice. The plugin ships only the mapping from rule id to source entry. The machine that runs ADW fetches the text into its own local store.
4. The store is a local SQLite file under `~/.adw/cache`. A hook must answer in milliseconds, and a MacBook away from the home network cannot reach 10.0.0.9. Hosting on Unraid stays an open question.
5. A Code Check rule blocks only after it reaches the existing precision threshold of 0.85, held in `pattern_semantic.ENFORCE_PRECISION`. Until then it reports and does not block.
6. When ADW resolves to a newer model on its own, the old precision numbers no longer describe the gate. Each verdict therefore records the resolved model id.

## Tech stack

Python 3.11 standard library for the hooks. SQLite through the `sqlite3` module for the knowledge base. The existing MLX embedding worker on darwin-arm64 and the llama.cpp worker on linux-x86_64. The existing Luna provider through the Codex SDK runtime. The `pi` extension in TypeScript on Bun for OMP.

No new runtime dependency enters the hook interpreter.

## Commands

```bash
cd hooks && uvx --python 3.11 --with pytest pytest . lib -q
pylint $(git ls-files '*.py')
bash -n $(git ls-files '*.sh')
cd pi && bun install && bun test
```

## Project structure

```text
hooks/lib/catalog.py          rule names, families, and their descriptions
hooks/lib/scanner.py          deterministic scan per surface
hooks/lib/comment_rules.py    comment and docstring rules
hooks/lib/test_rules.py       new, Code Check test rules that regex or AST can decide
hooks/lib/principle_kb.py     new, rule id to explanation lookup
hooks/lib/principle_map.json  new, rule id to DevIQ or programming-principles entry id
hooks/lib/luna_provider.py    Luna model selection
hooks/lib/claude_presets.py   Claude judge model selection
docs/research/                source extractions and measurements
evals/                        corpora and precision measurements
```

## Code style

The repository style holds. One strict WHY line per docstring, at most 60 characters. Findings go through the `Finding` record.

```python
findings.append(_finding(Finding(
    family="code", rule="assert_in_loop", line=line_number,
    detail="Assertion inside a loop in " + path, force=False,
    snippet=line.strip()[:180], action="Split the cases into a parameterized test.",
    path=None, severity=None, tool_use_id=None,
)))
```

## Testing strategy

The new rules apply to their own tests. Each rule gets one violating and one clean fixture taken from the Khorikov catalog. Tests assert on findings, never on the text of a rule name that the test itself hard-codes.

A script measures precision, and no test asserts it. The script labels a sample of ADW test functions by hand and writes the result to `evals/`.

## Boundaries

Always do these things.
1. Run the full hook suite and pylint before each commit.
2. Keep an unmeasured rule at observe.
3. Keep old configuration family names working.

Ask first before these steps.
1. Deploy anything to the Unraid host at 10.0.0.9.
2. Delete tests from the ADW suite that a new rule flags.
3. Add a runtime dependency to the hook interpreter.
4. Push, merge, or release.

Never do these things.
1. Commit DevIQ or programming-principles text to this repository.
2. Print or log the Unraid credentials.
3. Let a rule block before it has a precision measurement.

## Success criteria

1. `catalog.FAMILIES` names `prose`, `comment`, and `code`. A configuration that names `punctuation`, `english`, or `clean_code` still loads and means the same rules.
2. Code Check reports the Rust example above with at least the loop rule and the name rule.
3. The static test rules run on the ADW suite. `evals/` records the hit count and the hand-labeled precision per rule.
4. Each Code Check finding shows the explanation text once per rule per session, at most 80 words, with no link.
5. A fresh install with no network still runs every gate. The finding then carries the rule text without the explanation.
6. Luna runs on the newest `gpt-N-luna` that the Codex account lists with high effort. The journal records that model id.
7. `evals/` records the embedding load time and peak memory before and after the idle-timeout change.

## Open questions

1. Unraid. Local SQLite is enough for one machine. Recommendation is to skip Unraid unless several machines must share one store.
2. Claude model aliases. No test shows yet whether the hook `model` field accepts the `haiku` or `sonnet` alias. Task 2 tests it before the change lands.
3. Suite cleanup. The self-audit will flag ADW tests. Who decides which ones go?
