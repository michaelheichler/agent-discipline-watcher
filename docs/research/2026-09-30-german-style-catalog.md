# German prose rule catalog for ADW

Ticket T-001 asks ADW to gate German prose at the same depth as English prose. This catalog lists German rules an implementation can build from, each with a definition, sources, a detection class, a concrete signal, and examples.

This catalog holds 80 rules from four sources, plus an extended Typography conflicts section, a Numbers table, and a Policy questions section. Detection class splits STATIC 49, SEMANTIC 25, and DOCUMENT 6. Rules 21 through 80, plus 12 merges folded into rules 5, 6, 7, 8, 9, 15, and the Typography conflicts section, cite humanizer-de pattern names and definitions under CC BY-SA 4.0. About 11 of those also cite a numeric detection threshold under MIT, since that number comes from the plugin's scripts rather than its pattern tables. The original 20 book-sourced rules carry no open license. They restate copyrighted book text in this document's own words, under fair use for commentary and analysis.

## The gap this catalog closes

A test scan (recorded in `docs/research/2026-09-30-german-support-facts.md`, section 6) ran this German paragraph through `scanner.scan_all` as prose.

```
Das Projekt läuft gut, die Ergebnisse sind vielversprechend. „Wir sind zufrieden", sagte die Leiterin, sie betonte die Zusammenarbeit und könnte das Modell noch verbessern.
```

The scan produced exactly two findings, `banned_dash` on the spaced en dash and `prose_semicolon` on the semicolon. Nothing fired on the German „…" quotation marks. Nothing fired on the passive voice. Nothing fired on the modal verb "könnte," a word a German reader flags on sight. ADW's punctuation rules work on German text today because punctuation is language agnostic. Its lexical rules key off English words and English morphology instead, so passive-voice detection, filler detection, and modal-verb bans give zero coverage on German prose. This catalog is the rule list that closes that coverage gap.

## Sources

1. Monika Salchert, *Verständliches Schreiben*, Selbstlernheft, Bundesakademie für öffentliche Verwaltung im Bundesministerium des Innern, 2nd edition, September 2012. Cited below as **BAköV**, by page number.
2. Andreas Baumert, *Professionell texten*, dtv Ratgeber / C.H. Beck, cited below as **Baumert**, by chapter and page number from the EPUB.
3. Stefan Gottschling, *Einfach besser texten*, GABAL, 2006, 164 pages. Cited below as **Gottschling**, by page number.
4. The humanizer-de Claude Code plugin, version 5.28.1. Sources are `references/patterns.md`, `references/de-naturalness.md`, `references/register-profiles.md`, `references/decision-tables.md`, and the scripts `german_pattern_lint.py`, `register_lint.py`, and `rhythm_lint.py`. Cited below as **humanizer-de**, by pattern number (`Muster N`) or script name. The plugin's own `NOTICE` file states a split license. Most of the plugin, including all three scripts, ships under MIT. It credits Siqi Chen's `blader/humanizer` project. The pattern tables in `references/patterns.md` ship under CC BY-SA 4.0. The Wikipedia article "Anzeichen für KI-generierte Inhalte" ("Signs of AI writing") is their source. This catalog keeps each humanizer-de pattern's own trigger words and numeric thresholds. It rewrites only the surrounding description. That split matches the credit terms of both licenses.

Each rule restates the source's point in this document's own words. This document copies no sentence from any source. Short German technical terms such as Nominalstil, Funktionsverbgefüge, Verbklammer, Floskel, and Schachtelsatz are field vocabulary, not copyrighted prose, and this document uses them freely.

**A private Duden skill, used as an idea source only.** A user-local Claude Code skill named `duden-rechtschreibung` informed the wording of the typography facts below. Its source book is *Duden, Einfach können, Rechtschreibung, Zeichensetzung und Grammatik*, Dudenredaktion, Cornelsen, 2025, ISBN 978-3-411-75696-4. It informed, in particular, the Apostroph, Auslassungspunkte, Ergänzungsstrich, and geschütztes-Leerzeichen entries below. This skill never ships with ADW. ADW never reads it at runtime. It is not a cited source, and this document names no page number from it. Where a fact below traces back to it, the fact also appears independently in a cited source (BAköV, Baumert, Gottschling, or humanizer-de). Or it stands as a plain, uncontested German typography rule with no author to credit.

**Reading coverage.** A first pass covered BAköV in full, Baumert Ch.3 and Ch.4, and Gottschling pages 30 to 61 and 142 to 143. A second pass added Baumert Ch.1. It also added Gottschling Ch.3, pages 62 to 99, Ch.4, pages 100 to 123, and Ch.5, pages 124 to 136. Rules 19 and 20 below come from that second pass. Gottschling Ch.5, "Werkzeuge," lists research websites and online dictionaries. It holds no prose-style content, so it added no new rule. Each book's glossary, index, footnotes, and literature list stayed unread in both passes. Those sections list names and citations, not style rules. A third pass read all 72 humanizer-de patterns in full. It also read the plugin's three deterministic scripts and its de-naturalness, register, and decision-table references. That pass added rules 21 through 80 below. It also added the merges and typography extensions that follow the rule table.

## Rule table

| # | id | detection class | maps to (English ADW) |
|---|----|----|----|
| 1 | de_satzlaenge | DOCUMENT | long_sentence |
| 2 | de_schachtelsatz | STATIC | long_sentence, dramatic_fragmentation |
| 3 | de_verbklammer | STATIC | new |
| 4 | de_nominalstil | STATIC | new |
| 5 | de_funktionsverbgefuege | STATIC | formulaic_construction, wordiness |
| 6 | de_passiv | SEMANTIC | passive_voice |
| 7 | de_doppelte_verneinung | STATIC | hedge_stack |
| 8 | de_floskel | SEMANTIC | dead_metaphor, corporate_idiom, business_jargon |
| 9 | de_fuellwort | STATIC | filler_phrase, filler, wordiness |
| 10 | de_blaehwort | STATIC | empty_intensifier |
| 11 | de_tautologie_pleonasmus | STATIC | wordiness |
| 12 | de_fremdwort_unerklaert | SEMANTIC | business_jargon, corporate_idiom |
| 13 | de_abkuerzung_unerklaert | STATIC | new |
| 14 | de_komposita_lang | DOCUMENT | new |
| 15 | de_verstaerkungswort_unbelegt | SEMANTIC | lazy_extreme, binary_contrast |
| 16 | de_modalverb_uebermass | STATIC | no exact match, see note |
| 17 | de_ausrufezeichen_stakkato | STATIC | performative_emphasis, emphasis_crutch |
| 18 | de_anrede_flapsig | STATIC | greeting_opener |
| 19 | de_informationscluster | STATIC | new |
| 20 | de_binnen_i | STATIC | new |
| 21 | de_symbolik_uebertreibung | STATIC | ai_tell |
| 22 | de_meta_kommentar | STATIC | meta_commentary |
| 23 | de_mechanische_konjunktionen | STATIC | filler_phrase |
| 24 | de_abschnitt_zusammenfassung | STATIC | ai_closer |
| 25 | de_dichotomie_zuspitzung | SEMANTIC | binary_contrast |
| 26 | de_trikolon | STATIC | three_item_list |
| 27 | de_partizip_oberflaechlich | SEMANTIC | new |
| 28 | de_vage_autoritaet | SEMANTIC | vague_declarative |
| 29 | de_falsche_erweiterung | SEMANTIC | new |
| 30 | de_hypernym_stapel | STATIC | vague_quantity |
| 31 | de_synonym_rotation | SEMANTIC | new |
| 32 | de_ki_marker_vokabular | STATIC | weighted_slop_marker |
| 33 | de_fake_analyse_anhang | SEMANTIC | new |
| 34 | de_komparativ_rahmung | SEMANTIC | new |
| 35 | de_fettschrift_uebermass | DOCUMENT | emphasis_crutch |
| 36 | de_falsche_liste | STATIC | new |
| 37 | de_emoji_ueberschrift | STATIC | new |
| 38 | de_register_kollaps | SEMANTIC | new |
| 39 | de_briefartig | STATIC | greeting_opener |
| 40 | de_kollaborativ_chatbot | STATIC | ai_closer |
| 41 | de_wissensgrenze | STATIC | new |
| 42 | de_prompt_ablehnung | STATIC | new |
| 43 | de_platzhaltertext | STATIC | new |
| 44 | de_suchlink_referenz | STATIC | new |
| 45 | de_markdown_statt_wikitext | STATIC | new |
| 46 | de_wikitext_artefakt | STATIC | new |
| 47 | de_defekter_link | SEMANTIC | new |
| 48 | de_zitatfabrikation | SEMANTIC | new |
| 49 | de_referenz_format | STATIC | new |
| 50 | de_falsche_kategorie | STATIC | new |
| 51 | de_abrupter_abbruch | STATIC | new |
| 52 | de_stilwechsel | SEMANTIC | new |
| 53 | de_bearbeitungszusammenfassung | STATIC | new |
| 54 | de_autoritaets_floskel | STATIC | rhetorical_setup |
| 55 | de_signposting | STATIC | throat_clearing |
| 56 | de_fragmentierte_ueberschrift | SEMANTIC | new |
| 57 | de_rhetorische_frage | SEMANTIC | rhetorical_setup |
| 58 | de_unternehmensschluss | STATIC | ai_closer |
| 59 | de_diff_verankert | STATIC | new |
| 60 | de_aphorismus_formel | STATIC | formulaic_construction |
| 61 | de_isometrisches_dokument | DOCUMENT | uniform_paragraph_endings |
| 62 | de_markerloser_schluss | SEMANTIC | ai_closer |
| 63 | de_ankuendigungs_spaltsatz | STATIC | rhetorical_setup |
| 64 | de_retroaktive_scheinnuance | SEMANTIC | new |
| 65 | de_konditional_stapel | STATIC | hedge_stack |
| 66 | de_epistemisches_fehlvertrauen | SEMANTIC | lazy_extreme, hedge_stack |
| 67 | de_lueckenfuellende_spekulation | SEMANTIC | vague_declarative |
| 68 | de_erfundene_icherfahrung | SEMANTIC | new |
| 69 | de_falsche_agency | SEMANTIC | false_agency |
| 70 | de_pseudotherapeutische_validierung | STATIC | new |
| 71 | de_beleginkongruenz | SEMANTIC | new |
| 72 | de_versteckte_unicode | STATIC | new |
| 73 | de_standard_kapitel_leer | SEMANTIC | vague_declarative |
| 74 | de_anglizismus_struktur | STATIC | business_jargon |
| 75 | de_englische_titel_grossschreibung | STATIC | new |
| 76 | de_englisches_zahlenformat | STATIC | new |
| 77 | de_stichpunkt_interpunktion | STATIC | new |
| 78 | de_obsessive_parataxe | DOCUMENT | dramatic_fragmentation |
| 79 | de_markdown_artefakt | STATIC | new |
| 80 | de_gleichfoermiger_rhythmus | DOCUMENT | low_sentence_variance |

