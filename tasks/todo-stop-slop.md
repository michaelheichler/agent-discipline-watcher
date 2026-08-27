# Todo: stop-slop detection in ADW

Plan: [plan.md](plan.md)

## Phase 1: Corpus and harness
- [ ] 1. Build the sentence corpus and the document corpus, with each source bias recorded
- [ ] 2. Per-rule, per-surface precision and recall harness

## Checkpoint
- [ ] Corpus rebuilds deterministically, suite green, label balance reviewed

## Phase 2: Phrase rules
- [ ] 3. `hooks/lib/slop_phrase.py`, weighted markers from sloptotal
- [ ] 4. Wire into the english family without growing `scanner.py`

## Phase 3: Structure rules
- [ ] 5. `hooks/lib/slop_structure.py`, the eight zero-false-positive categories
- [ ] 6. Rhythm statistics in `prose_structure.py`

## Checkpoint
- [ ] All 98 patterns mapped to a rule or a written omission reason
- [ ] Repo self-scan clean

## Phase 4: Surfaces and gating
- [ ] 7. Per-surface `rule_gates`, plus the `config_seal` escape checks
- [ ] 8. Commit message scanning, structural rules only
- [ ] 9. Comment and docstring surface, structural rules only

## Phase 5: Report metric
- [ ] 10. Five-dimension slop score, never gated

## Phase 6: Calibration
- [ ] 11. Gate state per rule per surface from measured precision, never on one corpus alone
- [ ] 12. Self-scan, pylint 10.00, CI green on 3.11, 3.12 and 3.13
- [ ] 13. German markers, observe only until a German corpus exists

## Checkpoint
- [ ] Coverage remeasured against the 98-pattern probe
