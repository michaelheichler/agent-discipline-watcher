# German vote separation (T-009 spike)

**The shipped 4 plus 4 vote does not separate German violating sentences from clean ones.**

It flags most machine-written sentences and close to half of human sentences, whatever the rule.

Only `de_comparative_framing` separates its pattern from same-source near misses.

No rule changes state. All 25 stay at observe until T-010.

## Setup

1. Exemplars come from `hooks/lib/pattern_exemplars_de.jsonl`, built by `evals/build_pattern_exemplars_de.py`.
2. The violating side comes from `evals/pattern_labels_de.jsonl`. Each label names a line of `corpus_ai_sentences_de.jsonl`.
3. `evals/pattern_candidates_de.py` orders each rule's candidates by seed 20261001. The labels cover a prefix of that order, and the script refuses labels that skip a candidate.
4. One labeler, Claude Opus 5.5, labeled 570 candidates by hand against the catalog definitions on 2026-10-01. No second rater checked them.
5. A rule ships a violating side only with 4 or more violating labels. The first 4 in label order become exemplars.
6. `evals/qualify_embeddings_de.py` runs the vote on the local LFM2.5 server, started through the ADW lease. It writes `evals/qualification_de.json`.

## Three query sets per rule

1. Held-out violating. Labeled violating sentences that did not become exemplars.
2. Near-miss clean. Labeled clean sentences from the same trigger and the same models.
3. Human clean. 40 random human sentences, shared by every rule, none of them an exemplar.

Each query votes among the rule's 8 shipped exemplars, the same ranking `pattern_semantic` uses. The sweep covers 1, 3, 5 and 7 neighbours. Production uses 5.

A fourth measure, the labeled pool, puts every labeled row of a rule into the neighbour set and leaves one out at a time. It asks whether the model separates the pattern at all, apart from the four-exemplar limit.

## Results at 5 neighbours

Cells read flagged of total.

| # | rule | violating side | held-out violating | near-miss clean | human clean | pool violating | pool clean | reading |
|---|------|----|----|----|----|----|----|----|
| 6 | de_passive_voice | yes | 4/4 | 15/23 | 22/40 | 0/8 | 3/27 | no separation |
| 8 | de_stock_phrase | yes | 8/9 | 13/19 | 11/40 | 5/13 | 5/23 | weak |
| 12 | de_unexplained_foreign_word | yes | 3/4 | 19/24 | 21/40 | 0/8 | 2/28 | no separation |
| 15 | de_unbacked_superlative | yes | 4/5 | 11/23 | 20/40 | 2/9 | 1/27 | no separation |
| 25 | de_dichotomy_template | yes | 5/5 | 4/6 | 19/40 | 9/9 | 6/10 | weak, small sample |
| 27 | de_shallow_participle | no | | | | | | silent |
| 28 | de_vague_authority | yes | 9/10 | 16/18 | 22/40 | 5/14 | 8/22 | no separation |
| 29 | de_false_range | yes | 1/3 | 14/33 | 14/40 | 1/7 | 1/37 | no separation |
| 31 | de_synonym_rotation | no | | | | | | silent |
| 33 | de_fake_analysis_tail | yes | 4/5 | 14/23 | 19/40 | 0/9 | 8/27 | no separation |
| 34 | de_comparative_framing | yes | 5/5 | 28/38 | 21/40 | 6/9 | 3/42 | separates in the pool |
| 38 | de_register_collapse | yes | 1/1 | 24/27 | 24/40 | 0/5 | 2/31 | no separation |
| 47 | de_broken_link | no | | | | | | silent |
| 48 | de_fabricated_citation | no | | | | | | silent |
| 52 | de_style_shift | no | | | | | | silent |
| 56 | de_fragment_heading | no | | | | | | silent |
| 57 | de_rhetorical_question | yes | 2/4 | 4/8 | 13/40 | 1/8 | 5/12 | no separation |
| 62 | de_markerless_closer | yes | 5/6 | 18/21 | 16/40 | 3/10 | 6/25 | no separation |
| 64 | de_retroactive_nuance | no | | | | | | silent |
| 66 | de_epistemic_miscalibration | yes | 1/2 | 25/34 | 13/40 | 0/6 | 0/38 | no separation |
| 67 | de_gap_filling_speculation | yes | 6/9 | 15/19 | 19/40 | 0/13 | 8/23 | no separation |
| 68 | de_invented_anecdote | no | | | | | | silent |
| 69 | de_false_agency | no | | | | | | silent |
| 71 | de_citation_mismatch | no | | | | | | silent |
| 73 | de_empty_standard_section | yes | 3/4 | 6/8 | 17/40 | 5/8 | 4/12 | weak |

