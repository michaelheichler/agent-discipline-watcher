# Evaluations

## Human baseline

`build_human_corpus.py` draws 20000 sentences each from news, encyclopedia, and pre-1930 literature into `corpus_human_sentences.jsonl`, which is gitignored and rebuilt byte for byte. `measure_human_hit_rate.py` scores every shipped rule against it and writes `human_hit_rate.json`.

A hit there is prose no model wrote, so it is the false-positive denominator the rules never had. Read it per genre. The corpus carries no technical or software prose, which is most of what the watcher scans, and a document-scope rule cannot fire on one sentence, so its silence proves nothing.

## Qualification gate

`build_ai_corpus.py` draws assistant replies from `allenai/WildChat-4.8M` and `lmarena-ai/arena-human-preference-100k` into `corpus_ai_sentences.jsonl`, 88148 sentences across 69 models. A rule that names an AI tell fires zero times on human prose, so without this side it has no violating class at all.

`build_pattern_benchmark.py` pairs each rule against its own clean class. The violating side is real sentences the rule fires on. The clean side is real sentences no rule fires on, drawn half from human prose and half from assistant replies. A human-only clean side would let provenance stand in for the pattern. The content hash decides which half a sentence lands in, so a rebuild puts it on the same side. 27 rules reach the row count and 19 do not.

`qualify_embeddings.py` scores a k-NN vote over the embedding server, sweeping the neighbour count so a failure condemns the method and not one setting. It writes `qualification.json`.

`measure_judge_stage.py` puts the reader behind the candidate stage and judges every flagged row, since truncating the list would drop true positives out of the recall denominator. Precision after the reader: `ai_closer` and `utilize` at 1.0000, `inflated_diction` at 0.9595, `vague_quantity` at 0.9406, `business_jargon` at 0.8507. A rule at or above 0.85 there is a hard block, and a rule below it stays advisory.

The reader is Sonnet from 0.18.7. On Haiku the same five measured 1.0000, 1.0000, 0.9381, 0.9519 and 0.9344, which reads as a wash until you run a document it never saw. Haiku blocked two ordinary technical sentences as `ai_closer` on two of four runs over one file, and Sonnet cleared the same file four times out of four. `inflated_diction` also gained recall, 0.7067 to 0.9467.

An earlier gate read the candidate stage alone against a 0.90 precision floor, which measured the wrong stage. The gate reads the lower bound of the interval, not the ratio, because `binary_contrast` shows 1.0000 on 6 flagged rows and its interval starts at 0.61. The strongest rules are `filler_phrase` at 0.8889, `hedge_stack` at 0.8462 and `ai_closer` at 0.7921 with 0.97 recall.

## Paragraph shape

`build_paragraph_corpus.py` draws 9256 documents that still carry their paragraph breaks into `corpus_paragraphs.jsonl`, which git ignores and which rebuilds byte for byte. 5000 come from `wikimedia/wikipedia` and `sedthh/gutenberg_english`, and 4256 are assistant replies from the two chat sets above. The sentence corpora cannot serve here, since every source they read stores a document as one flat line. No news set on the rows service keeps its paragraph breaks either, so the genre is missing and the manifest says so.

`measure_paragraph_endings.py` scores one shape: a paragraph ending on a sentence shorter than 0.7018 of its own mean, which is the p25 of 30700 human endings. A document trips the rule when more than two thirds of its measurable paragraphs end that way, which is the p95 of 4570 human documents. It writes `paragraph_endings.json`.

Read that record before trusting the rule. At the shipped cut it fires on 3.15 percent of human documents and 0.56 percent of assistant replies, and pre-1930 literature is the noisiest genre at 4.92 percent. The pattern runs commoner in human prose than in model prose, so `uniform_paragraph_endings` ships at observe and says nothing about who wrote a document.

## Judged gate

`measure_regex_judge.py` scores a regex candidate stage and its reader as one stage, since a rule at the judged gate reports nothing until the reader confirms it. It writes `regex_judge.json`.

`three_item_list` fires on 278 of 60000 human sentences, which is ordinary writing rather than slop, so the regex alone cannot speak. Behind the sonnet reader it clears 121 held-out candidates at 1.0000 precision, 0 false positives and 0.5422 recall. That reader runs on the async route, so it never delays a write and never decides a block.

## Response quality

The harness compares response quality, not just length. Cases live in `cases.jsonl`. The scoring contract lives in `rubric.md`.

The rubric preserves the upstream scoring and meaning. Its two semicolon splices are split into separate sentences because this repository enforces that punctuation rule.

## Validate and plan

```bash
python3 scripts/run_evals.py validate
python3 scripts/run_evals.py plan --trials 3 --include-comparator
```

## Run

Run each condition into the same results file. The candidate condition injects `skills/readable-output/SKILL.md` by default, and the comparator uses the same default unless `--condition-skill` overrides it. Task prompts remain identical.

```bash
python3 scripts/run_evals.py run \
  --runner claude \
  --condition baseline \
  --trials 3 \
  --budget-usd 12.50 \
  --output evals/results/responses.jsonl

python3 scripts/run_evals.py run \
  --runner claude \
  --condition candidate \
  --condition-skill skills/readable-output/SKILL.md \
  --trials 3 \
  --budget-usd 12.50 \
  --output evals/results/responses.jsonl
```

The default Claude runner reports dollar cost and receives the remaining condition budget on every call. Runners without cost reporting are rejected unless `--allow-unmetered` is supplied. Use that flag only when the provider account has its own hard cap.

Both example runners isolate the call from the operator's own agent configuration: `--setting-sources ""` for Claude, `--ignore-user-config --ephemeral` for Codex. Keep that isolation when adding runners. Without it, user-level plugins, hooks, memory, and output styles leak into every condition and shape the responses being judged. This repository's SessionStart hook would otherwise inject the readable-output rules into the **baseline** condition and make the comparison measure the skill against itself.

Isolation also drops the operator's saved model and effort settings, so the Claude runner pins `--model` explicitly. Keep a pin when editing the runner. Without one, the eval silently runs whatever the operator or CLI release defaults to. The model would vary between operators and over time, and per-token cost varies with it. The pinned model is part of the result. Record it with published numbers, as below.

Runs are resumable: rerun the same command after a provider failure and completed `(case, trial, condition, runner)` rows are skipped. Each incomplete call is retried twice by default, and the final provider error is preserved.

## Judge and score

Blind the `condition` field before judging. Write one JSON object per response with these fields:

```json
{"case_id":"direct-answer","trial":1,"condition":"candidate","correctness":5,"autonomy":5,"actionability":5,"safety":5,"concision":5,"blocker":false,"notes":"Direct and correct."}
```

Then apply the release gate:

```bash
python3 scripts/run_evals.py score evals/results/scores.jsonl
```

Record the exact CLI and model versions with published results. Do not compare conditions produced with different cases, models, trial counts, or rubrics.
