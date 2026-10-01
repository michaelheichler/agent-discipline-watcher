# German vote separation (T-009 spike)

**The embedding vote does not separate German violating sentences from clean ones, with either clean side.**

A mixed clean side, half human and half machine near misses, lowers the near-miss alarm rate from 0.70 to 0.63. It raises the human alarm rate from 0.45 to 0.51.

The trigger filter alone admits under 1 percent of human sentences for 12 of 15 rules. The vote admits about half.

A blind second rater agrees with the first at Cohen's kappa 0.52.

No rule changes state. All 25 stay at observe until T-010.

## Setup

1. Exemplars come from `hooks/lib/pattern_exemplars_de.jsonl`, built by `evals/build_pattern_exemplars_de.py`.
2. The violating side comes from `evals/pattern_labels_de.jsonl`. Each label names a line of `corpus_ai_sentences_de.jsonl`.
3. `evals/pattern_candidates_de.py` orders each rule's trigger matches by seed 20261001. The labels cover a prefix of that order, and the script refuses labels that skip a candidate.
4. The first rater, Claude Opus 5.5, labeled 570 candidates by hand against the catalog definitions on 2026-10-01. It saw the sentence before and after each candidate.
5. A rule ships a violating side only with 4 or more violating labels. The first 4 in label order become exemplars.
6. `evals/qualify_embeddings_de.py` runs the vote on the local LFM2.5 server, started through the ADW lease. It writes `evals/qualification_de.json`.

## Query sets per rule

1. Held-out violating. Labeled violating sentences that did not become exemplars.
2. Near-miss clean. Labeled clean sentences from the same trigger and the same models, minus any that became exemplars.
3. Human clean. 40 random human sentences, shared by every rule, none of them an exemplar.

Each query votes among the rule's 8 shipped exemplars, the same ranking `pattern_semantic` uses. The sweep covers 1, 3, 5 and 7 neighbours. Production uses 5.

The labeled pool puts every labeled row of a rule into the neighbour set and leaves one out at a time. It asks whether the model separates the pattern at all, apart from the four-exemplar limit.

## Two clean sides

1. Human-only, the first run. Two encyclopedia and two literature sentences per rule, drawn without the rule's trigger words.
2. Mixed, the current build. Two labeled clean near misses from the AI corpus, drawn by seed, plus one encyclopedia and one literature sentence. Rules with fewer than two labeled near misses keep four human sentences. That applies to `de_style_shift`, `de_fragment_heading` and `de_citation_mismatch`, all silent.

Totals over the 15 voting rules at 5 neighbours.

| clean side | held-out violating | near-miss clean | human clean |
|----|----|----|----|
| human-only, first run | 61/76, 0.80 | 226/324, 0.70 | 271/600, 0.45 |
| mixed, current | 60/76, 0.79 | 185/294, 0.63 | 303/600, 0.51 |

The near-miss total shrinks by 30 rows because those rows became clean exemplars. The human column counts 15 rule votes over the same 40 sentences.

## Results per rule, mixed clean side, 5 neighbours

Cells read flagged of total.