Totals over the 15 voting rules at 5 neighbours.

1. Held-out violating flagged 61 of 76, 0.80.
2. Near-miss clean flagged 226 of 324, 0.70.
3. Human clean flagged 271 of 600 rule votes, 0.45, on the same 40 sentences.

The other neighbour counts do not change the picture. The full sweep sits in `evals/qualification_de.json`.

## Why the vote fails

**The shipped vote sorts by source, not by pattern.**

1. Every violating exemplar is machine text, mostly COLING news.
2. Every clean exemplar is human encyclopedia or literature text, drawn without the rule's trigger words.
3. A query that reads like generated news lands near the violating side, pattern or not. That explains 0.70 on near misses.
4. The English benchmark drew its clean side half from human and half from assistant text for this reason, see `evals/README.md`.
5. Four exemplars per side is also thin. The English vote reads 40 per side.

The labeled pool removes the source gap, since both classes there come from the same models. With the gap gone, 12 of 15 rules flag at most 38 percent of their violating rows. Only `de_dichotomy_template`, `de_comparative_framing` and `de_empty_standard_section` go higher, and `de_dichotomy_template` also flags 6 of its 10 clean rows.

Leave-one-out on the 8 shipped exemplars carries a quirk. At 7 neighbours the held-out row always faces 4 of the other class and 3 of its own, so it always loses. The record keeps those rows, and this note marks them as unusable.

## Rules left silent

| # | rule | candidates labeled | violating | reason |
|---|------|----|----|----|
| 27 | de_shallow_participle | 5 of 5 | 0 | The participle tail, `gewährleistend` and the like, never occurs in the corpus. |
| 31 | de_synonym_rotation | 16 of 123 | 0 | One sentence shows a plain anaphor. The rotation needs two sentences. |
| 47 | de_broken_link | 5 of 5 | 0 | All five links point at one blog and answered HTTP 200 on 2026-10-01. |
| 48 | de_fabricated_citation | 16 of 84 | 0 | 12 stay undecided, since the news is generated or no catalog check ran. 4 checked out as real. |
| 52 | de_style_shift | none | 0 | The sentence corpus has no paragraph boundaries. |
| 56 | de_fragment_heading | none | 0 | No corpus keeps headings or sentences under 8 words. |
| 64 | de_retroactive_nuance | 41 of 41 | 1 | `eigentlich` and `genauer` almost always carry their plain meaning. |
| 68 | de_invented_anecdote | 6 of 6 | 3 | Few staged first-person stories in news and chat answers. |
| 69 | de_false_agency | 18 of 18 | 1 | Government and party subjects are people, so they pass. |
| 71 | de_citation_mismatch | none | 0 | Judging it needs the cited source text, which no corpus holds. |

A silent rule never votes, since `pattern_semantic.candidates_for` skips a rule with no violating exemplar.

## Multi-sentence rules

1. **31 de_synonym_rotation.** The spike gives no support for a sentence vote. The one rotation found, `der Konzern` then `die Japaner` in COLING document 50095, spans two sentences, and each sentence alone reads clean.
2. **47 de_broken_link.** No support. A dead link is a network fact. Two sentences with the same wording can carry a live and a dead link.
3. **48 de_fabricated_citation.** No support. Fabrication shows only against a catalog or a resolver. The wording of a real and an invented citation is the same.
4. **52 de_style_shift.** No support and no measurement. The voice change lives between paragraphs, and one sentence cannot show it.
5. **56 de_fragment_heading.** No support. `pattern_semantic` skips sentences under 4 words, and the catalog example `Geschwindigkeit zählt.` has 2. The corpora also drop headings.
6. **73 de_empty_standard_section.** It has a violating side, labeled from sentence-level filler such as `Zusammenfassend ist festzuhalten`. The vote flags 3 of 4 held-out rows but also 6 of 8 near misses. The pool reaches 5 of 8 against 4 of 12. The heading itself never reaches the vote. The spike gives weak support at best, and the rule overlaps the STATIC rules 24 and 55.

## What T-010 inherits

1. 15 rules carry 4 violating and 4 clean exemplars with source and corpus row.
2. 10 rules stay silent, listed above with reasons.
3. The shipped vote would send about 70 percent of machine-written near misses and 45 percent of human sentences to the judge. The judge decides every row, so the cost is judge calls, not false blocks.
4. `pattern_labels_de.jsonl` already holds 417 clean labels from the same AI sources. A clean side drawn from them would test the source gap directly.