Rules 21 through 80 come from humanizer-de. Each row names the pattern's closest English ADW rule where one exists. Twelve more humanizer-de patterns do not get a new row. The next section merges each of those twelve into an existing rule above, or into the Typography conflicts section below.

Rule 16 has no exact English twin in `catalog.py`. English ADW bans a fixed adverb list through `banned_adverb`, not a modal-verb list. The nearest parallel sits outside `catalog.py` entirely. This project's own global CLAUDE.md bans a short list of English hedging modals in prose. German sources ban a parallel list of German modal verbs (spelled out in rule 16 below) as sentence-final auxiliary clutter for a similar reason. That symmetry is one of the three strongest rules in this catalog, named again in the closing summary.

## Rule entries

### 1. de_satzlaenge

**Definition.** A sentence carries too many words for a reader to hold in working memory on one pass. German readability research treats sentence length as the single strongest predictor of how hard a text is to read.

**Sources.** BAköV p.13 states a sentence gets critical from about 15 words. BAköV p.42 gives a checklist cap of 15 to 18 words. Baumert Ch.3 p.62 gives 10 to 15 words as a fair average for understandable German text, with 10 as the floor for weak readers, and separately cites the Amstad formula's own worked example, where 15 words per sentence and 1.8 syllables per word, a length the book calls typical for German, produces a Flesch score near 59.7 (good). Gottschling p.142 to 143 cites a spoken-language recall limit near 14 words and sets a practical range of 14 to 20 words, with anything past 20 marked for a forced split.

**Numeric threshold.** Three sources converge on the same narrow band from three independent angles, a plain critical-length observation (BAköV), a readability-formula worked example (Baumert), and a spoken-memory study (Gottschling). Use 15 words as the flag point and 20 words as the hard-split point. This is the strongest cross-source-confirmed number in the whole catalog.

**Detection class.** DOCUMENT. Sentence length is a per-sentence word count, aggregated across a file into a distribution, the same shape as the existing `long_sentence` and `low_sentence_variance` rules already use for English.

**Detection signal.** Split text on sentence-ending punctuation, count words per sentence by whitespace, flag any sentence over 20 words, and flag a file whose average sentence length sits over 15 words with low variance (a sign of uniformly dense prose, not a single long sentence).

**Bad example.**
```
Nachdem die Arbeitsgruppe sämtliche eingereichten Vorschläge gesichtet und mit den zuständigen Fachbereichen abgestimmt hatte, wurde die überarbeitete Fassung, die zahlreiche Änderungen gegenüber dem ursprünglichen Entwurf enthielt, den Mitgliedern zur endgültigen Abstimmung vorgelegt.
```

**Good example.**
```
Die Arbeitsgruppe sichtete alle Vorschläge und stimmte sie mit den Fachbereichen ab. Die Mitglieder stimmten danach über die überarbeitete Fassung ab.
```

### 2. de_schachtelsatz

**Definition.** A Schachtelsatz nests one subordinate clause inside another instead of placing clauses one after the other. The reader must hold the outer clause open across the whole inner clause before the sentence resolves.

**Sources.** BAköV p.13 caps a sentence at one subordinate clause. BAköV p.42 names "keine Schachtelsätze" and "keine Satzklammern" directly as checklist items. Baumert Ch.3 p.65 to 66 gives a worked nested example about a shipping company and a competitor, then a second short example about a mail carrier and dogs, and recommends that clauses attach one after another instead of inside each other. Gottschling p.35 gives a rule of thumb that a sentence grows hard to follow past its third comma, and p.144 gives a manual check, circle every comma in a draft and look for clauses trapped inside other clauses.

**Numeric threshold.** Gottschling's comma rule of thumb, more than three commas in one sentence signals a Schachtelsatz risk, p.35.

**Detection class.** STATIC. A regex count of commas plus subordinating conjunctions per sentence (`dass`, `weil`, `obwohl`, `während`, `nachdem`, `wenn`, relative pronouns `der/die/das/welche` in a non-sentence-initial position) catches the pattern without a full parse.

**Detection signal.** Count commas per sentence and flag past three. Separately count subordinating conjunctions and relative pronouns per sentence and flag two or more, since two subordinators in one sentence usually means one clause sits inside another rather than after it.

**Bad example.**
```
Der Bericht, der von der Abteilung, die für die Auswertung zuständig ist, vor zwei Wochen fertiggestellt wurde, liegt jetzt vor.
```

**Good example.**
```
Die Abteilung für Auswertung hat den Bericht vor zwei Wochen fertiggestellt. Er liegt jetzt vor.
```

### 3. de_verbklammer

**Definition.** German can split a verb into two parts and place unrelated information between them, for example a separable prefix, a modal verb with its infinitive, or an auxiliary with its participle. A wide gap between the two halves forces the reader to hold the sentence open until the second half finally arrives.

**Sources.** Baumert Ch.3 p.55 to 56 calls this construction a Verbklammer and gives two worked examples, one with a separable verb and one with a modal verb, showing how moving the closing half earlier shortens the gap without changing the meaning. BAköV p.42 names "keine Satzklammern" as a checklist item without a worked example.

**Numeric threshold.** None of the three sources gives a token-distance number for how wide a Verbklammer may be before it hurts readability. This is a gap, flagged again in the source-disagreement section below.

**Detection class.** STATIC. Measure the token distance between a separable-prefix verb stem and its prefix, or between a modal verb and its infinitive, or between an auxiliary and its participle, using part-of-speech tags or a fixed list of modal and auxiliary verbs plus a search for a bracketed infinitive or participle later in the sentence.