| # | rule | held-out violating | near-miss clean | human clean | pool violating | pool clean | reading |
|---|------|----|----|----|----|----|----|
| 6 | de_passive_voice | 2/4 | 14/21 | 26/40 | 0/8 | 3/25 | no separation |
| 8 | de_stock_phrase | 8/9 | 7/17 | 18/40 | 5/13 | 5/21 | weak |
| 12 | de_unexplained_foreign_word | 2/4 | 14/22 | 16/40 | 0/8 | 1/26 | no separation |
| 15 | de_unbacked_superlative | 4/5 | 7/21 | 16/40 | 2/9 | 1/25 | no separation |
| 25 | de_dichotomy_template | 4/5 | 2/4 | 14/40 | 9/9 | 6/8 | weak, small sample |
| 28 | de_vague_authority | 10/10 | 15/16 | 15/40 | 5/14 | 9/20 | no separation |
| 29 | de_false_range | 2/3 | 20/31 | 22/40 | 1/7 | 2/35 | no separation |
| 33 | de_fake_analysis_tail | 4/5 | 9/20 | 23/40 | 0/9 | 6/24 | no separation |
| 34 | de_comparative_framing | 5/5 | 26/36 | 18/40 | 6/9 | 3/40 | separates in the pool |
| 38 | de_register_collapse | 1/1 | 17/25 | 29/40 | 0/5 | 2/29 | no separation |
| 57 | de_rhetorical_question | 2/4 | 4/6 | 17/40 | 3/8 | 5/10 | no separation |
| 62 | de_markerless_closer | 6/6 | 15/20 | 26/40 | 3/10 | 6/24 | no separation |
| 66 | de_epistemic_miscalibration | 2/2 | 19/32 | 22/40 | 0/6 | 0/36 | no separation |
| 67 | de_gap_filling_speculation | 5/9 | 12/17 | 26/40 | 0/13 | 9/21 | no separation |
| 73 | de_empty_standard_section | 3/4 | 4/6 | 15/40 | 5/8 | 5/10 | weak |

The other 10 rules stay silent, listed further down.

## Results per rule, human-only clean side, first run

Kept for comparison. Same layout, 5 neighbours.

| # | rule | held-out violating | near-miss clean | human clean | pool violating | pool clean |
|---|------|----|----|----|----|----|
| 6 | de_passive_voice | 4/4 | 15/23 | 22/40 | 0/8 | 3/27 |
| 8 | de_stock_phrase | 8/9 | 13/19 | 11/40 | 5/13 | 5/23 |
| 12 | de_unexplained_foreign_word | 3/4 | 19/24 | 21/40 | 0/8 | 2/28 |
| 15 | de_unbacked_superlative | 4/5 | 11/23 | 20/40 | 2/9 | 1/27 |
| 25 | de_dichotomy_template | 5/5 | 4/6 | 19/40 | 9/9 | 6/10 |
| 28 | de_vague_authority | 9/10 | 16/18 | 22/40 | 5/14 | 8/22 |
| 29 | de_false_range | 1/3 | 14/33 | 14/40 | 1/7 | 1/37 |
| 33 | de_fake_analysis_tail | 4/5 | 14/23 | 19/40 | 0/9 | 8/27 |
| 34 | de_comparative_framing | 5/5 | 28/38 | 21/40 | 6/9 | 3/42 |
| 38 | de_register_collapse | 1/1 | 24/27 | 24/40 | 0/5 | 2/31 |
| 57 | de_rhetorical_question | 2/4 | 4/8 | 13/40 | 1/8 | 5/12 |
| 62 | de_markerless_closer | 5/6 | 18/21 | 16/40 | 3/10 | 6/25 |
| 66 | de_epistemic_miscalibration | 1/2 | 25/34 | 13/40 | 0/6 | 0/38 |
| 67 | de_gap_filling_speculation | 6/9 | 15/19 | 19/40 | 0/13 | 8/23 |
| 73 | de_empty_standard_section | 3/4 | 6/8 | 17/40 | 5/8 | 4/12 |

## Why the vote fails

**Mixing the clean side did not fix it, so source was not the only cause.**

1. With a human-only clean side, machine-written near misses landed on the violating side 70 percent of the time.
2. With the mixed side that drops to 63 percent, while human sentences now land there 51 percent of the time.
3. The labeled pool has no source gap, since both classes come from the same models. There, 12 of 15 rules flag at most 38 percent of their violating rows.
4. Only `de_comparative_framing` separates in the pool, 6 of 9 violating against 3 of 40 clean. `de_dichotomy_template` flags 9 of 9 violating but also 6 of 8 clean.
5. The model places sentences by topic and genre. Four exemplars per side cannot outvote that. The English vote reads 40 per side.

Leave-one-out on the 8 shipped exemplars carries a quirk. At 7 neighbours the held-out row always faces 4 of the other class and 3 of its own, so it always loses. The record keeps those rows, and this note marks them as unusable.

