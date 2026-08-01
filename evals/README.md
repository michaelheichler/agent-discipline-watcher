# Evaluations

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
