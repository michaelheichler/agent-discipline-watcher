<p align="center"><img src="adw-logo.svg" alt="Agent Discipline Watcher" width="480"></p>

Agent Discipline Watcher (ADW) checks agent-written prose, comments, tests, and commits, then blocks or reports each finding with one rule and one line.

Current release: **0.33.0**.

[![MIT license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Pylint](https://github.com/michaelheichler/agent-discipline-watcher/actions/workflows/pylint.yml/badge.svg)](https://github.com/michaelheichler/agent-discipline-watcher/actions/workflows/pylint.yml)
[![Python 3.11 or newer](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

## What it does

ADW is a Claude Code plugin with a Python hook engine. It checks output from Claude Code, Codex, OMP (oh-my-pi), and Cowork. The host runs checks as an agent writes and when it finishes a turn. ADW never returns a verdict on a whole document and never answers whether a model wrote something.

A finding names the rule, file, line, and action. For example:

```text
/path/file.md:42 Dash character. Use ASCII hyphen or rewrite the sentence. (banned_dash)
```

Pattern checks catch known forms. An optional meaning layer looks for paraphrases, and a model review can assess comments or document structure. Rules block only when their measured precision reaches 0.85. The [evaluation guide](evals/README.md) explains the measurements.

## Install

### Claude Code

In Claude Code, run:

```text
/plugin marketplace add michaelheichler/agent-discipline-watcher
/plugin install agent-discipline-watcher@agent-discipline-watcher
/reload-plugins
```

### Codex

From a checkout of this repository, run:

```bash
./install.sh --codex
```

### OMP (oh-my-pi)

From a checkout of this repository, run:

```bash
./install.sh --omp
```

Restart OMP after installation.

### Cowork

Find Agent Discipline Watcher in the plugin directory on claude.ai and sync it to Cowork. Cowork has no local installer.

## Everyday use

`./install.sh` adds `~/.adw/bin` to your shell PATH. Without it, run `bin/adw-config` from a checkout of this repository. Run `adw-config` in a terminal to inspect or change project policy. The configuration file lives at the project root as `.agent-discipline.json`.

```bash
adw-config status
adw-config family prose on
adw-config tests allow
adw-config tests deny
adw-config prose-languages en,de
```

Test writes default to deny. To allow them temporarily, use `adw-config tests allow --for 30m`.

Update the installed hosts to the latest release:

```bash
~/.adw/bin/adw update
```

Preview full removal, then remove ADW and its stored data:

```bash
~/.adw/bin/adw-nuke --dry-run
~/.adw/bin/adw-nuke --yes
```

## How checks work

**Pattern rules** look for known issues such as banned punctuation or comment narration. These checks are deterministic.

**Meaning checks** compare prose sentences with examples of a rule, which can surface matching ideas expressed in different words. This layer is optional.

**Document and model review** can assess structure that line-level rules cannot judge. Model review uses your selected host session, and some host review routes send the text under review to a model provider.

The precision threshold helps keep false positives from blocking work. ADW reports rules that have not reached the threshold instead of blocking on them. See [evaluation results](evals/README.md).

## Requirements and privacy

ADW requires a Unix shell and Python 3.11 or newer. Model review uses the login for the host you configured. ADW does not require an API key.

ADW keeps session state, findings, reports, caches, and provider runtimes under `~/.adw`. Project policy stays in `.agent-discipline.json` at the project root.

Deterministic checks run locally. Model review may send candidate text to the provider used by that host. Codex and OMP review need `data_boundary.enabled` set to `true` in the project `.agent-discipline.json` file. The Claude review preset uses your Claude Code session. Choose a review setup only if its data handling fits your needs.

## Development

Run the project checks from the repository root:

```bash
(cd hooks && python -m pytest . lib -q)
python3 -m pytest pi/test_merge_settings.py -q
(cd pi && bun install && bun test)
pylint $(git ls-files '*.py')
claude plugin validate . --strict
```

The project denies test writes by default. Only the `adw-test-writer` agent may add or change tests. See the [test-writing principles](skills/unit-testing-principles/SKILL.md) and [agent skill](skills/agent-discipline-watcher/SKILL.md).

## Further information

- [Configuration help](skills/adw-config/SKILL.md)
- [Host integrations](hosts/)
- [Release history](CHANGELOG.md)
- [License](LICENSE)
- [Third-party credits](NOTICE)
- [Evaluation methods](evals/README.md)