**Detection signal.** Flag a sentence where more than six words sit between a modal or auxiliary verb and the infinitive or participle it depends on.

**Bad example.**
```
Die oberen Räume muss der Pförtner zum Ende der Veranstaltung, spätestens aber wenn der Trainer das Gebäude verlassen hat, schließen.
```

**Good example.**
```
Die oberen Räume muss der Pförtner schließen, wenn die Veranstaltung endet oder der Trainer das Gebäude verlässt.
```

### 4. de_nominalstil

**Definition.** Nominalstil turns a verb into a noun and props the sentence up with a weak substitute verb. The action disappears into a noun, and the reader loses the sense of who does what.

**Sources.** Baumert Ch.3 p.50 to 51 names the pattern directly, walks through the shift from "beißen" to "das Beißen ... erfolgt," and gives a second worked example about cows and hens. BAköV repeats the same warning at p.5, p.11, p.16, and p.41, and names four noun endings as the tell. Baumert's Ch.3 practice-section list at p.71 repeats the same two endings.

**Numeric threshold.** None of the three sources gives a density number, such as nominalizations per hundred words. This is a gap.

**Detection class.** STATIC. A word-ending regex plus a short verb list catches the pattern without a parse.

**Detection signal.** Flag nouns ending in `-ung`, `-heit`, `-keit`, or `-schaft` that sit next to a weak carrier verb from this list, `erfolgen`, `geschehen`, `passieren`, `sich ereignen`, `stattfinden`, `vorliegen`.

**Bad example.**
```
Der Versand der Ware erfolgt am Tag der Bestellung.
```

**Good example.**
```
Wir versenden die Ware am Tag der Bestellung.
```

### 5. de_funktionsverbgefuege

**Definition.** A Funktionsverbgefüge, also called a Streckverb construction, pairs a weak generic verb with a preposition and a noun to do the work of one plain verb. The construction adds words without adding meaning.

**Sources.** Baumert Ch.3 p.56 to 57 and p.71 names the pattern and gives a worked list of pairs. BAköV p.19 to 23 gives a parallel list under its own "Spartipp" heading.

**Numeric threshold.** None given. Both sources treat the rule as absolute, not a density threshold, except for a named exception, a Funktionsverbgefüge stays if no single verb carries the same nuance (Baumert p.57).

**Detection class.** STATIC. A fixed phrase list, self-written from the two sources, catches the common cases directly.

**Detection signal.** Flag these phrase pairs, `in Frage stellen` for `bezweifeln`, `zur Sprache bringen` for `ansprechen` or `erwähnen`, `zur Anwendung bringen` for `anwenden`, `in Erwägung ziehen` for `erwägen`, `zur Kenntnis bringen` or `zur Kenntnis nehmen` for `sagen` or `wissen`, `in Gang setzen` for `starten`, `Rache nehmen` for `sich rächen`.

**Bad example.**
```
Lassen Sie uns heute eine Technik zur Sprache bringen, die einige in Frage stellen.
```

**Good example.**
```
Lassen Sie uns heute über eine Technik reden, die einige bezweifeln.
```

**Merge from humanizer-de.** Muster 65, Kopula-Vermeidung, names the mirror habit. The writer swaps a plain copula (`sein`, `haben`) for a heavier verb phrase to sound more active. `german_pattern_lint.py` flags this at two or more hits per text (`COPULA_AVOIDANCE`, threshold `>=2`). It is the same padding problem as the Funktionsverbgefüge above, approached from the opposite direction, a weak verb dressed up instead of a plain verb split apart. Add the script's word list as a second detection signal on this rule, not a new rule id.

### 6. de_passiv

**Definition.** The Passiv drops the actor from a sentence and promotes the object of the action to subject. German marks it with `werden` plus a participle, or, in its harder-to-spot Zustandspassiv form, with `sein` plus a participle and a silently dropped `worden`.

**Sources.** BAköV p.19 gives one worked before-and-after pair and states the rule "Aktiv schlägt Passiv" among its 13 core rules, p.6 and p.43. Baumert Ch.3 p.63 to 65 gives three worked examples and a named technique, the Null-Passiv-Methode, a one-month self-check where the writer rewrites every Passiv sentence found into Aktiv. Gottschling does not cover the Passiv directly in the chapters read for this catalog.

**Numeric threshold.** None given. Baumert treats Passiv as acceptable in small amounts and calls it a seasoning, not a forbidden construction, p.64, while BAköV and Baumert's own safety-text checklist (Ch.3 p.72) both ban it outright in safety-relevant and press-facing text.

**Detection class.** SEMANTIC. Spotting `werden` plus participle is a STATIC pattern, but judging whether the missing actor matters, and whether this is a Vorgangspassiv or a stand-alone Zustandspassiv, needs an embedding vote plus an LLM judge, the same split English `passive_voice` already uses.

**Detection signal.** Flag a `werden` auxiliary paired with a past participle where no `von` or `durch` phrase names an actor in the same sentence. Separately flag `sein` plus participle constructions that describe a completed action rather than a state.

**Bad example.**
```
Die Gebühren für das Schwimmbad werden erhöht.
```

**Good example.**
```
Die Stadt erhöht die Gebühren für das Schwimmbad.
```

**Merge from humanizer-de.** Muster 39, Passiv und subjektlose Fragmente, names the same construction. It adds one signal. It flags a short sentence fragment that drops the subject, not only the actor, next to a Passiv sentence. Treat this as a second detection signal on this rule.

### 7. de_doppelte_verneinung

**Definition.** A sentence stacks two negation markers where one would carry the meaning. The reader must cancel one negation against the other before the sentence resolves.

**Sources.** Baumert Ch.3 p.67 to 68 gives a worked example with two "nicht" markers in one sentence and calls doubled negation a Verständnis-Falle, a trap for comprehension. BAköV p.18 gives a parallel word-pair list for turning single negations into positive statements.

**Numeric threshold.** Baumert's own practical rule, at most one negation per sentence, p.68.

**Detection class.** STATIC. Count negation markers per sentence with a regex.

**Detection signal.** Flag a sentence with two or more of `nicht`, `kein`, `nie`, `niemals`, or a word starting with `un-` used as a negating prefix.

**Bad example.**
```
Die Maschine dürfen Sie nicht einschalten, wenn die Temperatur nicht unter achtzig Grad gesunken ist.
```

**Good example.**
```
Schalten Sie die Maschine erst ein, wenn die Temperatur unter achtzig Grad gesunken ist.
```

### 8. de_floskel

**Definition.** A Floskel is a worn phrase that once carried a real meaning and now only fills space, a stock opener, a stock closer, or a dead metaphor repeated so often it no longer paints a picture.

**Sources.** BAköV p.22 lists ten worn images directly, and p.26 to 27 lists worn letter openers and closers such as "Wir möchten Sie bitten" and "In der Anlage." Gottschling p.55 cites Wahrig's dictionary definition, "leere Redensart, Formel," and gives its own resolved word list at p.57, including `unter Zuhilfenahme` for `mit`, `diesbezüglich` for nothing (cut it), and `nichtsdestotrotz` for `trotzdem`.

**Numeric threshold.** None given by any source.

**Detection class.** SEMANTIC. Fixed phrases catch known cases through a STATIC list, but a worn phrase absent from any list needs an embedding vote against known Floskeln plus an LLM judge, the same way English `dead_metaphor` and `corporate_idiom` already split STATIC hits from SEMANTIC judgment.

**Detection signal.** Maintain a combined phrase list from both sources (`in der Anlage`, `wir möchten Sie bitten`, `unter Zuhilfenahme`, `diesbezüglich`, `nichtsdestotrotz`, `als Erstunterzeichner`, `Sturm im Wasserglas`, `eine Lanze brechen`, `Silberstreif am Horizont`) and flag exact and near matches.

**Bad example.**
```
Unter Zuhilfenahme der beigefügten Unterlagen teilen wir Ihnen diesbezüglich mit, dass wir Ihnen gerne eine Lanze brechen.
```

**Good example.**
```
Mit den beigefügten Unterlagen unterstützen wir Sie gern.
```

**Merge from humanizer-de.** Three more patterns name worn openers and closers of the same kind. Add each phrase list below as an extra detection signal on this rule, not a new rule id.