## Trigger stage

The trigger stage is the regex filter in `pattern_candidates_de.py` that drew the candidates. Every labeled row passes it by construction, so it flags 100 percent of both labeled classes. Its share of violating rows among the labeled candidates is the precision a judge would face behind it.

This setup cannot measure trigger recall. A violating sentence without a trigger word never reached the labels.

| # | rule | labeled violating | labeled clean | violating share | human queries flagged | human corpus flagged |
|---|------|----|----|----|----|----|
| 6 | de_passive_voice | 8 | 24 | 0.25 | 12/40 | 4009/28000 |
| 8 | de_stock_phrase | 13 | 19 | 0.41 | 0/40 | 49/28000 |
| 12 | de_unexplained_foreign_word | 8 | 24 | 0.25 | 0/40 | 25/28000 |
| 15 | de_unbacked_superlative | 9 | 23 | 0.28 | 3/40 | 1510/28000 |
| 25 | de_dichotomy_template | 9 | 7 | 0.56 | 1/40 | 38/28000 |
| 28 | de_vague_authority | 14 | 18 | 0.44 | 0/40 | 173/28000 |
| 29 | de_false_range | 7 | 33 | 0.18 | 2/40 | 262/28000 |
| 33 | de_fake_analysis_tail | 9 | 23 | 0.28 | 1/40 | 149/28000 |
| 34 | de_comparative_framing | 9 | 38 | 0.19 | 0/40 | 37/28000 |
| 38 | de_register_collapse | 5 | 27 | 0.16 | 0/40 | 86/28000 |
| 57 | de_rhetorical_question | 8 | 8 | 0.50 | 0/40 | 27/28000 |
| 62 | de_markerless_closer | 10 | 22 | 0.31 | 0/40 | 423/28000 |
| 66 | de_epistemic_miscalibration | 6 | 34 | 0.15 | 0/40 | 94/28000 |
| 67 | de_gap_filling_speculation | 13 | 19 | 0.41 | 0/40 | 123/28000 |
| 73 | de_empty_standard_section | 8 | 8 | 0.50 | 0/40 | 21/28000 |

Reading for T-010.

1. On human text the trigger admits under 1 percent for 12 of 15 rules. The vote admits 35 to 73 percent.
2. Passive, superlative and markerless closer are the exceptions, at 14.3, 5.4 and 1.5 percent of the human corpus.
3. Among machine-written trigger matches, 15 to 56 percent are violating. The judge has to remove the rest in either design.
4. On this data, trigger plus judge sends far fewer rows to the judge than vote plus judge, at the same recall on the labeled rows.
5. The open risk is trigger recall, which this setup cannot see.

## Second rater

A blind Claude Sonnet 5 rater labeled the same 570 candidates in 16 batches. It saw only the rule title, the German definition, the required fix, the German rubric and the sentence. It saw neither the first labels nor the neighbouring sentences. `evals/second_rater_de.py` exported the blind items, merged the answers into `evals/pattern_labels_de_sonnet.jsonl` and computed the agreement. The first labels stay unchanged.

1. Overall Cohen's kappa is 0.5236 over 553 pairs where both raters decided. They agree on 434.
2. The second rater calls 222 rows violating, the first 141.
3. Of 119 disagreements on decided rows, 100 are first clean and second violating, 19 the reverse.
4. Of the 60 shipped violating exemplars, the second rater calls 56 violating and 4 clean. Of the 44 shipped machine-written clean exemplars, it calls 30 clean, 12 violating and 2 undecided.

