# Stream F, new entries in the Home Assistant bug list

The Home Assistant session added entries 4a, 6a, 8a to 8g, 11a, 12a, 13a, 13b and 15 to `homeassistant/adw-bug.md` on 2026-10-22. Three read-only investigators triaged them. Coding starts after streams A, B and C pass. Each item keeps every rule at full strength.

## Already folded into stream A

- `git merge-file` wrote its first operand in place without a check. The user moved the fix into stream A round 3.

## Gates, holes first

1. A script run as `python3 script.py` or `bash script.sh` never reaches a gate. Read the script with a bound and pass it through the same gates. The SAVE_THEN_RUN advice points agents at this route today.
2. No gate covers `bsdtar`, `gtar` or `pax -r`.

## Gates, read-only interpreter calls

1. 6a. `next` is missing from `SAFE_BUILTINS` in `hooks/lib/python_payload.py:26`, so ADW denies a read-only `python3 -c` with a generator. Add it and return the argument kind in `builtin_call`.
2. 6a. ADW denies `node -e` with `require("./x.json")` at `hooks/lib/opaque_write.py:112`. Strip each literal JSON `require` that passes `_plain_json_file`, then judge the rest.
3. 6a. `node --input-type=module` with `node:fs` reads needs an allowlist keyed by import binding. Lowest rank.
4. 6a. The action text at `hooks/lib/python_shell.py:122` tells the agent to use Write for a read. Fix the wording only.

## Gates, archives, patches and copies

1. 8a. `git apply` returns UNRESOLVED without reading the patch, at `hooks/lib/write_targets.py:312`. Read the `---` and `+++` headers with a bound and check each path. Deny on binary patches, renames, missing headers and cap hits.
2. 8a and 8e. `decode_pipe_write` and `opaque_source_write` fire on literal scratch destinations. Resolve the destination and deny only when it stays unresolved or names a protected path. Apply the same check to `gunzip >` and `unzip -p >`.
3. 8c, 8e and 8f. `hooks/lib/write_targets.py:361` marks every `tar` and `unzip` extraction UNRESOLVED. Read the member list with a bound, apply `-C` and `--strip-components`, and check each member. Deny on traversal names, link members, dynamic paths and cap hits.
4. 8c. The gate blocks `unzip -lp` and `unzip -lq`, because read flags match only as whole tokens. Parse the short flag cluster.
5. HEAD bug. `cp`, `mv` and `install` always join the source name onto the destination at `hooks/lib/write_targets.py:283`. `cp tests/test_x.py src/a.py` reports `src/a.py/test_x.py`. Join only when the destination is a real directory.

## Prose and scanning

1. 8e and 11a. Add one content masker in `_mask_markup` in `hooks/lib/markup.py`. It blanks unified diff regions, `rg` and `grep` match lines, timestamped log lines and whole JSON documents. Real prose in `.build/` stays checked. The user chose this over skipping dot folders.
2. 8g. Keep the Markdown list path of `three_item_list` and sharpen it. Emit only for three single-sentence items of at most 10 words, with no checkbox, no item ID, consecutive numbers, no code or path, a word spread of at most 7 and one capitalization class. On 154 docs this drops 86 findings to 11 and keeps all 7 real triads.
3. 4a. `de_modal_verb` has precision 0.00, with 0 of 73 hits being padding. Fix the action text now, so a requirement stays a requirement. The German action becomes "Behalte bei einer Anforderung den Sinn und schreib sie als Bedingung oder Imperativ, nicht als Tatsache." Redesign the detector after a fresh label round.
4. 12a. Add one sentence to the shared reviewer prompt in `hooks/lib/judge_contracts.py`. A marker like `c.` at the start of a line is not part of the sentence above it.
5. 13a. Detect binary content by its bytes in `hooks/lib/scan_input.py:98`, then fall back to the extension list. Add `.vdb` to the list as well.
6. 13b. Skip `just` before right, enough, as, like, now, yet, in time, about, over and under in `hooks/lib/slop_phrase.py:202`.
7. 8f. Not reproducible. The scanner removes the URL before the colon rule runs.

## Ownership of copied code

1. 8b. `hooks/lib/comment_rules.py:467` maps docstring lines by offset, so a backslash continuation shifts the line. Map each value line back through the source lines of the docstring node.
2. 8d. `hooks/pre_commit.py:194` builds ownership parents only from git revisions, so every file new to git counts as written by the agent. Feed `imported_baseline` into the commit check. Record files that arrive through `tar`, `unzip` and `git clone`, not only `cp`, `mv`, `install` and `rsync`.

## Open decisions for the user

1. Deny unscanned content before it lands in a source file. This would cover `>`, `cat`, `cp` and downloads alike. Stream A keeps the redirect model and scans the file after the run.
2. Review files above the 128 KiB admission cap. `record_edit` and `record_patterns` admit no rows above `MAX_FILE_BYTES` in `hooks/lib/journal.py:34`, so the model reviewers never see such a file. HEAD has the same gap. An agent can also pad a held file past the cap to release its block. The gap reaches the default install, because judged rules such as `choppy_sentences`, `de_parataxis` and `three_item_list` release their deterministic rows and wait for a model verdict that never comes. QA recommends releasing the stale held verdict and adding a separate block that names the current agent-written file as too large to review. That block must follow the file, not the old held row, so delete and recreate cannot escape it.
3. Decide what counts as a project test for recursive deletes. Stream A walks each folder that `rm -r`, `mv` or `rsync --delete` touches, with a bound of 20,000 entries. So `rm -rf node_modules` fails closed on a bigger folder under both policies. Under `tests=deny` it also fails closed when dependency packages ship test files. QA rejects a `node_modules` exemption and a raised bound, so the fix has to come from a better definition of project tests.
4. Entry 15 is the knowledge-based-search plugin, not ADW. Its gate reads only the main transcript, so a skill loaded inside a subagent never counts. The fix is a PostToolUse `Skill` record or a read of `agent_transcript_path`. Decide where to fix it.

## Follow-ups from streams A to C

- `de_information_cluster` stays off. It still overcounts "gehört", "gefällt", "verlassen", "heute komme ich", "flog", "oder lieferte Peter alles" and "die Kinder haben Hunger". Better verb evidence and a fresh measurement come before any promotion.
- Rerun the German judge eval, because the shared reviewer prompt changed after the last measurement.
- Craftsman nesting warnings in `_judged` in `hooks/lib/claude_luna.py` and `_trailer_metadata_ranges` in `hooks/pre_commit.py`.
