# Implementation Plan: stop-slop detection in ADW

## Overview

ADW covers 6 of the 98 patterns that the stop-slop skill defines. This plan raises that
to full coverage using regex and stdlib statistics only, calibrated against a labelled
corpus of real AI and human prose rather than against sentences invented from the pattern
list. Rules ship at the gate state their measured precision earns on each surface, so the
adverb and passive rules never block the commit messages and WHY comments this repo
already requires.

## Evidence

Measured before planning, all numbers reproducible from the scripts named in each row.

| Measurement | Result | Source |
| --- | --- | --- |
| stop-slop patterns ADW detects today | 6 of 98 | one probe sentence per pattern through `scan_all` |
| `-ly` adverb hits on ADW markdown | 63 in 575 sentences | tracked `*.md` |
| Lazy-extreme hits on ADW markdown | 28 in 575 sentences | tracked `*.md` |
| Passive hits on ADW markdown | 33 in 575 sentences | tracked `*.md` |
| `-ly` adverb hits in commit bodies | 235 in 1585 lines | last 200 commits |
| Lazy-extreme hits in commit bodies | 121 in 1585 lines | last 200 commits |
| Structural pattern hits, all surfaces | 0 | narrator, binary contrast, false agency, Wh- starter |
| sloptotal engines that need no dependency | 6 of 23 | import scan of `app/engines` |
| Marker density, length-matched AUC | 0.963 | 46 AI against 46 human, median 295 words |
| Sentence-variance AUC | 0.902 inverted | same sample |
| Formulaic density AUC | 0.811 | same sample |

Two findings drive the design.

Structural rules cost nothing. They fired zero times across prose, comments and commit
messages, so they can enforce on every surface from the first release.

Word-level rules are the opposite. On this repo the lazy-extreme rule would attack the
exact WHY comment style that the `clean_code` family demands, in comments such as
`Bypass every switch and exemption because scanner._unconditional_findings must agree`.
Those rules need a per-surface gate or they cannot ship at all.

## Architecture Decisions

**D1. Regex plus a stdlib weighted scorer. No model dependency.** Decision D6 pins this
codebase to stdlib-only Python 3.11, and `hooks/lib/test_regex_only_runtime.py` asserts
that `model_jury.py` stays deleted. The length-matched spike reaches 0.963 AUC on marker
density alone, so an embedding model buys nothing that would justify reversing that pin.
Revisit only if calibration in Phase 6 leaves a rule family below 0.80 precision.

**D2. Pattern lists come from sloptotal, not from stop-slop.** sloptotal is MIT licensed
and its marker weights carry a calibration note against 108 RAID samples. The stop-slop
lists are prose guidance for a reader. Where the two disagree the sloptotal weight wins,
because it was measured. stop-slop still supplies the structural taxonomy, which sloptotal
has no equivalent for.

**D3. Two modules under the existing english family.** `slop_phrase.py` and
`slop_structure.py` both emit into `english`. No new key enters the `gates` map, so
`config_seal` and its `_gated_off_everywhere` and `_killed_everywhere` escape checks need
no new work.

**D4. Per-surface rule gates.** `rule_gates` gains an optional per-surface form so one
rule can enforce in prose and stay off in comments and commit messages. This is the only
schema change in the plan, and `config_seal` must learn it as a new escape route.

**D5. Rhythm rules block. The five-dimension score never blocks.** Sentence variance,
three-item lists and paragraph-ending uniformity are countable. The stop-slop score asks
whether prose sounds human, which no regex answers, so it enters the report as a number
and no gate reads it.

**D6. Use every usable corpus, compare within a length band, and generate nothing.** No
clean dataset of AI prose exists and hunting for one wastes the budget. The goal is a
reliable spot, not a perfect classifier. Each source on disk carries a known bias. A rule
must therefore survive in more than one of them before it enforces. Each corpus is
compared only inside a band where the two classes overlap in length. Length is
the confound that ruins all of these sets: scored raw, `data_for_preprocessing.csv`
reports hapax ratio at 0.982 AUC and root type token ratio at 0.011, which is a word
counter in costume.