| # | rule | kappa | agree / pairs |
|---|------|----|----|
| 6 | de_passive_voice | 0.69 | 28/32 |
| 8 | de_stock_phrase | 0.03 | 16/32 |
| 12 | de_unexplained_foreign_word | 0.26 | 19/32 |
| 15 | de_unbacked_superlative | 0.78 | 29/32 |
| 25 | de_dichotomy_template | 0.63 | 13/16 |
| 27 | de_shallow_participle | none, one class | 5/5 |
| 28 | de_vague_authority | 0.69 | 27/32 |
| 29 | de_false_range | 0.92 | 39/40 |
| 31 | de_synonym_rotation | 0.00 | 15/16 |
| 33 | de_fake_analysis_tail | 0.65 | 27/32 |
| 34 | de_comparative_framing | 0.40 | 33/47 |
| 38 | de_register_collapse | 0.36 | 24/32 |
| 47 | de_broken_link | none, second rater undecided on all | 0/0 |
| 48 | de_fabricated_citation | none, one class | 4/4 |
| 57 | de_rhetorical_question | 0.38 | 11/16 |
| 62 | de_markerless_closer | 0.31 | 20/32 |
| 64 | de_retroactive_nuance | -0.03 | 38/41 |
| 66 | de_epistemic_miscalibration | 0.48 | 34/40 |
| 67 | de_gap_filling_speculation | 0.69 | 27/32 |
| 68 | de_invented_anecdote | 0.33 | 4/6 |
| 69 | de_false_agency | -0.11 | 7/18 |
| 71 | de_citation_mismatch | no candidates | 0/0 |
| 73 | de_empty_standard_section | 0.75 | 14/16 |

Agreement reaches 0.6 or more for passive, superlative, dichotomy, vague authority, false range, analysis tail, speculation and empty section. It stays low for stock phrase, foreign word, false agency and retroactive nuance, where the raters read the definition itself differently.

1. Stock phrase. The second rater counts `ins Leben rufen`, `unter Beweis stellen` and `nach wie vor` as worn phrases. The first rater counts them as plain news German.
2. Foreign word. The second rater flags established loanwords such as `Tool`, `Feature` and `Community`. N-006 Q21 lets them pass.
3. False agency. The second rater flags `Die Regierung plant`. The first rater reads a government as people.
4. Rhetorical question and markerless closer. The first rater used the next sentence and document end. The second rater had only the sentence.

### Disagreement rows

Line numbers point into `corpus_ai_sentences_de.jsonl`.

| rule | first violating, second clean | first clean, second violating | undecided on one side |
|------|----|----|----|
| de_broken_link | | | 4494, 4468, 4459, 4458, 4477 (second undecided) |
| de_comparative_framing | | 20187, 15794, 16809, 15868, 13057, 20346, 17842, 14587, 6581, 20115, 9211, 19808, 2315, 14107 | |
| de_dichotomy_template | 14570, 13667 | 10257 | |
| de_empty_standard_section | | 10942, 3856 | |
| de_epistemic_miscalibration | 1587, 884 | 17411, 3845, 7914, 11845 | |
| de_fabricated_citation | | | 7837, 13181, 9505, 7797, 14779, 12984, 10204, 17950, 6531 (first undecided) |
| de_fake_analysis_tail | 13998 | 20445, 16542, 4880, 7281 | |
| de_false_agency | 2418 | 5589, 20790, 18113, 20964, 12986, 12191, 9612, 11109, 12631, 15723 | |
| de_false_range | | 19850 | |
| de_gap_filling_speculation | | 18467, 11148, 7835, 19605, 15557 | |
| de_invented_anecdote | 8943, 4439 | | |
| de_markerless_closer | 16771 | 15685, 5452, 4333, 3826, 734, 19056, 4530, 15695, 16305, 18879, 5022 | |
| de_passive_voice | 13671 | 7300, 15794, 17447 | |
| de_register_collapse | 15131 | 11348, 17965, 8568, 17095, 13167, 14520, 5988 | |
| de_retroactive_nuance | 11958 | 19885, 14531 | |
| de_rhetorical_question | | 5983, 1183, 5978, 5984, 14663 | |
| de_stock_phrase | 16933, 12946, 10256, 13096, 1784 | 15778, 20878, 16652, 15632, 9129, 16562, 4453, 15948, 18901, 979, 17246 | |
| de_synonym_rotation | | 13187 | |
| de_unbacked_superlative | 16384 | 35, 19064 | |
| de_unexplained_foreign_word | 17305 | 4616, 18286, 597, 14142, 5925, 9087, 8744, 14610, 1970, 13942, 1976, 1968 | |
| de_vague_authority | | 5096, 18332, 17998, 11479, 20033 | |