- **Muster 36, Menschheitserfahrungs-Eröffnung.** An opener that frames the topic as a universal human truth. Phrases include `Seit Anbeginn der Zeit` and `In der Geschichte der Menschheit`.
- **Muster 37, "In der heutigen X-Welt."** A stock opener that names the current era before the real point. Phrases include `In der heutigen schnellen Welt` and `In der heutigen digitalen Landschaft`.
- **Muster 6, unpassendes Fazit.** A "Fazit" or "Zusammenfassung" heading dropped into a short passage or a talk page comment that never needed one.

### 9. de_fuellwort

**Definition.** A Füllwort, also called a Modalpartikel or Abtönungspartikel in linguistics, softens or colors a statement without adding information. A sentence keeps its meaning if the word disappears.

**Sources.** BAköV p.23 gives the Mannheimer Institut für deutsche Sprache's top-20 most frequent German words, plus a named filler list, `irgendwie`, `eigentlich`, `aber`, `doch`, `also`, `auch`, `jedoch`, `obschon`. Gottschling p.55 to 56 gives a second, overlapping list of Abtönungspartikeln, `na`, `denn`, `ja`, `so`, `doch`, `nun`.

**Numeric threshold.** None given. BAköV frames the Mannheimer list as a frequency ranking, not a per-paragraph cap.

**Detection class.** STATIC. A merged word list from both sources, deduplicated, flags candidates directly.

**Detection signal.** Flag `irgendwie`, `eigentlich`, `jedoch`, `obschon`, `na`, `denn`, `nunmehr`, and `lediglich` outside a quoted dialogue block, since these carry the least information under BAköV's frequency data and Gottschling's Abtönungspartikel list.

**Bad example.**
```
Das müssen wir eigentlich irgendwie anders anpacken, das ist doch nun mal so.
```

**Good example.**
```
Wir müssen das anders anpacken.
```

**Cross-reference to humanizer-de, not a merge.** Muster 63, Modalpartikel-Anomalie, flags the opposite failure. It fires when a casual passage has zero Modalpartikeln (`ja, doch, eben, halt, wohl, mal, schon, ohnehin`, from `register_lint.py`), which reads as stiff machine translation, or when a formal passage has a cluster of more than three. This rule bans the words outright. Muster 63 judges their absence or overdose by register. Keep the two rules separate. Do not merge the word list.

### 10. de_blaehwort

**Definition.** A Blähwort is an intensifier that inflates a statement without adding proof. Gottschling calls this group "Trittbrettfahrer," words that hitch a ride on a claim instead of earning their place.

**Sources.** Gottschling p.51 to 52 gives a word list to mark during editing, `ganz, sehr, durchaus, unbedingt, absolut, völlig, voll und ganz, total`. Baumert Ch.4 p.101 to 102 names Blähwörter directly with a worked example on `völlig`, and separately flags the prefixes `an-` and `un-` added out of habit, `anmieten` for `mieten`, `Unkosten` for `Kosten`.

**Numeric threshold.** None given by either source.

**Detection class.** STATIC. The word list plus the prefix pair form fixed matches.

**Detection signal.** Flag the eight listed words plus `anmieten` and `Unkosten` as exact matches.

**Bad example.**
```
Das Angebot ist absolut völlig ausreichend für unsere Zwecke.
```

**Good example.**
```
Das Angebot reicht für unsere Zwecke.
```

### 11. de_tautologie_pleonasmus

**Definition.** A Tautologie pairs two near-synonyms into one phrase, `nie und nimmer`. A Pleonasmus adds a modifier that the noun already implies, `der weiße Schimmel`, since a Schimmel is by definition a white horse.

**Sources.** Gottschling p.56 to 57 names both figures and gives the Schimmel example. BAköV p.19 to 23 gives the identical `weißer Schimmel` example from a separate source, confirming the pattern by independent example rather than shared origin.

**Numeric threshold.** None given.

**Detection class.** STATIC. A fixed phrase list catches the named cases.

**Detection signal.** Flag `nie und nimmer`, `immer und ewig`, `weißer Schimmel`, `die gemachten Erfahrungen`, `der telefonische Anruf`, and `voll und ganz`. Gottschling notes `voll und ganz` and `für immer und ewig` can serve tone in a declaration of love, so a reviewer may keep either phrase in clearly emotional writing.

**Bad example.**
```
Der telefonische Anruf kam wegen der gemachten Erfahrungen mit dem weißen Schimmel.
```

**Good example.**
```
Der Anruf kam wegen der Erfahrungen mit dem Schimmel.
```

### 12. de_fremdwort_unerklaert

**Definition.** A foreign word, mostly an English loanword today, stands in a German sentence without a check on whether the reader knows it. The writer assumes understanding instead of confirming it.

**Sources.** Baumert Ch.3 p.51 to 54 gives four reasons to restrict foreign words in the writer's own words. First, the reader may not know it, so check the reader group first. Second, a careless Anglicism irritates the reader, and dropping it often reads as more polite. Third, a writer maintains the working tool, language, the way any craftsperson maintains a tool. Fourth, a foreign word can read as showing off. Baumert cites Endmark GmbH slogan studies from 2003, 2006, and 2009, where the best-scoring English-German slogan tested, "Sense and Simplicity," was still understood correctly by only 48 percent of respondents. Gottschling p.58 to 59 gives three rules of thumb. Use English only where German lacks a good word. Use it where the product sells worldwide. Use it only where the writer trusts the audience to understand or pronounce it.

**Numeric threshold.** The Endmark figure, 48 percent correct understanding for the top-scoring slogan tested, Baumert Ch.3 p.52.

**Detection class.** SEMANTIC. Whether a given foreign word needs a gloss depends on the named audience, so this needs an LLM judge over the surrounding context rather than a fixed list.

**Detection signal.** Flag an English loanword with no German gloss nearby, then let the judge weigh the target readership named in the document or its metadata.

**Bad example.**
```
Unser Sense and Simplicity Ansatz überzeugt jeden Kunden sofort.
```

**Good example.**
```
Unser einfacher, klarer Ansatz überzeugt jeden Kunden sofort.
```

### 13. de_abkuerzung_unerklaert

**Definition.** An abbreviation stands in for a full word or phrase without spelling it out first. A reader unfamiliar with the shortcut has to guess at its meaning.

**Sources.** Baumert Ch.3 p.54 to 55 and p.71 to 72 names `usw.`, `bzw.`, and `d.h.` as near-always superfluous, and argues their presence signals the writer has not thought the sentence through. Baumert recommends deleting the abbreviation rather than spelling it out, except for unavoidable cases such as currency signs, titles, and fixed legal forms like `GmbH`, `PKW`, or `PC`. BAköV p.19 to 23 gives a second list of abbreviations to spell out at first use, `Fam.`, `Fa.`, `MfG.`, `s.o.`, `dergl.`, `u.U.`, and `wg.` The two sources agree with no conflict found.

**Numeric threshold.** None given.

**Detection class.** STATIC. A fixed flag list plus an allow list.

**Detection signal.** Flag `usw.`, `bzw.`, `d.h.`, `u.U.`, `dergl.`, and `s.o.` Allow `GmbH`, `PKW`, `PC`, and `e.V.` without a flag.

**Bad example.**
```
Wir liefern usw. alle Teile, bzw. die noch fehlenden Stücke, d.h. bis Freitag.
```

**Good example.**
```
Wir liefern alle Teile und die noch fehlenden Stücke bis Freitag.
```

### 14. de_komposita_lang

**Definition.** German builds long compound nouns by chaining shorter words into one, such as `Festplattencontrollerkabel`. Past a certain length the chain stops reading as one word and starts reading as a puzzle.

**Sources.** Baumert Ch.3 p.48 to 49 credits Wolf Schneider's term "Silbenschleppzug" for these chains, and gives an escalating joke example that grows from `Festplattencontrollerkabel` to `Festplattencontrollerkabelanschlussklemme`. Baumert allows short, dictionary-listed compounds such as `Kaffeemaschine` and `Plastiktragetasche`, and objects only past that point. Gottschling p.36 to 38 grounds the same complaint in eye-tracking research. A fixation, the moment the eye holds still on text, lasts about two-tenths of a second. A saccade, the jump between fixations, takes two- to five-hundredths of a second. Sharp vision during a fixation covers a circle about two to three centimeters wide at normal reading distance. Gottschling names `Automobilzuliefererkonferenz` and `Tapeziertischoberfläche` as unreadable in one fixation and recommends a hyphen split, `Tapeziertisch-Oberfläche`.