| Source | Rows | Usable as | Known bias |
| --- | --- | --- | --- |
| `AI Generated Essays Dataset.csv` | 85 AI, 1375 human | Document rules, 150 to 450 word band, 46 against 46 | Student persuasive essays only |
| `ai_vs_human_text.csv` | 648 AI, 651 human | Sentence rules, naturally matched at 9 to 10 words | Human class is famous aphorisms, not ordinary prose |
| `data_for_preprocessing.csv` | 3069 AI, 3000 human | Nothing | AI p90 is 57 words, human p10 is 174, the classes never overlap |
| `large_ai_human_dataset.csv` | 246 AI, 254 human | Nothing | Placeholder text, and the labels contradict the rows |

**D7. Density is a threshold, not a finding.** Every claim keeps a line the reader can
check. On the 9-word sentence corpus the weighted markers score AUC 0.507 with a 1.4
percent hit rate, against 0.963 on 300-word documents. Markers appear roughly once per 45
words, so most single sentences contain none. One `robust` is noise where eight is a
pattern. That argues for a density measure. It does not argue for a finding without a
line.

A line number is the evidence pointer. It is what lets a reader open the file and judge
whether the tool is right. A whole-file verdict anchored at line 1 points at something
that is not the reason, so the claim can be neither confirmed nor refuted, and an
unfalsifiable finding teaches the reader to ignore the detector. That cost never shows up
in a diff, which is why it is written down here.

So density decides whether the markers surface, and the markers carry the evidence. Below
the threshold they stay quiet. Above it every contributing marker is reported at its own
real line, under a verdict naming the measured rate. The reader can walk the list,
disagree with any entry, and catch the detector being wrong. That last property is what
makes the rest of its output worth believing.

Variance follows the same rule. A paragraph whose sentence lengths barely differ is
reported at that paragraph, not at the file.

**D8. A rule earns power by being caught being right, not by staying quiet.** The eight
structural rules produce zero hits on this repository, and an earlier draft of this plan
treated that as grounds to enforce them immediately. It is not. Zero hits means the rule
has never been observed being correct either, so its error rate is unknown rather than
low. Silence is absence of evidence, and reading it as evidence of safety is the fastest
route to a blocking rule that nobody has ever checked.

Every rule therefore ships with two recorded numbers, a true positive count above zero and
a measured precision, both naming the corpus and the sample size they came from. A rule
that cannot produce a true positive is either wrong or untestable, and neither ships.
Enforcement is a power granted on evidence, and the evidence is public in the report.

## Rejected

`large_ai_human_dataset.csv` entirely. Every row reads `Sample text number N
demonstrating ... style`, and rows labelled `Human` say `demonstrating AI generated
style`. It is placeholder output, not text.

`data_for_preprocessing.csv` as a calibration source. Its 6069 balanced rows look ideal
until you measure length. It cannot be salvaged by sampling, because the two classes do
not overlap at any length.

Generating new labelled samples. The existing sets are biased but real. Synthetic rows
would be written by the same kind of model the rules are meant to catch, which makes the
corpus agree with the rules by construction.

Vendoring sloptotal engine code. Only the pattern lists and the weights are worth taking.
The engine classes carry a scoring contract and a schema that ADW has no use for.

## Task List

### Phase 1: Corpus and harness

- [ ] **Task 1: Build the two labelled corpora.**
  `hooks/lib/corpus_slop_sentence.jsonl` from `ai_vs_human_text.csv`, which is already
  matched at 9 to 10 words and scores the line-anchored rules.
  `hooks/lib/corpus_slop_document.jsonl` from the 150 to 450 word band of the essays
  dataset, which scores the density and variance rules. Two files, because D7 splits the
  rules by scope and one corpus cannot score both.
  - Acceptance: each row carries `label`, `source`, `text`, and the bias note for its
    source, so no reader mistakes an aphorism corpus for ordinary human prose.
  - Acceptance: neither label holds more than 60 percent of rows in either file.
  - Acceptance: a rebuild script under `evals/` reproduces both files byte for byte from
    the CSVs, and skips the two rejected sources by name.
  - Verification: `python3 -m pytest hooks -q`.
  - Dependencies: none. Scope: Small.