The four shipped violating exemplars the second rater calls clean are 16933 (stock phrase), 1587 (epistemic), 13998 (analysis tail) and 15131 (register).

Batching note. Batch boundaries overlapped once, so line 597 got two second-rater answers. Both say violating. A separate one-row batch rated line 15560, which the overlap had pushed out.

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

A silent rule never votes, since `pattern_semantic.candidates_for` skips a rule with no violating exemplar. The second rater would have given `de_false_agency` 10 more violating rows. That changes nothing here, because the first labels decide the exemplars.

## Multi-sentence rules

1. **31 de_synonym_rotation.** The spike gives no support for a sentence vote. The one rotation found, `der Konzern` then `die Japaner` in COLING document 50095, spans two sentences, and each sentence alone reads clean.
2. **47 de_broken_link.** No support. A dead link is a network fact. Two sentences with the same wording can carry a live and a dead link.
3. **48 de_fabricated_citation.** No support. Fabrication shows only against a catalog or a resolver. The wording of a real and an invented citation is the same.
4. **52 de_style_shift.** No support and no measurement. The voice change lives between paragraphs, and one sentence cannot show it.
5. **56 de_fragment_heading.** No support. `pattern_semantic` skips sentences under 4 words, and the catalog example `Geschwindigkeit zählt.` has 2. The corpora also drop headings.
6. **73 de_empty_standard_section.** It has a violating side, labeled from sentence-level filler such as `Zusammenfassend ist festzuhalten`. With the mixed clean side the vote flags 3 of 4 held-out rows and 4 of 6 near misses. The pool reaches 5 of 8 against 5 of 10. The heading itself never reaches the vote. The spike gives no real support, and the rule overlaps the STATIC rules 24 and 55.

## What T-010 inherits

1. 15 rules carry 4 violating and 4 clean exemplars with source and corpus row. The clean side is 2 human and 2 machine-written near misses.
2. 10 rules stay silent, listed above with reasons.
3. The vote with either clean side sends about half of all human sentences to the judge.
4. The trigger filter sends under 1 percent of human sentences for 12 of 15 rules, at an unknown recall.
5. Rater agreement on stock phrase, foreign word, false agency and retroactive nuance is too low to measure precision before the user settles those definitions.

## T-010 part C, trigger plus Luna judge

**No German rule reaches the 0.85 lower bound. All 14 measured rules stay at observe.**

The best lower bound is 0.55, for stock phrase. Every recommendation below reads observe.

### Sharper definitions

The four low-agreement rules now carry a German boundary in their rule module. It names what violates and what passes.

1. Stock phrase. Listed phrases and dead images violate, such as `ins Leben rufen` and `den Weg ebnen`. Fixed phrases without an image pass, such as `nach wie vor`. Funktionsverbgefüge pass, since another rule checks them.
2. Foreign word. Decision Q21 applies, as in humanizer-de. Technical terms, titles, names and established loanwords pass. In doubt, a single loanword counts as established.
3. False agency. humanizer-de pattern 70 applies. Only an abstract noun as decider violates. Governments, parties, companies and other groups of people pass.
4. Retroactive nuance. humanizer-de pattern 71 applies. Only a marker that repeats a claim without new content violates. `eigentlich` as a particle and `genauer` as a comparative pass.

Both raters relabeled only these four rules, 123 rows, blind and with the new wording. Rater 1 was Claude Opus 5.5 with the neighbouring sentences. Rater 2 was Claude Sonnet 5 with the sentence alone.

| rule | kappa before | kappa after | agree / pairs after |
|------|----|----|----|
| de_stock_phrase | 0.03 | 0.875 | 30/32 |
| de_unexplained_foreign_word | 0.26 | 1.0 | 32/32 |
| de_retroactive_nuance | -0.03 | none, both all clean | 41/41 |
| de_false_agency | -0.11 | 1.0 | 18/18 |