**Numeric threshold.** Gottschling p.145, Schreib-Trick Nr. 5, states a reader takes in about five to six syllables per fixation at a 12-point type size.

**Detection class.** DOCUMENT. Syllable counting needs the whole word, and a per-document sweep catches every long compound in one pass.

**Detection signal.** Count vowel clusters per word as a syllable estimate. Flag any compound of six or more syllables that carries no internal hyphen, and suggest a hyphen split or a genitive rewrite, `Oberfläche des Tapeziertisches` instead of `Tapeziertischoberfläche`.

**Bad example.**
```
Der Automobilzuliefererkonferenzraum war bereits ausgebucht.
```

**Good example.**
```
Der Konferenzraum für die Automobilzulieferer war bereits ausgebucht.
```

### 15. de_verstaerkungswort_unbelegt

**Definition.** An intensifying claim, often a superlative, states a maximum without proof standing next to it. A reader can always name a counterexample to an unproven "best" or "most."

**Sources.** Gottschling p.49 to 54 opens with a Bismarck-attributed point that any superlative invites a challenge. An unqualified claim like "das schönste Auto der Welt" sits open to legal challenge, while framing it as a named person's opinion, "Für Tester Müller...," defends it, and a dated, sourced claim, "Seit 1632 verbrieft," defends it best of all. Gottschling gives a five-point fix list at p.53. First, frame the claim as a named opinion. Second, soften it with `wohl` or `vielleicht`. Third, use a verified intensifier with care, such as `Spitzenservice`. Fourth, strengthen the claim through comparison rather than a bare superlative, `steinreich` instead of `sehr reich`. Fifth, pick the one correct concrete word, `Sturm` instead of `starker Wind`.

**Numeric threshold.** None given.

**Detection class.** SEMANTIC. Judging whether a citation, a date, or a named person in the same passage backs the claim needs an LLM judge, not a word list.

**Detection signal.** Flag a superlative or absolute claim with no named source, date, or attributed opinion in the same sentence or the one next to it.

**Bad example.**
```
Der neue BMW 3000 ist das schönste Auto der Welt.
```

**Good example.**
```
Für Tester Müller ist der neue BMW 3000 das schönste Auto, das er je gefahren hat.
```

**Merge from humanizer-de.** Muster 2, Werbesprache und Superlative, names a related but narrower case. It flags a cluster of promotional adjectives (`innovativ, nahtlos, robust, umfassend, bahnbrechend`) even where no bare superlative sits in the sentence. Add the word list as an extra detection signal on this rule. Keep the citation-or-attribution test above as the main judgment call.

### 16. de_modalverb_uebermass

**Definition.** A sentence built around a modal verb, `können, müssen, möchten, dürfen, wollen, sollen, würden`, pushes the real action verb to the far end of the sentence as an infinitive. The reader waits through the whole sentence to learn what happens.

**Sources.** Gottschling p.144 to 145, Schreib-Trick Nr. 6, "Schreiben Sie im Verbalstil," gives a 26-word corporate sentence built on "möchte" as its bad example, where the reader learns nothing concrete until the final clause. Gottschling frames the fix as naming what a product does, not what it could do, and states this rule holds strictly for ad copy that describes a product's action.

**Numeric threshold.** None given. The rule is a word list plus a structural check, not a density count.

**Detection class.** STATIC. The seven listed verbs are a fixed list, though the exception carve-out below needs a documented rule, not a full regex solve.

**Detection signal.** Flag `können, müssen, möchten, dürfen, wollen, sollen, würden` when the verb governs a sentence-final infinitive or participle that carries the sentence's real meaning. Gottschling names three exceptions. A polite request, "Darf ich bitten," stands. A deliberate relativizing choice stands, such as a bank stating a product "10% Rendite erzielen können" rather than promising 10% outright. `Können` in its plain capability sense stands, since that use names an ability rather than hedging a claim.

**Bad example.**
```
Wir möchten Sie darauf hinweisen, dass unser neues Produkt Ihnen helfen könnte, Ihre Prozesse zu verbessern.
```

**Good example.**
```
Unser neues Produkt verbessert Ihre Prozesse.
```

### 17. de_ausrufezeichen_stakkato

**Definition.** A Stakkato-Satz is a short, often verb-less sentence. A run of several in a row, each closed with an exclamation mark, reads as loud and pushy rather than energetic.

**Sources.** Gottschling p.30 to 31 names this pattern "Stakkato-" or "Asthmatiker-Sätze" and gives a worked ad-copy example, "Endlich da! Das neue Sonderheft! Mode, Mode, Mode! Ab morgen am Kiosk. Gleich vorbeikommen! Anschauen! Kaufen!" Gottschling's own claim is direct. Too many exclamation marks in a row read as too loud and apply pressure to the reader. Gottschling treats the pattern as a deliberate pacing tool in ad copy, used with care, not a pattern to ban outright.

**Numeric threshold.** None given for how many exclamation marks in a row cross the line. This catalog sets its own working threshold below, marked as a gap filled by project judgment rather than a cited source.

**Detection class.** STATIC. A run of short, exclamation-marked sentences is countable directly from punctuation and word count.

**Detection signal.** Flag three or more consecutive sentences under six words each that each end in an exclamation mark.

**Bad example.**
```
Endlich da! Das neue Sonderheft! Jetzt zugreifen!
```

**Good example.**
```
Das neue Sonderheft ist endlich da. Jetzt am Kiosk.
```

### 18. de_anrede_flapsig

**Definition.** A salutation or closing reads as casual, spoken-register German rather than the neutral or formal register a business letter or official document expects.

**Sources.** BAköV p.26 to 27 flags casual salutations as unsuitable for official correspondence, `Hi`, `Tachchen`, `Moin Moin`, `Halli-Hallo`, and flags casual closings the same way, `Tschüssi`, `Mach's gut Alter`, `Und Tschüss`, `So long`. Baumert and Gottschling give no content read on this specific point in this catalog, so this catalog leaves the point unconfirmed by the other two sources rather than flags an actual disagreement.

**Numeric threshold.** None. This is a binary word-list match.

**Detection class.** STATIC. The flag list matches against the opening and closing lines of a document.

**Detection signal.** Flag `Hi`, `Tachchen`, `Moin Moin`, `Halli-Hallo`, `Tschüssi`, `Mach's gut Alter`, `Und Tschüss`, and `So long` when a reviewer or the document's own metadata marks the document as formal or business correspondence.

**Bad example.**
```
Tachchen Herr Schmidt, Ihre Bestellung ist da. So long!
```

**Good example.**
```
Sehr geehrter Herr Schmidt, Ihre Bestellung ist da. Mit freundlichen Grüßen.
```

### 19. de_informationscluster

**Definition.** A sentence overloads a reader's working memory when it packs more distinct information items into one clause than the reader can hold before the sentence resolves. An information item here is a number, a name, a listed noun, or a short embedded clause.

**Sources.** Baumert Ch.1 p.7 to 9 describes a chess experiment. Skilled players rebuilt a realistic board position from memory well, but got no better than beginners at a randomly scattered one. Baumert uses this to argue that working memory holds information in chunks, and that a known pattern, such as a real chess position or a familiar word, fits into one chunk, while an unfamiliar item takes up a chunk of its own. BAköV and Gottschling give no matching content in the chapters read for this catalog.

**Numeric threshold.** Baumert cites research placing working memory's practical limit at roughly seven to nine of these chunks. Past that count, the channel clogs, and the reader loses track before the sentence ends.

**Detection class.** STATIC. Count the comma-separated items, embedded numbers, and named entities inside one sentence. Flag the sentence when that count passes roughly eight.

**Detection signal.** Count commas that separate list items, plus digit groups, plus proper nouns, within one sentence span. A count above eight flags the sentence, independent of its word count, since a short sentence can still pack many named items.

**Bad example.**
```
Der Kunde bestellte die Artikel 4471, 4472 und 4473 in den Farben Rot, Blau, Grün und Gelb, lieferbar am Montag, Mittwoch oder Freitag über DHL, Hermes oder die Deutsche Post.
```

**Good example.**
```
Der Kunde bestellte die Artikel 4471, 4472 und 4473 in Rot, Blau, Grün und Gelb. Die Lieferung erfolgt an einem von drei möglichen Tagen über einen von drei Versanddienstleistern.
```

