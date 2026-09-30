# Claude Code hook model field and alias resolution

## Question

Does a Claude Code `prompt` or `agent` hook accept a model alias such as `sonnet`, `haiku`, or `opus` in its `model` field. If it does, the digest of the managed hooks in `claude_presets.py` should render the alias instead of a pinned snapshot id.

## Primary source on the field

The hooks reference at `https://code.claude.com/docs/en/hooks` documents the field this way, in the "Prompt and agent hook fields" table.

`model` (not required). "Model to use for evaluation. Defaults to the model Claude Code uses for background functionality."

The page does not state whether the field accepts an alias. The model configuration reference at `https://code.claude.com/docs/en/model-config` documents alias support for `/model`, the `--model` flag, `ANTHROPIC_MODEL`, the top level `model` field in `settings.json`, and the subagent model override. It does not list the hook `model` field among those locations.

## Empirical test

The working directory was a scratch folder under `/tmp`, outside this repository. The ADW write gate refused a file write named `.claude/settings.json` even under `/tmp`, so the settings came from the CLI flag `--settings`, which accepts a JSON string in place of a file path.

Command run for a `prompt` hook with the alias `sonnet`.

```
claude -p --debug api,hooks --debug-file debug.log \
  --settings '{"hooks":{"Stop":[{"hooks":[{"type":"prompt","model":"sonnet","prompt":"..."}]}]}}' \
  "Say the word ping and nothing else."
```

The debug log recorded this chain for the hook call.

```
[claude-code:unrecognized_model] {"model":"sonnet","query_source":"hook_prompt"}
[API:timing] dispatching to firstParty model=sonnet
API error (attempt 1/11): 404 {"type":"error","error":{"type":"not_found_error","message":"model: sonnet"}}
Hooks: prompt-hook evaluator API error: There's an issue with the selected model (sonnet).
```

A second run against an `agent` hook with the alias `haiku` produced the same chain, with `query_source":"hook_agent"` and `message":"model: haiku"`.

Claude Code sends the literal string from the `model` field straight to the Anthropic API, with no client side alias lookup. The account used for this test has access to Sonnet and Haiku through the normal session model picker. The 404 comes from the API rejecting the bare word `sonnet` as a model id, not from missing account access.

A third run pinned the current constant already in `claude_presets.py`, `claude-sonnet-4-6`, on a `prompt` hook. The dispatch line read `model=claude-sonnet-4-6`, with no error. A fourth run used `claude-sonnet-5-5`, the Claude API id for Sonnet 5.5 from the models overview page. That dispatch also succeeded, and the hook returned a real judged answer rather than the fallback text, which confirms the account already has Sonnet 5.5.

A fifth run used the current `judge.py` constant, the dateless id `claude-haiku-4-5`. That dispatch also succeeded, with no `unrecognized_model` log line at all, unlike the bare aliases. The models overview page lists `claude-haiku-4-5` as the "Claude API alias" row for Haiku 4.5. That row is a server side pointer to the dated snapshot `claude-haiku-4-5-20251001`. It works by a different mechanism than the client side convenience aliases `sonnet`, `haiku`, and `opus`.

## Answer

The alias fails for both hook types. A `prompt` or `agent` hook needs a real Claude API model id. The docs call this id either the dateless pointer form or the fully dated snapshot. The hook code path skips the client side lookup that resolves `/model`, `--model`, and the top level `settings.json` field. The literal word goes to the API instead, and the API returns a 404.

## CLI judge path

`judge.py` and `judge_provider.py` hold no live call to the `claude` CLI. Commit `7bf4397` on this repository removed that call. Its message names the reason. A worker pool around the old call could spawn several billed sessions from one file scan. `judge_provider.available()` returns `False` unconditionally today. `judge.judge()` returns `None` before it would reach a model. The `JUDGE_MODEL` constant is a dead pin. Only tests read it, never a code path that runs against a live account.

For the record, the CLI flag itself does resolve aliases client side. `claude -p --model haiku "..."` dispatched to `claude-haiku-4-5-20251001`, confirmed by the same debug log, with no 404. That resolution happens in the CLI argument parser, a different code path from the hook `model` field.

## Model ids adopted

Sonnet moves from `claude-sonnet-4-6` to `claude-sonnet-5-5`. The test above confirmed it live. It matches the newest row on the models overview page.

Haiku stays at `claude-haiku-4-5-20251001`. That id was already the newest snapshot for Haiku 4.5. The same test run confirmed it live, through the ADW plugin's own managed Stop hook.

`judge.py` moves its dead `JUDGE_MODEL` pin from the dateless `claude-haiku-4-5` to the same dated id, for parity with `claude_presets.py`. The dated id is the exact snapshot the docs name as current. The change has no runtime effect today.

## Luna native, recommendation only

Fact given by the task, not re-derived here. In this Claude Code install, the alias `luna` resolves through LeverFrame to GPT-5.6 Luna. The id `leverframe:openai-oauth:gpt-6-luna` resolves to GPT-6 Luna instead. A sixth and seventh run in the same scratch folder confirmed both strings dispatch without a 404 as an `agent` hook model. Both are live selectable ids in this install, matching the given fact. Selecting GPT-6 Luna would mean rendering `leverframe:openai-oauth:gpt-6-luna` in place of `luna` for the `luna-native` preset. That id names a specific LeverFrame routing target outside the Claude model list this repository owns. This repository does not carry the LeverFrame wiring, so the choice belongs to the user, not to a code change here.
