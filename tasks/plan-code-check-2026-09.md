# Implementation plan for the Code Check family

The spec lives in [spec-code-check-2026-09.md](spec-code-check-2026-09.md). The tickets live in [todo-code-check-2026-09.md](todo-code-check-2026-09.md).

## Overview

ADW gains a third rule family, Code Check, next to Prose and Comment Check. Code Check judges tests against Khorikov and code against clean code principles. Each finding explains its principle in plain text from a local knowledge base. The ADW suite with 2012 test functions is the first corpus. Two smaller changes land first. Luna moves to the newest model, and the embedding worker stops reloading on every turn.

## Evidence

| Fact | Source |
| --- | --- |
| Codex lists `gpt-6-luna` with high effort, and ADW pins `gpt-5.6-luna` | `~/.codex/models_cache.json`, `hooks/lib/luna_provider.py:28` |
| Claude judges pin `claude-haiku-4-5-20251001` and `claude-sonnet-4-6` | `hooks/lib/claude_presets.py:16-17` |
| Every Stop releases the embedding lease, so the next turn reloads 709 MB of weights | `hooks/stop.py:52`, `hooks/lib/model_artifacts.py:60` |
| OpenCode Go has no embeddings endpoint, and a POST to `/zen/go/v1/embeddings` returns 404 | `opencode.ai/docs/go`, probe on 2026-09-30 |
| DevIQ holds about 248 entries in `NimblePros/deviq-hugo`, with no license file | shallow clone on 2026-09-30 |
| webpro/programming-principles holds 30 principles in one README, with no license file | GitHub API on 2026-09-30 |
| 16 files outside tests name a family string, including the OMP bridge | `git grep` on 2026-09-30 |

## Architecture decisions

### Rules

1. Old family names stay valid. `punctuation` and `english` become subfamilies of `prose`. `clean_code` becomes an alias that covers both `comment` and `code`. A user configuration therefore keeps its meaning.
2. Test rules run on test functions only. A test function is a Python `def test_*` or a Rust `#[test]` function. The existing `brace_functions.py` measures brace spans, and Python uses `ast`.
3. Static rules come first. They need no model, cost nothing per write, and give the fastest measurement on the ADW suite.
4. Every new rule starts at observe. It blocks only after a hand-labeled sample reaches precision 0.85.

### Explanations

1. The knowledge base is a local SQLite file under `~/.adw/cache/principles.sqlite`. Install and update build it from pinned commits of both source repositories. No hook fetches anything from the network.
2. The repository ships only `principle_map.json`, which maps rule ids to source entry ids. The text never enters git.
3. A finding shows the explanation once per rule per session, at most 80 words, with no link. Later findings of the same rule show the rule line only. This caps the token cost for the agent.

### Runtime

1. The embedding worker stays warm across turns until an idle timeout runs out. The timeout replaces the release on every Stop.
2. Luna picks the highest `gpt-N-luna` that the account lists with high effort. Each verdict and each cache key records the model id.

## Task list

### Phase 1. Foundations, parallel

- [ ] Task 1. Luna resolves to the newest model
- [ ] Task 2. Claude judge model aliases
- [ ] Task 3. Measure one embedding load cycle
- [ ] Task 4. Idle timeout for the embedding worker
- [ ] Task 5. Split the rule families

### Checkpoint A

- [ ] Hook suite and pylint pass
- [ ] Old configuration files load with the same rules active
- [ ] The user reviews the embedding numbers before Task 4 merges

### Phase 2. Static test rules and explanations

- [ ] Task 6. Test function extraction and the self-audit runner
- [ ] Task 7. The two user rules and the loop rule
- [ ] Task 8. The remaining static Khorikov rules
- [ ] Task 9. Knowledge base build step
- [ ] Task 10. Explanation text in findings
- [ ] Task 11. Self-audit measurement on the ADW suite

### Checkpoint B

- [ ] The Rust example yields the loop finding and the name finding with explanations
- [ ] `evals/code_check_precision.json` holds a precision per static rule
- [ ] The user decides which rules block and which ADW tests go

### Phase 3. Semantic rules and clean code

- [ ] Task 12. Spike on test embeddings
- [ ] Task 13. Semantic test rules through the journal and Luna
- [ ] Task 14. Clean code principle catalog
- [ ] Task 15. README and CHANGELOG

### Checkpoint C

- [ ] All success criteria in the spec hold
- [ ] The user reviews before any push or release

## Parallel work

Tasks 1 to 5 touch separate files and run in parallel. Tasks 7, 8, and 9 run in parallel after Task 6 and Task 5. Task 10 waits for Task 9. Task 13 waits for the spike result of Task 12. Task 14 is research and runs at any time.

## Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Text embeddings group tests by topic, not by pattern | High | Task 12 measures separation first. If it fails, Task 13 sends only static candidates to Luna. |
| The family split breaks the OMP bridge or user configurations | High | Aliases, a parity test against `adw-bridge.ts`, and a fixture with each old configuration |
| The self-audit flags hundreds of ADW tests | Medium | Rules stay at observe. The user decides on deletion in Checkpoint B. |
| A newer Luna changes verdicts without notice | Medium | The journal records the model id, so a precision drop shows up per model |
| DevIQ changes its layout | Low | The build pins a commit, and a missing entry falls back to the rule line |
| A warm worker holds 709 MB between turns | Medium | Task 3 measures it, and the idle timeout is configurable |

## Open questions

1. Unraid. The recommendation is to skip it unless several machines share one store.
2. Claude aliases. Task 2 answers this.
3. Test deletion. The user decides after Checkpoint B.