- [ ] **Task 2: Score rules against the corpus per surface.**
  Extend the existing recall test pattern from `test_scanner.py:854` into a harness that
  reports precision and recall for one rule at a time, and reports separately for the
  prose, comment and commit surfaces.
  - Acceptance: harness prints a per-rule, per-surface table and fails only on a rule
    that regresses below its recorded floor.
  - Acceptance: the existing `what_comment` recall assertion still passes unchanged.
  - Verification: full suite green at its current count.
  - Dependencies: Task 1. Scope: Medium.

### Checkpoint: Foundation
- [ ] Corpus rebuilds deterministically, harness runs, suite green.
- [ ] Review the corpus label balance before any rule is written.

### Phase 2: Phrase rules

- [ ] **Task 3: Add `hooks/lib/slop_phrase.py` with the weighted marker rules.**
  Port the sloptotal marker list and the formulaic opener, closer and filler patterns,
  dropping the eight Spanish markers. Carry the weights, because a single `robust` is
  noise and eight of them is not.
  - Acceptance: covers throat-clearing, emphasis crutches, jargon, filler,
    meta-commentary, performative emphasis, telling, and vague declaratives.
  - Acceptance: every reported marker carries its own line, per D7. Density decides
    whether the weight-1 markers surface, and never speaks without citing them.
  - Verification: harness reports precision for each new rule against the corpus that
    matches its scope.
  - Dependencies: Task 2. Scope: Medium.

- [ ] **Task 4: Wire `slop_phrase` into the english family.**
  Rules join `ENGLISH_RULES` through the new module rather than being pasted into
  `scanner.py`, which already carries a file-length warning.
  - Acceptance: `scan_all` emits the new rules on a `.md` file.
  - Acceptance: `scanner.py` line count does not increase.
  - Verification: full suite green.
  - Dependencies: Task 3. Scope: Small.

### Phase 3: Structure rules

- [ ] **Task 5: Add `hooks/lib/slop_structure.py`.**
  The eight structural categories: binary contrast, negative listing, dramatic
  fragmentation, rhetorical setup, formulaic construction, false agency,
  narrator-from-a-distance, and passive voice. These scored zero hits on this repo, which
  is not evidence that they are correct. It only means they have never been observed at
  all, in either direction. They need a measured recall before they gain any power, per
  D8.
  - Acceptance: every category has at least one rule and enough corpus rows to compute a
    recall figure, not merely one row.
  - Acceptance: recorded true positive count is above zero for every rule. A rule that
    fires on nothing in the corpus is either wrong or untestable, and neither ships.
  - Acceptance: zero hits when run across this repo tracked markdown, recorded as a
    precision input rather than as a pass condition on its own.
  - Verification: harness plus a repo-wide self-scan.
  - Dependencies: Task 2. Scope: Medium.

- [ ] **Task 6: Add rhythm statistics to `prose_structure.py`.**
  Sentence-length coefficient of variation per paragraph, three-item list detection, and
  uniform paragraph endings. The variance check reuses the machinery `_sentences` and
  `_paragraphs` already provide.
  - Acceptance: variance rule fires on the AI corpus rows and not on the human rows at
    the 0.902 separation the spike measured.
  - Acceptance: three-item list rule ships at observe, since technical writing uses them.
  - Verification: harness.
  - Dependencies: Task 5. Scope: Medium.

### Checkpoint: Rules complete
- [ ] All 98 stop-slop patterns map to a rule or to a written reason for omission.
- [ ] Repo self-scan produces no new blocking finding.

### Phase 4: Surfaces and gating

- [ ] **Task 7: Per-surface rule gates.**
  `rule_gates` accepts either a state or a mapping of surface to state. Absent surface
  falls back to the plain state, so every existing config keeps working.
  - Acceptance: `config.py` resolves both forms, and an unknown surface name is ignored
    rather than raising.
  - Acceptance: `config_seal` blocks a write that gates a rule off across every surface.
  - Verification: full suite plus new tests for the eight escape shapes.
  - Dependencies: Task 4. Scope: Medium.