### 20. de_binnen_i

**Definition.** A gender-inclusive word form that places a capital letter inside a word, such as the capital I in "LeserInnen," breaks standard German spelling rules.

**Sources.** Baumert Ch.1 p.31 to 32 names five ways to write a gender-neutral German text. A writer can name both forms in full, use a participle form such as "die Lesenden," add the suffix "-innen" where the text allows it, use the capital-I form, or add a one-time note that tells the reader the masculine form stands for both genders. Baumert calls the capital-I form a plain spelling mistake, and recommends the one-time note for a longer text such as a book. BAköV and Gottschling give no matching content in the material read for this catalog.

**Numeric threshold.** None. This is a binary spelling-pattern match, not a countable threshold.

**Detection class.** STATIC. A regex match for a capital letter sitting right after a lowercase letter, inside one word.

**Detection signal.** Match a word carrying an interior capital letter at the known suffix pattern `-In` or `-Innen`, for example `LeserInnen`, `MitarbeiterInnen`, or `KundInnen`.

**Bad example.**
```
Die LeserInnen unseres Magazins schätzen klare Sprache.
```

**Good example.**
```
Die Leserinnen und Leser unseres Magazins schätzen klare Sprache.
```

## Rule entries from humanizer-de, rules 21 through 80

These 60 rules use a compact format. Each row names the humanizer-de pattern number, the severity humanizer-de assigns it (HIGH, MEDIUM, or LOW), and a short key signal. Every quoted German phrase below comes straight from `references/patterns.md`, kept in this catalog's own words around it, per the CC BY-SA 4.0 credit terms named in the Sources section above. Full definitions, worked examples, and exception carve-outs stay in the plugin file itself. This catalog does not copy them, since the rule ID and detection class here are enough for an implementation to build from, and the source stays one file path away.

### Sprache und Tonfall (rules 21 to 34)

Word- and phrase-level habits in diction and tone that read as machine-generated.

| # | id | Muster | severity | key signal |
|---|----|--------|----------|------------|
| 21 | de_symbolik_uebertreibung | 1 | HIGH | `steht als Zeugnis`, `spielt eine wichtige Rolle`, `symbolisiert` |
| 22 | de_meta_kommentar | 3 | HIGH | `es ist wichtig zu bemerken`, `es sollte hervorgehoben werden` |
| 23 | de_mechanische_konjunktionen | 4 | HIGH | `darüber hinaus`, `außerdem`, `ferner`, `ebenfalls`, overused as sentence openers |
| 24 | de_abschnitt_zusammenfassung | 5 | HIGH | `zusammenfassend`, `insgesamt`, `kurz gesagt` at a paragraph's start |
| 25 | de_dichotomie_zuspitzung | 7 | MEDIUM | `Trotz X... steht Y vor Z`, a praise-challenges-outlook three-beat template |
| 26 | de_trikolon | 9 | MEDIUM | a three-item list with no reason for exactly three |
| 27 | de_partizip_oberflaechlich | 10 | HIGH | `gewährleistend`, `hervorhebend`, `ermöglichend` as a shallow analysis tail |
| 28 | de_vage_autoritaet | 11 | HIGH | `Branchenberichte zeigen`, `Manche argumentieren`, no named source |
| 29 | de_falsche_erweiterung | 12 | MEDIUM | `von traditionellen bis modernen`, a span phrase over a false range |
| 30 | de_hypernym_stapel | 58 | MEDIUM | `Maßnahmen`, `Aspekte`, `Lösungen` stacked instead of a named concrete thing |
| 31 | de_synonym_rotation | 60 | MEDIUM | the same entity renamed each sentence, `die Hansestadt`, `die Elbmetropole` |
| 32 | de_ki_marker_vokabular | 64 | MEDIUM | `beleuchten`, `eintauchen`, `spannend`, `nahtlos`, `die digitale Landschaft` in a cluster |
| 33 | de_fake_analyse_anhang | 66 | MEDIUM | a relative clause tail, `was X unterstreicht`, that adds no new information |
| 34 | de_komparativ_rahmung | 68 | MEDIUM | `weniger X als vielmehr Y` standing in for a plain description |

### Stil (rules 35 to 38)

Surface formatting habits, not word choice.

| # | id | Muster | severity | key signal |
|---|----|--------|----------|------------|
| 35 | de_fettschrift_uebermass | 13 | MEDIUM | bold spans on five or more words per text (`BOLD_OVERDOSE_THRESHOLD = 5` in `german_pattern_lint.py`) |
| 36 | de_falsche_liste | 14 | LOW | a bullet character `•` used instead of Wikitext `-` or Markdown syntax where German Wikitext is expected |
| 37 | de_emoji_ueberschrift | 15 | LOW | an emoji placed before a heading, for example `🎓 Bildung` |
| 38 | de_register_kollaps | 69 | MEDIUM | a casual particle sitting inside an otherwise fully formal sentence and paragraph structure |

### Kommunikation (rules 39 to 44)

Tells that show the text never left chatbot-turn shape.

| # | id | Muster | severity | key signal |
|---|----|--------|----------|------------|
| 39 | de_briefartig | 17 | HIGH | `Betreff:`, `Liebe Wikipedia-Editoren`, `Mit freundlichen Grüßen` |
| 40 | de_kollaborativ_chatbot | 18 | HIGH | `Ich hoffe, das hilft`, `Natürlich!`, `Lassen Sie mich wissen` |
| 41 | de_wissensgrenze | 19 | HIGH | `Stand [Datum]`, `Bis zu meinem letzten Update` |
| 42 | de_prompt_ablehnung | 20 | HIGH | `Als KI-Sprachmodell kann ich nicht...`, `Es tut mir leid, aber...` |
| 43 | de_platzhaltertext | 21 | HIGH | `[Name einfügen]`, `[Datum hier]`, `TODO:` |
| 44 | de_suchlink_referenz | 22 | HIGH | a citation that is a raw `google.com/search?q=` link instead of a source |

### Auszeichnungstext (rules 45 to 50)

Markup and citation habits specific to Wikitext and reference formatting.

| # | id | Muster | severity | key signal |
|---|----|--------|----------|------------|
| 45 | de_markdown_statt_wikitext | 23 | MEDIUM | a Markdown `# Überschrift` where Wikitext `== Überschrift ==` belongs |
| 46 | de_wikitext_artefakt | 24 | MEDIUM | an incomplete template tag, or a literal `oaicite` or `contentReference` string left in the text |
| 47 | de_defekter_link | 25 | MEDIUM | a link that resolves to a 404 or to a nonexistent article |
| 48 | de_zitatfabrikation | 26 | HIGH | an invented source, an invalid DOI or ISBN, or a real source that does not back the claim next to it |
| 49 | de_referenz_format | 27 | MEDIUM | an English date order or field order inside a German reference |
| 50 | de_falsche_kategorie | 28 | MEDIUM | `[[Category:...]]` instead of the German `[[Kategorie:...]]` |

### Verschiedenes (rules 51 to 53)

Structural breaks that show incomplete generation or editing.

| # | id | Muster | severity | key signal |
|---|----|--------|----------|------------|
| 51 | de_abrupter_abbruch | 29 | LOW | the text stops mid-sentence |
| 52 | de_stilwechsel | 30 | MEDIUM | paragraphs that read as if written by different authors |
| 53 | de_bearbeitungszusammenfassung | 31 | LOW | a long first-person edit summary, `Ich habe einen Absatz über...` |

### Rhetorik und Struktur (rules 54 to 64)

Rhetorical scaffolding and whole-document structural uniformity.