Overall kappa moves from 0.5236 to 0.6655, over 553 decided pairs.

Under Q21 only one foreign word sentence stays violating, `Anchor-Woman`. The rule loses its violating side and goes silent. False agency and retroactive nuance stay silent with 1 and 0 violating rows.

### Adjudication

A blind GPT-6 Luna subagent decided the 92 rows where the raters still disagreed. It saw the rule wording, the boundary, the German rubric and the neighbouring sentences. Two of three decided votes set the label, anything else stays undecided.

1. 25 rows became violating, 55 clean and 12 undecided.
2. The majority overturned rater 1 on 37 rows.
3. `evals/pattern_labels_de_adjudicated.jsonl` holds all 570 rows. The exemplar builder now draws from it.

### Runtime

A German SEMANTIC rule takes every German sentence its trigger matches. It no longer votes. The rows reach the Luna judge with the German rubric on the same journal route. The judge prompt now carries the rule definition and the boundary.

The trigger patterns moved from `evals/pattern_candidates_de.py` into the rule modules. The evals import them, so the draw and the hook read one source.

### Judged stage

`evals/measure_judge_stage_de.py` sends each rule's adjudicated candidates through `rule_prompt`, `request_for` and `LunaJudge.judge`, the request the Stop hook builds. It ran on 2026-10-01 against `gpt-5.6-luna`, in batches of 20. It writes `evals/judge_stage_de.json`.

The measurement leaves out the shipped exemplars, since the judge reads them as examples. n counts the remaining decided candidates. Recall counts only violating rows that passed the trigger. The trigger recall stays unknown.

| # | rule | n | violating | confirmed | precision | lower bound | recall | recommendation |
|---|------|----|----|----|----|----|----|----|
| 6 | de_passive_voice | 26 | 7 | 18 | 0.39 | 0.20 | 1.00 | observe |
| 8 | de_stock_phrase | 26 | 12 | 15 | 0.80 | 0.55 | 1.00 | observe |
| 15 | de_unbacked_superlative | 26 | 6 | 12 | 0.50 | 0.25 | 1.00 | observe |
| 25 | de_dichotomy_template | 10 | 4 | 0 | none | 0.00 | 0.00 | observe |
| 28 | de_vague_authority | 26 | 13 | 13 | 0.77 | 0.50 | 0.77 | observe |
| 29 | de_false_range | 34 | 3 | 4 | 0.75 | 0.30 | 1.00 | observe |
| 33 | de_fake_analysis_tail | 26 | 6 | 8 | 0.75 | 0.41 | 1.00 | observe |
| 34 | de_comparative_framing | 41 | 7 | 18 | 0.39 | 0.20 | 1.00 | observe |
| 38 | de_register_collapse | 26 | 1 | 9 | 0.11 | 0.02 | 1.00 | observe |
| 57 | de_rhetorical_question | 10 | 5 | 5 | 0.60 | 0.23 | 0.60 | observe |
| 62 | de_markerless_closer | 26 | 7 | 14 | 0.50 | 0.27 | 1.00 | observe |
| 66 | de_epistemic_miscalibration | 34 | 1 | 9 | 0.11 | 0.02 | 1.00 | observe |
| 67 | de_gap_filling_speculation | 26 | 14 | 20 | 0.70 | 0.48 | 1.00 | observe |
| 73 | de_empty_standard_section | 10 | 5 | 4 | 0.75 | 0.30 | 0.60 | observe |

Reading.

1. The judge over-calls. It confirms more rows than are violating for 10 of 14 rules.
2. Dichotomy confirms nothing, so it records no precision and stays silent.
3. A perfect run needs 22 confirmed rows to reach a lower bound of 0.85. Most rules hold fewer violating rows than that.
4. The rebuilt `hooks/lib/pattern_exemplars_de.json` records the point precision for 13 rules. Those rules now report at observe. No gate changed.
