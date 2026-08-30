# Implementation Plan for the Per-Host Runtime Split

Rewritten on 2026-08-30, after Phase 2 closed. `spec-host-runtime-split-2026-08.md` holds the
requirements and `decisions-host-split-2026-08.md` holds the settled decisions with their
evidence. This file tracks the task list and nothing else.

## Overview

ADW ships one rules core and four host runtimes. A user installs the runtime for the host they
use, and nothing else lands on disk. The core stays identical everywhere, and a fixture that
all four runtimes scan proves it.

## Corrections to the first draft

Three claims in the original plan turned out wrong. Each cost work, so each stays recorded.

1. "There are three runtimes." Cowork is a fourth. Its VM never reads the host home directory.
2. "The OMP extension API exposes no inference call." It exposes `completeSimple` and
   `streamSimple` from `@oh-my-pi/pi-ai`, reachable in process.
3. "The Claude runtime uses agent hooks and never spawns a nested CLI." True for `haiku`,
   `mixed`, and `sonnet`. The `luna` preset cannot, because a Claude agent hook carries no
   OpenAI model. D6 records why the SDK path stays.

## Phase 1. Contract, done 2026-08-30

- [x] Task 1. Runtime manifest and host identity. `lib/host.py` resolves four hosts in a fixed
      order and raises `UnknownHostError` rather than falling back.
- [x] Task 2. Collector config directory schema. `lib/collector.py` plus `lib/config_roots.py`,
      tolerant of an absent tree, refusing an unknown key by name.
- [x] Task 3. Host model provider seam. `lib/judge_provider.py` owns the only `claude -p` in
      the tree, and a test fails if a judge imports `subprocess` again.

### Checkpoint, met
- [x] Host identity resolves for all four
- [x] The collector loads while every runtime sits absent
- [x] Full suite green

## Phase 2. Packaging, done 2026-08-30

- [x] Task 4. Shared core that names no host. `lib/test_core_boundary.py` parses every module
      and every shared entry script and refuses an import into a host adapter.
- [x] Task 5. Claude runtime, serving terminal, IDE, Desktop, and web.
- [x] Task 6. Codex runtime.
- [x] Task 7. OMP runtime, plus the Cowork runtime the four-host roster added.

Tasks 5 to 7 landed as one build step rather than four hand-maintained trees.
`hosts/<name>/host.json` declares each host's surface, `lib/vendor.py` writes a runtime, and
`hooks/build_runtime.py` is the entry point.

### Checkpoint, met
- [x] Each runtime passes its own tests with the other three deleted,
      `test_runtime_isolation.py`
- [x] The fixture scan matches across all four runtimes and the source tree,
      `test_runtime_parity.py`

Suite moved 1817 to 1959 passing. Build output is 202, 196, 201, and 191 files.

## Phase 3. Installers, done 2026-08-30

- [x] Task 9. Ship the Claude runtime through plugin hooks only. Landed in commit `46801d2`.
- [x] Task 8a. `hosts/claude`, `hosts/codex`, and `hosts/omp` each own an `install.sh`, with
      `hosts/common.sh` holding the guards none of them should reimplement.
- [x] Task 8b. The four unconditional writes moved to the hosts that need them. Claude owns
      `~/.local/bin/adw-judge` and the rc block. `pi/install.sh` already owned `~/.agents`.
- [x] Task 8c. `hooks/host_picker.py` draws the multi-select and prints the choice to stdout.
      `lib/picker_state.py` holds the pure state, so every key and click has a test.

### Checkpoint, met
- [x] A Claude install leaves no `~/.codex`, no `~/.omp`, and no `~/.agents`
- [x] A moved checkout does not break an installed runtime, proven by renaming the source and
      running the installed launcher
- [x] Choosing nothing touches no file, and so does `--dry-run`

Claude gained an installer, which D4 said it would not carry. The reason is in the decisions
file under D7. Suite moved 1959 to 2003 passing.

## Phase 4. Model providers

- [ ] Task 10. OMP internal model provider, split into a wire contract plus two provider shapes
- [ ] Task 11. Claude agent hook provider at haiku, nested CLI removed
- [ ] Task 12. Open the OMP model picker to every authenticated model

### Checkpoint
- [ ] No host spawns a nested Claude CLI
- [ ] A local OMP model returns real judge verdicts

## Phase 5. Surface verification

- [ ] Task 13. Verify one Claude runtime gates terminal, Desktop, and web

### Checkpoint
- [ ] Every runtime runs standalone from `~/.adw`
- [ ] All four runtimes produce identical rule output on one fixture

## Tasks

## Task 8a. Host installer scripts

**Description:** Each installable host owns the script its manifest already names. Codex takes
the block that sits at `install.sh:157-184` today. OMP delegates to `pi/install.sh`, which
already owns that surface. Claude and Cowork carry none, because a plugin install and an
account sync are not local scripts.