- [ ] **Task 8: Scan commit message bodies in `pre_commit`.**
  Structural rules only at enforce. The adverb, extreme and passive rules stay off here,
  because 235 adverb hits across 200 commits means every commit would block.
  - Acceptance: a commit body carrying a binary contrast blocks.
  - Acceptance: the last 200 commit bodies produce zero blocking findings.
  - Verification: replay the real git log through the gate.
  - Dependencies: Task 7. Scope: Medium.

- [ ] **Task 9: Apply the rules to comments and docstrings.**
  Structural rules at enforce. Word-level rules off, because they collide with the
  mandated WHY comment style.
  - Acceptance: no rule fires on this repo existing comments.
  - Verification: repo self-scan.
  - Dependencies: Task 7. Scope: Small.

### Phase 5: Report metric

- [ ] **Task 10: Add the slop score to the report.**
  Five dimensions, computed from marker density, sentence variance, formulaic density and
  hapax ratio. Printed, never gated.
  - Acceptance: no gate path reads the score.
  - Acceptance: the score appears in the report for a scanned prose file.
  - Verification: full suite, plus a test asserting the score cannot block.
  - Dependencies: Task 6. Scope: Small.

### Phase 6: Calibration

- [ ] **Task 11: Assign every rule its gate state from measured precision.**
  Enforce at 0.90 precision or better on that surface, observe between 0.70 and 0.90, and
  off below 0.70 with the number recorded next to the rule.
  - Acceptance: every entry in `rule_gates` carries its measured precision in a comment.
  - Acceptance: no rule enforces on a surface where it was not measured.
  - Acceptance: no rule enforces on the evidence of a single corpus, per D6.
  - Verification: harness output matches the shipped states.
  - Dependencies: Tasks 8, 9, 10. Scope: Medium.

- [ ] **Task 13: German markers, after the English release ships.**
  Build a German marker list the way sloptotal built its Spanish one, and calibrate it
  against German text before any German rule leaves observe. Kept out of Tasks 3 and 11
  because the corpora on disk are English and a German rule would ship with no measured
  precision at all.
  - Acceptance: German rules ship at observe until a German corpus exists.
  - Acceptance: the existing `anglizismen` skill is checked for overlap before any new
    German rule is written.
  - Dependencies: Task 12. Scope: Medium.

- [ ] **Task 12: Self-scan and release.**
  - Acceptance: `agent-discipline` scan of this repo produces zero new blocking findings.
  - Acceptance: pylint 10.00, suite green on Python 3.11, 3.12 and 3.13 in CI.
  - Verification: CI run green before any version bump.
  - Dependencies: Task 11. Scope: Small.

### Checkpoint: Complete
- [ ] Coverage measured again with the Phase 0 probe, reported as a number out of 98.
- [ ] CI green on all three Python versions.

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Every corpus is biased, and the document corpus is 92 rows of student essay | High | Report the sample size and the bias next to every precision figure. No rule enforces on one corpus alone, per D6. |
| A rule that never fires looks safe and is merely unmeasured | High | D8 requires a true positive count above zero before any rule enforces. Silence disqualifies a rule rather than clearing it. |
| A finding a reader cannot verify trains the reader to ignore the tool | High | D7 keeps every reported claim anchored to a real line, and density never speaks without citing the markers under it. |
| The sentence corpus human class is famous aphorisms, not ordinary prose | Medium | Use it only to score line-anchored rules, where the question is whether a sharp phrase appears. Never use it for density or variance. |
| Hapax ratio scored 0.960 but runs opposite to the sloptotal calibration | Medium | Treat it as a report metric in Task 10 only. No gate reads it until a second corpus agrees. |
| Word-level rules attack the mandated WHY comment style | High | Per-surface gates in Task 7, and the comment surface ships with word-level rules off. |
| Per-surface gates open a new config escape route | High | Task 7 extends `config_seal` in the same commit, with the eight escape shapes tested. |
| Rules fire on ADW own documentation | Medium | Task 5 and Task 9 both gate on a zero-hit repo self-scan. |
| `scanner.py` and `batch.py` already carry file-length warnings | Low | New rules land in new modules, and Task 4 asserts `scanner.py` does not grow. |

## Open Questions

None outstanding. The line-anchoring question is settled by D7: density cites the markers
that produced it, each at its own line, so no finding needs a file scope and `Finding`
keeps its `line >= 1` guarantee.