| # | id | Muster | severity | key signal |
|---|----|--------|----------|------------|
| 54 | de_autoritaets_floskel | 32 | MEDIUM | `Die eigentliche Frage ist`, `Im Kern`, `In Wirklichkeit` |
| 55 | de_signposting | 33 | MEDIUM | `Schauen wir uns an`, `Hier ist, was Sie wissen müssen` |
| 56 | de_fragmentierte_ueberschrift | 34 | LOW | a generic one-line sentence right under a heading, `Geschwindigkeit zählt.` |
| 57 | de_rhetorische_frage | 35 | MEDIUM | `Aber was bedeutet das?` used as a fake engagement hook |
| 58 | de_unternehmensschluss | 38 | MEDIUM | `bestens aufgestellt`, `die Möglichkeiten sind grenzenlos` as a closing line |
| 59 | de_diff_verankert | 52 | MEDIUM | `wurde jetzt ergänzt`, `neu hinzugefügt`, `ersetzt die alte Lösung` |
| 60 | de_aphorismus_formel | 56 | MEDIUM | `X ist die Sprache des Y`, `X wird zur Falle` as a fill-in-the-blank aphorism |
| 61 | de_isometrisches_dokument | 61 | MEDIUM | every paragraph, section, and list holds close to the same length |
| 62 | de_markerloser_schluss | 62 | MEDIUM | an evaluative closing sentence at a paragraph's end that adds no new fact |
| 63 | de_ankuendigungs_spaltsatz | 67 | MEDIUM | `Was mich überrascht hat, war...` announcing a point instead of stating it |
| 64 | de_retroaktive_scheinnuance | 71 | MEDIUM | `Genauer gesagt...`, `Fairerweise...` followed by the same claim in softer words |

### Argumentation und Evidenz (rules 65 to 70)

How a claim gets hedged, sourced, or handed off to an abstraction instead of a named actor.

| # | id | Muster | severity | key signal |
|---|----|--------|----------|------------|
| 65 | de_konditional_stapel | 40 | MEDIUM | stacked `wenn` clauses, `Wenn das Argument stimmt, und wenn die Evidenz...` |
| 66 | de_epistemisches_fehlvertrauen | 41 | MEDIUM | overclaim words (`grundlegend`, `entscheidend`) paired with overhedge words (`scheint möglicherweise`) in the same passage |
| 67 | de_lueckenfuellende_spekulation | 53 | HIGH | `hält sich bedeckt`, `vermutlich`, used to paper over a missing source |
| 68 | de_erfundene_icherfahrung | 59 | HIGH | a staged first-person anecdote, `Ehrlich gesagt`, `Spoiler:`, with no real narrator behind it |
| 69 | de_falsche_agency | 70 | MEDIUM | `Die Strategie entschied`, `Die Kennzahl erzwang`, an abstract noun doing a decision only a person can make |
| 70 | de_pseudotherapeutische_validierung | 72 | HIGH | `Du bist nicht zu sensibel`, `Deine Gefühle sind valide`, an unearned diagnosis of the reader |

### Ergänzungen (rules 71 to 74)

A mixed set covering source integrity, character encoding, and thin structure.

| # | id | Muster | severity | key signal |
|---|----|--------|----------|------------|
| 71 | de_beleginkongruenz | 42 | HIGH | the cited source exists but does not back the claim next to it |
| 72 | de_versteckte_unicode | 43 | HIGH | a zero-width space (U+200B), a soft hyphen, a BOM, or a bidi control character (U+202A to U+202E, U+2066 to U+2069) hidden in the text |
| 73 | de_standard_kapitel_leer | 44 | MEDIUM | a standard heading followed by unsupported filler text, where the fix is to merge the section in or delete it |
| 74 | de_anglizismus_struktur | 45 | MEDIUM | a hard calque or false friend, `am Ende des Tages`, `eventuell` used to mean `schließlich` |

### Typografie und Format (rules 75 to 79)

English-sourced formatting habits leaking into German text.

| # | id | Muster | severity | key signal |
|---|----|--------|----------|------------|
| 75 | de_englische_titel_grossschreibung | 47 | MEDIUM | `Die Neue KI Strategie` instead of German sentence-case capitalization |
| 76 | de_englisches_zahlenformat | 48 | LOW | `3.5` instead of `3,5`, `May 12` instead of `12. Mai` |
| 77 | de_stichpunkt_interpunktion | 50 | LOW | capital letters and a closing period on a bare bullet keyword |
| 78 | de_obsessive_parataxe | 51 | MEDIUM | too many same-shaped main clauses with no subordination |
| 79 | de_markdown_artefakt | 57 | MEDIUM | a one-line table, a skipped heading level (H2 straight to H4), or a `---` rule dropped in front of a heading |

### Titel- und Satzbau (rule 80)

| # | id | Muster | severity | key signal |
|---|----|--------|----------|------------|
| 80 | de_gleichfoermiger_rhythmus | 55 | MEDIUM | sentences near-identical in length, subject-first, low burstiness |

## Typography conflicts between German rules and English ADW rules

**Gedankenstrich.** Gottschling p.33 to 34 gives German-correct typography for the Gedankenstrich, a dash spaced on each side. It marks a pause, a turn to a new thought, or a list item. English ADW's `banned_dash` and `spaced_hyphen` rules ban that exact construction in English prose. A German-aware ADW needs a language switch on this rule, not a shared ban. Merge in humanizer-de Muster 16, Dash-Satzzeichen und Gedankenstrich-Cluster, as a numeric backstop on top of Gottschling's qualitative rule. `german_pattern_lint.py` flags a text at `DASH_CLUSTER_MIN_COUNT = 5` dash-as-punctuation hits, or at a density over `DASH_CLUSTER_MIN_PER_1000_WORDS = 15.0` dashes per 1000 words, whichever threshold a text crosses first.

**Anführungszeichen.** Correct German typography uses the „…" quote pair, a low opening mark and a high closing mark. The earlier test scan in this project's own support-facts document found zero findings against these marks. English ADW's quote-adjacent rules tune for English straight and curly quote conventions. German quotes need an allow list of their own rather than a shared rule, since a false positive here has not yet turned up, but no one has tested it directly against `pronoun_apostrophe`. Merge in humanizer-de Muster 46, falsche deutsche Anführungszeichen, HIGH severity. It flags the mismatched pair „Text” (a German open mark paired with an English-style close mark, U+201E opening against U+201C closing) where a correct German pair should close with „Text“.

**Doppelpunkt.** Gottschling p.32 gives German-specific capitalization rules after a colon. The word after the colon stays lowercase if what follows is an incomplete clause, except a direct quotation, which always capitalizes. The word after the colon capitalizes if what follows is a full sentence. Either case is acceptable if a Gedankenstrich could stand in for the colon. English `prose_colon` bans a mid-sentence colon outright. German uses the colon as a structural connector, so this needs its own German rule rather than a ban carried over from English. Merge in humanizer-de Muster 54, Doppelpunkt-Titel-Schema, MEDIUM severity. It flags a document, not a single colon, where two or more headings repeat a `Phrase: Was/Warum/Wie` colon-title template, by the `colon_heading_count >= 2` threshold in `rhythm_lint.py`.

**Komma and Semikolon.** Gottschling p.34 to 35 supports the same greater-than-three-comma threshold already used in rule 2 above. Gottschling calls the semicolon "das seltenste Satzzeichen der deutschen Sprache," the rarest German punctuation mark, and names two reasons a reader reacts badly to it, its rarity and its tonal ambiguity. Gottschling names one legitimate use, joining two independently complete clauses to keep a suspended connection rather than a hard full stop. English `prose_semicolon` bans the mark outright. German treats it as rare but legitimate in that one case, another spot where a shared ban does not fit German prose.

