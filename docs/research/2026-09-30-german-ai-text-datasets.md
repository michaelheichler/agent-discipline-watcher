# German AI-generated text datasets for ADW

Purpose. ADW needs German prose written by language models from 2024 to 2026, to pair against the human side (German Wikipedia before 2018 plus sedthh/gutenberg_multilang). This note ranks existing datasets by fit. Fit means German text, an open license, recent models, and prose longer than a sentence.

## Ranked results

### 1. COLING 2025 GenAI Content Detection Task 1, multilingual subtask (best fit)

- URL (official data and code). https://github.com/mbzuai-nlp/COLING-2025-Workshop-on-MGT-Detection-Task1
- URL (paper). https://arxiv.org/abs/2501.11012
- URL (unofficial HF mirror with a de tag). https://huggingface.co/datasets/anyangsong/COLING2025-MGT-Detection-Task1
- License. The official GitHub repo carries Apache-2.0 (confirmed through the GitHub API). The HF mirror also states MIT for its own copy. Review both terms before reuse.
- German coverage. The multilingual subtask covers 21 languages and lists `de` explicitly, alongside en, zh, it, ar, ru, bg, ur, id.
- Models. GPT-4o and Llama-3.1, per the paper's own description, plus the older generator set the task inherited from SemEval-2024 Task 8. These are 2024 models, the most recent of any dataset in this note.
- Genre. Student essays and academic peer reviews, multi-sentence prose.
- Human counterpart. Yes, the task is a binary human versus machine label on the same domains.
- Caveat. The HF datasets-server info endpoint returned a loading-script error for this repo, so the API gave no exact German row count. Confirming the row count needs a manual download or a Croissant-converted copy.

### 2. SemEval-2024 Task 8 / M4GT-Bench, multilingual subtask A

- URL (paper). https://arxiv.org/abs/2404.14183
- URL (HF mirror with full schema and a de tag). https://huggingface.co/datasets/d0rj/SemEval2024-task8
- URL (official data repo). https://github.com/mbzuai-nlp/SemEval2024-task8 (currently disabled by a DMCA takedown notice)
- License. The HF mirror states apache-2.0. The official GitHub repo shows no license field. The DMCA takedown of that repo raises doubt about the underlying data rights. Treat the license claim as unverified beyond the mirror's own terms.
- German coverage. Confirmed. The subtaskA_multilingual config lists German among Arabic, Russian, Chinese, Indonesian, Urdu, and Bulgarian. Those seven non-English languages combine for 172,417 train rows. Getting the German-only count needs a filter on the `source` or `language` field.
- Models. GPT-3.5, LLaMA2, Cohere, Dolly-v2, BLOOMz. These are 2023 models, a generation behind what ADW wants.
- Genre. German text sources from Wikipedia.
- Human counterpart. Yes, label 0 for human and 1 for machine in the same file.

### 3. MULTITuDE

- URL (paper). https://arxiv.org/abs/2310.13606
- URL (data, Zenodo). https://zenodo.org/records/10013755
- URL (code). https://github.com/kinit-sk/mgt-detection-benchmark
- License. The code repo carries GPL-3.0. The dataset sits behind a Zenodo access request. That request limits use to research purposes from a verified academic email. It does not meet ADW's open-license bar, even though the request itself is free.
- German coverage. Confirmed, German is one of the 11 languages (ar, ca, cs, de, en, es, nl, pt, ru, uk, zh).
- Models. 8 multilingual LLMs, dated October 2023, so also a generation behind.
- Genre. News articles subsampled from MassiveSumm, generated from headlines.
- Human counterpart. Yes, 7,992 human texts against 66,089 machine texts across all 11 languages.

### Ruled out

- **PAN 2025 Voight-Kampff Generative AI Detection, Subtask 1** (https://pan.webis.de/clef25/pan25-web/generated-content-analysis.html, data on Zenodo https://zenodo.org/records/14962653). The overview paper names novels and neighborhood essays as sources. Those come from English-language corpora such as Brennan-Greenstadt. No German language tag turned up in any source examined. PAN ran a separate multilingual task that year for text detoxification, not detection, and that task does carry a German split.
- **Kaggle.** The searches surfaced only English-language competitions and datasets (`llm-detect-ai-generated-text`, `ai-vs-human-text-dataset`, and similar). No German-specific AI-text dataset came up on Kaggle in this research pass.
- **GermEval (2024 to 2026).** The announced tasks were Text Complexity Assessment, Flausch-Erkennung, Harmful Content Detection, LLMs4Subjects, and SustainEval. None of them target machine-generated text detection.
- **lmarena-ai/arena-human-preference-100k.** The dataset card states directly that it holds "English human preference evaluations," confirmed against the HF API schema. It carries no German rows.
- **allenai/WildChat-4.8M** (https://huggingface.co/datasets/allenai/WildChat-4.8M, license ODC-BY). The HF datasets-server statistics endpoint returned a `country` breakdown, not a `language` breakdown. The `language` field sits nested inside the per-turn `conversation` list, and the statistics endpoint only aggregates top-level columns. The best figure pulled here is 31,089 conversations tagged `country: Germany`, out of 781,368 rows in the sampled config. That number is a proxy for German speakers. It is not a confirmed count of German-language text. Getting that count needs a manual filter on the nested `language` field.

### Could not verify

- **OSF page titled "German generated text detection"** (https://osf.io/n8s4a/). This page surfaced during a search for a related paper. The paper is Fiedler and Döpke (2025), on AI detection in German theses. It appeared in International Review of Economics Education, 49:100321 (https://www.sciencedirect.com/science/article/pii/S1477388025000131). The OSF page rendered no content through the fetch used here. I did not confirm its data, its license, or its connection to the paper.
