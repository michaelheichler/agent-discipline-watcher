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
- [x] 7. Per-surface `rule_gates`, done in `d291d44`. A gate value may be a `{surface: state}`
      map, findings carry a `surface`, and `pre_commit` tags its own as `commit`. An unnamed
      surface falls to the family rather than to off, and always-blocking rules ignore the map.
- [ ] 8. Commit message scanning. **Mechanism ready, default deliberately unchanged.** Task 7
      supplies the knob. Downgrading `banned_adverb`, `lazy_extreme`, and `passive_voice` on the
      commit surface would weaken the shipped gate, which this repo does not do without a
      measurement. It waits on task 11 and therefore on task 1.
- [ ] 9. Comment and docstring surface. **Missing.** `scanner._scan_line_families` runs the
      english family only when `context.prose` holds, so no slop rule reaches a comment.

## Phase 5. Report metric
- [ ] 10. Five-dimension slop score. **Missing.** No score field exists in `reporting.py`.

## Phase 6. Calibration
- [ ] 11. Measured precision per rule per surface. **Partial.** Structure rules sit hard-coded
      at `enforce` with no recorded precision, which the plan forbids. Blocked behind task 1.
- [x] 12. Self-scan and multi-version CI, done in `d291d44`. The floor job reads
      `.python-version` and a forward matrix runs 3.12 and 3.13. A third job runs the Bun suite,
      which CI never ran. Pylint now asserts 10.00 rather than trusting an exit code that stays
      zero on a warning. The suite passes on 3.11, 3.12, 3.13, and 3.14.
- [ ] 13. German markers in observe. **Missing.** `WEIGHTED_MARKERS` holds English only.

## Decision needed before Phase 6 starts
- [ ] Rebuild the corpora from new sources, or drop every calibration task. Tasks 2, 5, 6, 8,
      and 11 all wait on that answer.

Verified on 2026-08-31. `evals/corpus_slop_sentence.jsonl` and `corpus_slop_document.jsonl` are
absent, and `~/Downloads` holds none of the four CSV sources `build_slop_corpora.py` names. Only
the user can supply those files, so tasks 1, 2, 5, 6, and 11 stay blocked on data rather than on
work. Tasks 9, 10, and 13 need no corpus and remain open.

## Ordering note
Task 8 blocks commit messages today, so it earns priority over the rest of this plan. It
needs task 7 first, because the fix is a per-surface gate rather than a rule downgrade.
