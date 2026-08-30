# Todo for stop-slop detection in ADW

Plan lives in [plan-stop-slop.md](plan-stop-slop.md). The code shipped in `199525a`. Status below
comes from an audit on 2026-08-30 that checked each task against the source, not from the
original boxes, which recorded nothing done.

## Phase 1. Corpus and harness
- [ ] 1. Sentence and document corpora. **Blocked.** `slop_harness._CORPUS_NAMES` points at
      `corpus_slop_sentence.jsonl` and `corpus_slop_document.jsonl`. Neither exists, both sit
      in `.gitignore:19`, and `evals/build_slop_corpora.py` needs CSV sources from `~/Downloads`
      that are gone. The build script itself is complete and deterministic.
- [ ] 2. Per-rule per-surface harness. **Partial.** `score_rule` and `assert_floors` work for
      PROSE only. `_SURFACE_REASONS` marks COMMENT and COMMIT unmeasurable, and `_scan_source`
      raises for any non-PROSE surface.

## Phase 2. Phrase rules
- [x] 3. `slop_phrase.py` with `WEIGHTED_MARKERS`, density threshold 20.0, minimum 3 matches
- [x] 4. Wired into the english family at `scanner.py:274-278`, proven by `test_slop_integration.py`

## Phase 3. Structure rules
- [ ] 5. `slop_structure.py` ships all eight categories. **Partial.** `RULE_EVIDENCE` covers
      three phrase rules only, so no structure rule records a true positive count.
- [ ] 6. Rhythm statistics run in `prose_structure.py`. **Partial.** `RHYTHM_LIMITATIONS`
      records `low_sentence_variance` as unmeasurable with precision 0.0.

## Phase 4. Surfaces and gating
- [ ] 7. Per-surface `rule_gates`. **Missing.** `config._rule_state_from` accepts a flat state
      string, so a `{surface: state}` value falls through to the family gate.
      `protected._gated_off_everywhere` carries no per-surface escape check either.
- [ ] 8. Commit message scanning. **Partial and wrong today.** `pre_commit._message_findings`
      scans the body as prose, and `banned_adverb`, `lazy_extreme`, and `passive_voice` all sit
      at `enforce`, so word-level rules block commit bodies. Task 7 is the prerequisite.
- [ ] 9. Comment and docstring surface. **Missing.** `scanner._scan_line_families` runs the
      english family only when `context.prose` holds, so no slop rule reaches a comment.

## Phase 5. Report metric
- [ ] 10. Five-dimension slop score. **Missing.** No score field exists in `reporting.py`.

## Phase 6. Calibration
- [ ] 11. Measured precision per rule per surface. **Partial.** Structure rules sit hard-coded
      at `enforce` with no recorded precision, which the plan forbids. Blocked behind task 1.
- [ ] 12. Self-scan and multi-version CI. **Partial.** `pylint.yml` runs on 3.11 alone, with no
      3.12 or 3.13 matrix and no pylint 10.00 assertion.
- [ ] 13. German markers in observe. **Missing.** `WEIGHTED_MARKERS` holds English only.

## Decision needed before Phase 6 starts
- [ ] Rebuild the corpora from new sources, or drop every calibration task. Tasks 2, 5, 6,
      and 11 all wait on that answer.

## Ordering note
Task 8 blocks commit messages today, so it earns priority over the rest of this plan. It
needs task 7 first, because the fix is a per-surface gate rather than a rule downgrade.