**Acceptance criteria:**
- [ ] `hosts/codex/install.sh` and `hosts/omp/install.sh` exist and run alone
- [ ] Each installer stays idempotent across a second run
- [ ] No installer writes another host's configuration
- [ ] A test asserts every manifest that names an installer has that file on disk

**Verification:**
- [ ] Tests pass, `cd hooks && uv run --with pytest python -m pytest test_install_runtime.py -q`
- [ ] Manual check, run each installer into a temporary HOME and list the tree

**Dependencies:** Phase 2

**Files likely touched:**
- `hosts/codex/install.sh`
- `hosts/omp/install.sh`
- `hooks/lib/test_host_manifest.py`

**Estimated scope:** Medium

## Task 8b. Scope the shared writes

**Description:** Four writes in `install.sh` run no matter which host the user picked. That
breaks the D4 acceptance that each installer writes only under `~/.adw` and its own host
directory. They are `~/.agents/skills` at line 124, the three `~/.local/bin` links at lines 196
to 207, and the rc block that the script appends to `~/.zshrc` and `~/.bashrc` at line 210.

**Acceptance criteria:**
- [ ] Selecting one host leaves the other hosts' paths untouched
- [ ] Selecting nothing writes no file at all
- [ ] The rc block and the bin links attach to the hosts that need them, not to every run
- [ ] Uninstalling a host removes what that host wrote and nothing else

**Verification:**
- [ ] Tests pass, `cd hooks && uv run --with pytest python -m pytest test_install_runtime.py -q`
- [ ] Manual check, install one host into a temporary HOME and diff the tree against empty

**Dependencies:** Task 8a

**Files likely touched:**
- `install.sh`
- `hooks/test_install_runtime.py`

**Estimated scope:** Medium

## Task 8c. The router and the picker

**Description:** `install.sh` keeps its place as the entrypoint and stops knowing how to
install anything. A Python module under `hooks/` draws an interactive multi-select and prints
the chosen hosts back to bash, which then calls each `hosts/<name>/install.sh`. Bash resolves
the interpreter through `adw_resolve_python` against the floor in `.python-version`, the same
call it already makes at line 114. The picker reads `title`, `summary`, and `writes` straight
from the manifests, so it duplicates no wording.

**Acceptance criteria:**
- [ ] Arrows move, space toggles, Enter installs, and an SGR mouse click selects a row
- [ ] The picker names what each host writes before the user chooses
- [ ] A flag path installs without a terminal, for agents and CI
- [ ] Selecting nothing exits without touching disk
- [ ] The router maps a selection to exactly the chosen host installers

**Verification:**
- [ ] Tests pass, `cd hooks && uv run --with pytest python -m pytest test_host_picker.py test_install_runtime.py -q`
- [ ] Manual check, run `install.sh` with no flags and click a row

**Dependencies:** Tasks 8a and 8b

**Files likely touched:**
- `hooks/host_picker.py`
- `hooks/test_host_picker.py`
- `install.sh`
- `hooks/test_install_runtime.py`

**Estimated scope:** Medium

## Task 14. Split `claude_native.py` further, rendering first

Unchanged and still optional. `claude_native.py` sits near 995 lines against a 1000-line hard
block and a 750-line observe threshold, so reaching the threshold needs two staged moves.

Move one takes the rendering cluster at 567 to 709 and the managed hook cluster at 333 to 362,
about 173 lines, landing near 819.

Move two needs a three-layer boundary first, because a plain import either way cycles. Layer
zero is `claude_base.py` holding `PRESETS`, `TRANSACTION_VERSION`, `CORRUPT_SUFFIX`,
`_validate_preset`, and the path helpers, none of them patched. Layer one takes both
`MAX_CORRUPT_*` bounds and the reader as arguments, because the reader stack runs through the
patched `_leaf_lstat`. Layer two stays `claude_native.py`.

`_recover_unlocked` stays put. It calls the monkeypatched writes at 400, 408, and 413, so a
plain move would bind those names at import time and the patches would stop biting with no
test failing.

**Dependencies:** None, and it stays optional until a further addition trips the hard block

**Estimated scope:** Large, two staged moves

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|------|------|
| Rules drift between hosts | High | One shared core, plus `test_runtime_parity.py` across all four runtimes |
| A core module reaches back into a host | High | `test_core_boundary.py` refuses the import, with one named seam |
| An installer writes a path the user did not choose | High | Task 8b, plus a temporary HOME diff against empty |
| A host runtime passes silently when its provider is missing | High | An absent provider reports a named reason and never returns an empty result |
| The web surface ignores local settings | Medium | Task 13 checks it on its own, and the plugin carries its own hook wiring |
| Cloud egress from a freely chosen model | Medium | The data boundary flag keeps gating egress, and the picker names the destination |

## Open Questions

- Does the OMP judge provider call providers directly over HTTP, or should ADW ask OMP
  upstream for a host-side inference API?
- Which unwired Claude events earn their place, given the runner dispatch already carries
  `PostToolBatch` and `PostToolUseFailure`?
