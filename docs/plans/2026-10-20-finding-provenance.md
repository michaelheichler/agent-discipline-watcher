# Finding provenance by unit diff (T-045, ISS-006)

Target 0.29.0. One engine decides whether the agent owns a finding. It diffs units of the baseline text against the current text, with sentences as units in prose and lines in code. A finding on an unchanged or moved unit counts as inherited, and a finding on a changed unit counts as owned. The engine never matches finding text and never scans the baseline.

## 1. Where ADW splits owned and inherited today

Every split goes through `hooks/lib/baseline.py`. `partition` (144) calls `subtract` (128-141), which matches `(family, rule, snippet)` exactly and then counts by rule alone (138-141, the ISS-006 hole). `_halves` (151) and `_against` (205) wrap it, and `_against` first runs a full `scan_all` of the baseline through `_baseline_rows` (190-202).

| Caller | Baseline text | Current text |
|---|---|---|
| PostToolUse `hooks/record.py:171` | snapshot or HEAD | file after the write |
| PostToolUse fallback `record.py:169` | snapshot digest or generated marker | none, file scope |
| PreToolUse Edit `hooks/pre_write.py:225-236` | file before the edit | edited text, uses `changed_lines` OR `partition` |
| PreToolUse Write and patch `pre_write.py:307` | snapshot or HEAD | full or projected content |
| Bash overwrite `hooks/lib/write_shape.py:63-67` | snapshot or HEAD | heredoc body, an append stays owned |
| Batch `hooks/batch.py:298-307` | snapshot or HEAD | file on disk |
| Commit gate `hooks/pre_commit.py:173-191` | HEAD plus merge parents, pooled | staged blob |
| Stop rescan `hooks/lib/stop_scan.py:53-71` | snapshot, else HEAD | file on disk |
| Document reviewer `hooks/lib/journal.py:432-449, 561` | turn-start text | source context, line hunks |
| Parataxis candidates `hooks/lib/parataxis_review.py:45-47, 83-85` | turn-start text | file on disk |

In every row except the Edit fallback, finding lines refer to the current text. The Edit fallback indexes the pending `new_string`, so all its findings stay owned.

## 2. How findings carry location

`Finding` (`hooks/lib/findings.py:23-48`) has a 1-based `line`, a `snippet`, and an optional `match` span. It has no end line. Masking keeps host line numbers (`markup.py:146, 291`, `scanner.py:298`). `parataxis.paragraph_sentences` (`parataxis.py:179`) already returns sentence spans with first and last line.

A line-scoped prose finding maps to the sentence that holds its `match` on its line. If the match appears more than once or not at all, the finding takes every sentence on that line.

Block-scoped findings start at their first line but cover a span. Examples are `low_sentence_variance`, `three_item_list`, `oversized_list`, parataxis runs, comment blocks, docstrings, `function_too_long` and test units. Without an end line, an edit to sentence 3 of an inherited paragraph leaves a paragraph finding on line 1 inherited.

The plan adds an optional `end_line` to `Finding`. Each block emitter sets it from the span it already computes. A missing `end_line` means one line.

## 3. Changed-hunk logic that exists

`baseline.changed_lines` (`baseline.py:93-101`) and `document_hunks.changed_lines` (`document_hunks.py:43`) are two copies of a raw-line `SequenceMatcher`. Neither normalizes whitespace, so a reflowed paragraph marks every line changed. The new engine replaces both. `document_hunks._windows` keeps its windowing and takes changed lines and removal seams from the engine, so the reviewer, parataxis candidates and the gate agree on what changed.

## 4. Algorithm in a new `hooks/lib/provenance.py`

```python
def compare(path: str, before: str, after: str, check: Check = _unchecked) -> Provenance
def compare_any(path: str, befores: list[str], after: str, check: Check = _unchecked) -> Provenance
class Provenance:  # owns(finding), changed_lines, removed_seams, growth(first, last)
```

1. Units. A prose file uses `prose_source`, then paragraphs, then sentences split by `SENTENCE_BREAK_RE` with their spans. A span-yielding sibling in `prose_structure.py` keeps one splitter. Every non-blank host line that no sentence covers becomes a line unit. In code, every non-blank line is a unit.
2. Normalization with `" ".join(text.split())`, so a reflowed sentence keeps its key and a reindented code line stays unchanged.
3. Alignment. Trim the common prefix and suffix, then run `difflib.SequenceMatcher(None, old_mid, new_mid, autojunk=False)` on the middle. `equal` means unchanged and anything else means changed.
4. Moved units. A `Counter` of old keys outside `equal` blocks marks a changed new unit as moved when its key has at least 12 characters. The counter makes an extra copy owned, and the length floor stops `}` or `pass` from laundering a new finding.
5. `owns(finding)`.
   - Always-blocking and fixed-observe rules stay owned, as at `baseline.py:133`. `_length_relief` keeps the growth and generated-marker rules for `file_too_long` and `unscannable_file`.
   - `function_too_long` and `oversized_list` count as owned when the span grew. Otherwise rewording one line of an inherited long function would demand a refactor.
   - `uniform_paragraph_endings` counts as owned when a paragraph-ending unit changed.
   - Every other finding counts as owned when any unit in `[line, end_line]` changed. A prose finding in a prose file narrows to the sentence holding its match.
