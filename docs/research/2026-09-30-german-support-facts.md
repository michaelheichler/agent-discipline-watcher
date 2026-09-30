# German support research facts, 2026-09-30

## 1. Embedding model multilinguality

ADW's `hooks/lib/model_artifacts.py` pins `MLX_REPOSITORY = "mlx-community/LFM2.5-Embedding-350M-bf16"` (line 33). That is a bf16 conversion of `LiquidAI/LFM2.5-Embedding-350M-GGUF` (line 35).

- The MLX community card (https://huggingface.co/mlx-community/LFM2.5-Embedding-350M-bf16) calls the model a "multilingual dense bi-encoder." It carries an "11 languages" tag. It does not list the languages itself. It reports a MIRACL German ("de") NDCG@10 of 0.809.
- The upstream card it points to is https://huggingface.co/LiquidAI/LFM2.5-Embedding-350M. That card states supported languages directly. Quote. "English, Spanish, German, French, Italian, Portuguese, Arabic, Swedish, Norwegian, Japanese, Korean." German also appears as a scored column in its NanoBEIR/MKQA-11 tables. The embedding model scores 0.581 NDCG@10 and 0.709 Recall@20 on "de."

**Answer.** Yes, multilingual. Yes, the LiquidAI upstream card names German as a supported language. Cite that card, not the MLX-community mirror, for the language list.

## 2. Duden skill provenance and license

Path: `~/Development/skills-agents/skills/duden-rechtschreibung`. This is its own git repo. It is not part of a `skills-agents`-wide repo. `git status` fails at the parent `~/Development/skills-agents`. The error names it "not a git repository."

- **Source stated in README/SKILL.md.** The README declares that rules and examples derive from *Duden, Einfach können. Rechtschreibung, Zeichensetzung und Grammatik* (Dudenredaktion, Cornelsen 2025, ISBN 978-3-411-75696-4). A scripted pipeline built the skill. `convert.py` turns the EPUB into Markdown. Then one agent per chapter runs via `wf-extract.js`. Then polish scripts run. The README states "Personal use only." A `.gitignore` entry excludes the source EPUB itself, so the repo never ships it.
- **Own words versus verbatim.** I sampled `references/zeichensetzung/07-komma.md` and `references/zeichensetzung/15-anfuehrungszeichen.md`. The connective, explanatory prose reads as the extraction agent's own summary, not book typesetting. One example line reads "Das Komma gliedert Sätze. Es trennt Aufzählungsteile..." There are no page numbers. The pipeline reformats the text into agent-house style, with `>` blockquotes and Markdown tables. The example sentences are short and generic. One reads "In Weimar lebten Goethe, Herder, Schiller und Wieland." That style of example recurs across many German grammar references. It even recurs on Duden's own free rule pages. I cannot establish from the file content alone whether these specific example sentences copy the 2025 book verbatim. The source EPUB is deliberately not in the repo (per `.gitignore`). I did not have book access to check against it. Mark this unverified.
- **License file.** None exists. A search for `LICENSE*` in the repo returns nothing.
- **Public on GitHub.** `git remote -v` inside the skill's own repo shows `origin https://github.com/michaelheichler/duden-rechtschreibung.git`. `gh repo view --json visibility` reports `"visibility":"PRIVATE"`. The parent directory `~/Development/skills-agents` has no `.git` at all. It is not a repo at all, public or otherwise.

## 3. Duden.de official API and terms

- Duden offers a paid official API (https://www.duden.de/api). It covers spelling check, grammar correction, synonym suggestions, and punctuation check. It runs over JSON/HTTP. Duden claims servers in Germany and no data storage. Plans: "API Pro 100" gives 100 requests a day for 39.95 euros a month. "API Pro 500" gives 500 requests a day for 99.95 euros a month. "API Pro 1000" gives 1,000 requests a day for 174.95 euros a month. Duden caps each request at 20,000 characters. Larger volume needs a direct request to `kundenservice@duden.de`. Duden gives no open dataset and no free word-list download.
- Terms of use. The shop AGB sits at https://www.duden.de/service/agb. Section 1 paragraph 4 states these AGB cover only the shop. It says the free online dictionary has separate terms, not on that page. A direct guess at `/nutzungsbedingungen` returned a 404. I did not manage to fetch the dictionary-specific terms in this session. Within the shop AGB I did find these clauses.
  - Section 6 paragraph 11 opts out of the German text-and-data-mining copyright exception (paragraph 44b UrhG). The publisher reserves mining or scraping of the content to itself.
  - Section 12 says digital products are copyright protected, licensed for internal own use only. The customer cannot alter them. The customer cannot make them publicly accessible.
  - Section 6 paragraphs 3 to 4 let the publisher block access it deems abusive.
  - No clause names "scraping," "crawling," or "bot" directly.
- **Answer.** Yes to an official API, paid and rate limited, with no bulk or open dataset. The shop terms reserve text-and-data-mining rights. The shop terms forbid redistribution. The dictionary's own separate terms likely govern lookups on `duden.de/rechtschreibung/...`. I did not retrieve those terms directly in this session. Mark that half unverified.

## 4. humanizer-de 5.28.1

Path: `~/.claude/plugins/cache/humanizer-de/humanizer-de/5.28.1`.

- **License.** MIT (`LICENSE`). Copyright holders are Martin Moeller (2026) and Siqi Chen (2025, portions from `blader/humanizer`). `NOTICE` adds one carve-out. `references/patterns.md` adapts material from two Wikipedia project pages. So do the matching tables in `README.md` and `docs/muster-katalog.md`. The two source pages are "Anzeichen für KI-generierte Inhalte" and "Signs of AI writing." Those specific adapted portions are CC BY-SA 4.0, not MIT.
- **Runtime needs of the four named scripts.** All four use only the standard library plus the project's own sibling modules. None imports a third-party PyPI package. None makes a network call directly in the lint logic itself.

  Two scripts share the same shape. `german_pattern_lint.py` and `register_lint.py` both use stdlib `argparse`, `re`, `sys`, `importlib.util`, plus in-repo `evidence_lint` and `text_scope`. `german_pattern_lint.py` adds `bisect`, `functools`, `pathlib`, and in-repo `register_lint`. `register_lint.py` adds `collections.abc`.

  `rhythm_lint.py` uses stdlib `argparse`, `re`, `statistics`, `sys`, `pathlib`, plus in-repo `text_scope`. `spell_lint.py` is the outlier. It uses stdlib `argparse`, `re`, `shutil`, `subprocess`, `sys`, `pathlib`. It shells out via `subprocess`, likely to a system spellchecker binary. `shutil` probably locates that binary on `PATH`. It is the only one of the four with a plausible external-process dependency.

  All four share a local `cli_output` module for their I/O. None of the four imports a network library directly. A related script, `fp_corpus_report.py`, reads a local `tests/fp_corpus` directory, not the network.
- **`references/patterns.md` pattern counts.** 72 patterns total. The file's own section header names "Die 72 Muster." They group into 10 named categories. Sprache und Tonfall holds 19. Stil holds 5. Kommunikation holds 6. Auszeichnungstext holds 6. Verschiedenes holds 3. Rhetorik und Struktur holds 13. Argumentation und Evidenz holds 7. Ergänzungen holds 4. Typografie und Format holds 7. Titel- und Satzbau holds 2. Those ten add to 72. A separate "Statistische Detektoren (GPTZero u. a.)" section sits outside that 72-pattern count.
- **Measured false-positive rate.** Yes, in a limited sense. `scripts/fp_corpus_report.py` reads `tests/fp_corpus/`. It reports findings by kind. `tests/test_fp_corpus.py`, `tests/test_fp_corpus_report.py`, and a dedicated `tests/scenarios/04_technical_false_positive.yaml` scenario exist alongside it. This is a curated regression corpus. It is not a large-scale statistical false-positive rate over a big sample.

## 5. German corpora for measurement

ADW's own `evals/` directory is English-only today. It already depends on these three datasets.

- `allenai/WildChat-4.8M`. HF datasets-server reports 3,199,860 total rows. Each row carries a nested per-turn `language` field. In principle a manual parquet scan filters German turns out by that field. I did not get an exact German-row count in this session. The datasets-server `filter` endpoint kept rejecting the `where` clause, and once returned a 502. Mark unverified.
- `lmarena-ai/arena-human-preference-100k`. HF datasets-server reports 106,134 total rows, with a top-level `language` column. Same caveat applies. Exact German-row count was not obtained this session. Mark unverified.
- `wikimedia/wikipedia`, used for the English side today via config `20231101.en`, also ships a German config. Config `20231101.de` holds 2,845,308 verified rows, via `https://datasets-server.huggingface.co/size?dataset=wikimedia/wikipedia&config=20231101.de`. This is an openly licensed source (CC BY-SA/GFDL, per Wikipedia). It gives a directly usable German prose baseline. It mirrors what `evals/build_paragraph_corpus.py` already does on the English side.
- Project Gutenberg German. I did not find a ready-made, openly licensed German-language HF dataset comparable to `sedthh/gutenberg_english` in this session. Mark unverified, not found. One caution worth recording. The German-language "Projekt Gutenberg-DE" (spiegel.de) is not an open-license mirror of the US Project Gutenberg. It carries its own restrictive terms. It is not a safe drop-in, even though the name looks similar. The safer route is filtering `gutenberg.org`'s own public-domain catalogue directly by `language=de`. I did not check that route in this session.

## 6. ADW's current behavior on German prose

I ran a scratch script, `~/adw-research-scratch/run_scan.py`, deleted after the run. It imported `hooks/lib/scanner.scan_all` directly. It scanned this German paragraph as `sample.md` (prose).

> "Das Projekt läuft gut, die Ergebnisse sind vielversprechend. „Wir sind zufrieden", sagte die Leiterin, sie betonte die Zusammenarbeit und könnte das Modell noch verbessern."

(Note for this report only. The actual scanned text used a spaced en dash after "gut," and a semicolon after "zufrieden," to match the task's instruction. The scan result below names those two characters by rule name. It does not retype them, because this document's own house rules forbid the raw characters.)

Result. Exactly 2 findings.
- `punctuation` family, `banned_dash` rule, on the spaced en dash.
- `punctuation` family, `prose_semicolon` rule, on the semicolon.

Nothing fired on the German „…" quotation marks. Nothing fired on the passive-voice or banned-modal-verb English-lexical families either. That gap held even though the sentence has an actual German modal, "könnte." **Conclusion.** ADW's punctuation-family rules are language agnostic. They already correctly flag the dash and the semicolon in German text. The English-lexical families, banned modals and passive-voice detection, key off English words and morphology. They give zero coverage on German prose. That gap is why the team plans German-specific rule work now.