**Apostroph.** New subsection, sourced from humanizer-de Muster 49 and the Duden skill's chapter on the Apostroph, idea-source only. German marks the genitive of a name with a bare `s`, `Peters Buch`, not an apostrophe. The one narrow exception is a name that already ends in an s-sound, `s, ß, x, z`, where the apostrophe alone marks the genitive, `Fritz' Buch`. Muster 49, MEDIUM severity, flags the English-style genitive apostrophe, `Peter's` for `Peters`, as the clearest case of this error entering German text through translation habits. The Duden skill also names one apostrophe that stays optional rather than wrong, the elision mark for a dropped `es` in casual contractions such as `Wie geht's`. This rule should not flag that optional form.

**Auslassungspunkte.** New subsection, Duden-sourced, idea-source only, with no matching humanizer-de pattern. German writes the ellipsis as one single "…" character, not three typed periods. It never gains a fourth dot at a sentence's end, and it never doubles up against an abbreviation point or an ordinal point that happens to sit next to it.

**Geschütztes Leerzeichen.** New subsection, Duden-sourced, idea-source only, with no matching humanizer-de pattern. DIN 5008 calls for a protected, non-breaking space in several fixed spots, between a number and its unit, inside a multi-part abbreviation, between a day and a month name, and before a percent sign. A plain breaking space in any of those spots lets a line break fall in the wrong place.

**Ergänzungsstrich.** New subsection, Duden-sourced, idea-source only, with no matching humanizer-de pattern. German elides a shared word part across a compound pair with a bare, unspaced hyphen, `Ein- und Ausgang` for `Eingang und Ausgang`. This hyphen carries no space on either side. That shape sits close enough to English ADW's `spaced_hyphen` and `banned_dash` rules that a scanner without a German-aware carve-out could misflag it. See the policy question on this exact risk below.

**Schriftbild.** Lower priority than the punctuation conflicts above. Gottschling p.38 to 39 notes that serif type such as Times reads slightly easier in print than grotesque type such as Arial, because the serifs form a reading line for the eye, while grotesque type serves screens better due to cleaner letter shapes. Bold and italic both cut legibility against normal weight and work best over a short span. This is a design note, not a prose-content rule, and fits better as a footnote than a gating rule.

## Where the three sources disagree

**Floskeln, Füllwörter, and Tautologien, a permissive stance against a flat ban.** Gottschling writes from a marketing and ad-copy angle and endorses controlled use of Floskeln, Füllwörter, Modalpartikeln, and Tautologien for emotional tone and reader rapport. BAköV writes from a bureaucratic-clarity angle and Baumert writes from a technical-clarity angle. Both treat the same categories as something to cut, full stop. This is the sharpest three-way split in the catalog, and it traces back to genre. Ad copy wants warmth. Official and technical writing wants a plain, checkable claim.

**Sentence length, a hard cap against a hedged guideline.** BAköV states a flat 15 to 18 word cap with no hedge attached. Baumert gives a close number, 10 to 15 words, but frames it as one imperfect signal among several, and states a preference for the Hamburger Verständlichkeitsmodell, a holistic rating method whose own authors, three professors in Hamburg, reject mechanical word counting outright and name that habit "Fliegenbeinzählerei." Gottschling gives a third number, 14 to 20 words, grounded in a spoken-memory recall study rather than a written-readability formula. All three land in the same rough band. Each reaches that band through a different argument and holds a different level of confidence in the number itself.

**Passiv, a seasoning against a ban.** Baumert calls Passiv acceptable in moderation and names it "ein Gewürz," a seasoning, framing it as a source of sentence variety that a writer corrects through self-review rather than bans outright. BAköV states the flat rule "Aktiv schlägt Passiv" with no seasoning exception. The two sources agree only in one case. Baumert's own Ch.3 p.72 safety checklist bans Passiv outright in safety-relevant and press-facing text, matching BAköV's flat rule exactly in that one context.

**Verbklammer, a cross-source gap.** Rule 3 above already names this as a single-source gap, but it holds across all three books. Each source describes the split-verb problem in qualitative terms. None gives a number for how far apart the two verb halves can sit before a reader loses the thread.

## Numbers table

Every numeric threshold named anywhere in this catalog, in one place, with its source.

| number | rule or section | source |
|---|---|---|
| 15 to 18 words | rule 1, de_satzlaenge, sentence length cap | BAköV |
| 10 to 15 words | rule 1, de_satzlaenge, sentence length average | Baumert Ch.3 p.62 |
| 14 to 20 words | rule 1, de_satzlaenge, spoken-recall limit | Gottschling p.142 to 143 |
| more than 3 commas per sentence | rule 2, de_schachtelsatz | Gottschling p.34 to 35, and the Komma/Semikolon typography note |
| at most 1 negation per sentence | rule 7, de_doppelte_verneinung | Baumert Ch.3 p.68 |
| `BOLD_OVERDOSE_THRESHOLD = 5` bold spans per text | rule 35, de_fettschrift_uebermass (Muster 13) | `german_pattern_lint.py` |
| `ANTITHESIS_CLUSTER_MIN_COUNT = 4`, or 3.0 hits per 1000 words | rule 25, de_dichotomie_zuspitzung (Muster 7) | `german_pattern_lint.py` |
| `DASH_CLUSTER_MIN_COUNT = 5`, or 15.0 dashes per 1000 words | Typography, Gedankenstrich (Muster 16) | `german_pattern_lint.py` |
| `ABSTRACTA` word count `>= 3` per text | rule 30, de_hypernym_stapel (Muster 58) | `german_pattern_lint.py` |
| `COPULA_AVOIDANCE` word count `>= 2` per text | merge on rule 5, de_funktionsverbgefuege (Muster 65) | `german_pattern_lint.py` |
| `AI_MARKERS` word count `>= 3` per text | rule 32, de_ki_marker_vokabular (Muster 64) | `german_pattern_lint.py` |
| `colon_heading_count >= 2` | Typography, Doppelpunkt (Muster 54) | `rhythm_lint.py` |
| `connector_density > 1` per paragraph | rule 23, de_mechanische_konjunktionen (Muster 4) | `rhythm_lint.py` |
| sentence length variance `stddev / mean < 0.4`, needs 8 or more sentences | rule 80, de_gleichfoermiger_rhythmus (Muster 55) | `rhythm_lint.py`, revalidated 2026-07 |
| subject-initial ratio (SIR) cluster fires only above 0.85, with length ratio below 0.6 or 2 or more repeated openers | rule 80, de_gleichfoermiger_rhythmus (Muster 55) | `rhythm_lint.py`. The 0.6 threshold replaced an earlier 0.4 on 2026-08-18, after 0.4 stopped separating naive-Claude text from human text (6 of 10 false negatives), at a measured cost of 4 false positives out of 20 human texts. |
| genuine pre-2022 human median SIR, 0.816 | note inside `rhythm_lint.py`, not a rule threshold | `rhythm_lint.py` code comment |
| `uniform_paragraphs`, 4 or more paragraphs with a sentence-count spread of 2 or less | rule 61, de_isometrisches_dokument (Muster 61) | `rhythm_lint.py` |
| Modalpartikel overdose cap, more than 3 particles, casual register only | cross-reference on rule 9, de_fuellwort (Muster 63) | `register_lint.py` |

## Policy questions for the user

Each question below names the disagreement first, then a recommendation.

1. **Should `de_binnen_i` (rule 20) call the capital-I gender form a spelling error, or stay neutral?** Baumert's source text calls it a plain spelling mistake outright. The form is also a live, contested choice in German gender-language debate, not a settled typo. Recommendation, keep the rule as written, SEMANTIC-adjacent reporting rather than a hard block, and name the political context in the rule's own text so a future editor sees the tradeoff instead of inheriting it silently.
2. **How hard should ADW flag Anglicisms, given the Duden skill and humanizer-de disagree in tone?** The Duden skill's `00-ki-schreibfallen.md` treats Anglicisms as a correction target across the board. Humanizer-de's own `de-naturalness.md` names an explicit carve-out, code, quotations, English product titles, and established loanwords in a technical field should not get flagged. Recommendation, follow the humanizer-de carve-out over the Duden skill's blanket stance, since ADW already scans developer-facing technical prose where established English terms are normal, not an error.
3. **Does the Ergänzungsstrich note above risk a false positive against `banned_dash` and `spaced_hyphen`?** The Ergänzungsstrich is a bare, unspaced hyphen inside a compound elision, `Ein- und Ausgang`. It should not collide with either English rule, since both target a spaced dash, not a bare compound hyphen. Recommendation, add one explicit test case for this exact construction once implementation starts, rather than assume the unspaced shape protects it.
4. **Should every HIGH-severity humanizer-de rule above block a turn, or only report?** `register_lint.py` and `rhythm_lint.py` both describe their own output as suspicions, not findings, in their code comments, including for some rules marked HIGH in `patterns.md`. Recommendation, gate on severity and detection class together, STATIC and HIGH blocks, SEMANTIC and DOCUMENT report first and let a judge decide, matching how rule 6, de_passiv, already splits STATIC detection from SEMANTIC judgment above.

**The missing canonical authors.** The companion document `docs/research/2026-09-30-german-style-sources.md` already found that the user's own library holds no Wolf Schneider, Ludwig Reiners, or Bastian Sick title. Yet BAköV's own Literatur list, p.44, and Baumert Ch.4 p.99, naming Sick, Schneider, Reiners, and Glunk as "die meist genannten Stilratgeber," both point to these names as the field's standard references. This catalog rests on two practitioner books and one government brochure rather than the field's own most-cited authors. That gap sits in source coverage, not in a disagreement between the three books read for this catalog.