6. Merges. `compare_any` marks a unit changed only when it changed against every parent. This replaces pooling at `baseline.py:287`.
7. ADW classifies only current findings, so deleted units produce nothing.
8. Without git and without a snapshot, every finding stays owned.

In `baseline.py`, `_against` builds a `Provenance` instead of scanning the baseline. `partition` becomes one filter, and `subtract`, `finding_key`, `rule_key`, `_consume` and the loose pass go away. `_BASELINE_CACHE` becomes a memo of unit lists keyed by baseline digest. `pre_write._edit_findings` calls `compare` once.

## 5. Performance

The Stop rescan has 7 s (`stop_scan.py:23`) and files go up to 1 MB. Today the split rescans the baseline at about 250 KB/s, which costs about 4 s on a 1 MB file. The new cost is one masking pass and a regex split per text, plus a diff over the trimmed middle.

A `DIFF_UNITS_PER_SECOND` rate measured by a benchmark test feeds `fits_deadline`. If the middle passes `MAX_DIFF_CELLS`, every middle unit counts as changed, which is the conservative answer. The target is under 300 ms for a 1 MB rewrite.

## 6. Behaviors to test

Prose:

1. An unchanged file leaves every finding inherited.
2. A reflowed paragraph with the same words keeps its passive inherited.
3. An old passive replaced by a new passive counts as owned. This flips `RewordedFindingTests` in `hooks/lib/test_baseline.py:315-339`.
4. On a line shared by unchanged sentence A and changed sentence B, a match in A stays inherited and a match in B counts as owned.
5. An edit to sentence 3 of an inherited `low_sentence_variance` paragraph makes the finding owned.
6. A moved paragraph stays inherited, and an extra copy counts as owned.

Code:

1. A reindented block keeps its `what_comment` inherited, and a reworded one counts as owned.
2. A moved line stays inherited, and a new `}` matching a deleted `}` counts as owned.
3. `function_too_long` stays inherited after a one-line edit and becomes owned when the function grows.

File scope and modes:

1. `file_too_long` follows growth and the generated marker, as `test_first_seen.py:92-156` covers today.
2. A line taken from a merge parent stays inherited, and a line in no parent counts as owned.
3. The Stop rescan tags inherited rows, and `end_turn` releases a set that holds only inherited findings.
4. Reviewer hunks for a reflowed paragraph show no added lines.
5. A 1 MB diff fits the measured rate, and an over-cap diff marks the middle changed without raising.

## 7. Measurement

Reports in `~/.adw/reports` hold only owned rows, so they cannot show inherited findings that become owned. A replay script `evals/provenance_replay.py` pairs the first-seen blobs under `~/.adw/state/*/imported/` and the journal rows that carry both before and source context. For each pair it scans the current text once and classifies every finding with the legacy `subtract` and with `provenance.compare`. It prints counts per rule for each flip direction, 20 sample rows per direction, and the diff time distribution.

To pass, a reflow or a move must explain every owned-to-inherited flip. Every inherited-to-owned flip must sit on a changed unit. The totals go into the CHANGELOG.

## 8. Risks and what stays for one release

1. Rewording an inherited offender now makes it owned, by design. The T-035 visible release in 0.28.0 keeps that from trapping an agent.
2. A block emitter without `end_line` under-owns. A registry test runs one fixture per block rule and asserts `end_line >= line`.
3. Units only need to stay stable between the two texts, so the provenance splitter stays separate from rule tuning, and a test freezes it.
4. An edit that touches only masked text, such as an HTML attribute or a link URL, leaves prose unchanged. The README says so.
5. The commit gate starts applying `_length_relief`, so a commit of an old long file that did not grow passes.
6. No legacy switch. The public `split_*` and `strip_*` signatures stay the same, so callers need no edits beyond `pre_write._edit_findings` and `pre_commit`. `baseline.changed_lines` goes away with its callers moved to the engine.

## Sequence

1. `end_line` on `Finding` and the block emitters, with the registry test.
2. `provenance.py` and its tests.
3. Switch `baseline.py`, `pre_write._edit_findings` and `pre_commit`.
4. Move `document_hunks`, `journal` and `parataxis_review` onto the engine.
5. Benchmark and replay, with the numbers recorded.
6. README and CHANGELOG.

## Decisions (user, 2026-10-20)

1. `function_too_long` and `oversized_list` count as owned only when their span grows.
2. The commit gate applies the same length growth rule as Stop, so the two gates agree.
3. Clean cut with no legacy switch. `subtract` and the loose pass leave in 0.29.0, and the replay must clear its acceptance bar before release.
