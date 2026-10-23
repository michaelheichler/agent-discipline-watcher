#!/usr/bin/env python3
"""Keep base forms only, because inflected entries such as scheidungen and nationale leaked into compound parts."""
import csv
import gzip
import hashlib
import importlib
import json
import re
import sys
import urllib.request
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import NamedTuple


class Source(NamedTuple):
    name: str
    url: str
    md5: str


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LEXICON_PATH = REPOSITORY_ROOT / "hooks" / "lib" / "german_compound_lexicon.txt.gz"
VERBS_PATH = REPOSITORY_ROOT / "hooks" / "lib" / "german_verbs.json.gz"
CACHE_ROOT = Path.home() / ".adw" / "cache" / "datasets" / "german-compounds"
NOUNS = Source(
    "gambolputty/nouns.csv",
    "https://raw.githubusercontent.com/gambolputty/german-nouns/main/german_nouns/nouns.csv",
    "72610a0e19f8050cb5019708275d7c88",
)
KAIKKI = Source(
    "kaikki/kaikki-German.jsonl",
    "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl",
    "01765add1a84e2c9a61e6771abb2e958",
)
WORD_RE = re.compile(r"^[a-zäöüß]{3,}$")
KAIKKI_POS = frozenset({"noun", "verb", "adj", "adv", "prep", "particle"})
FUNCTION_POS = frozenset({"adv", "prep", "particle", "conj", "det", "pron", "num", "postp", "article"})
INFLECTION_TAGS = frozenset({
    "nominative", "accusative", "dative", "genitive", "masculine", "feminine", "neuter",
    "singular", "plural", "strong", "weak", "mixed",
})
MIN_STEM = 3
SHORT_NOUN_LETTERS = 3
CHUNK_BYTES = 1 << 20


@dataclass
class Buckets:
    nonverb: set[str] = field(default_factory=set)
    verb_lemmas: set[str] = field(default_factory=set)
    verb_stems: set[str] = field(default_factory=set)
    short_noun_candidates: set[str] = field(default_factory=set)
    function_words: set[str] = field(default_factory=set)
    skipped_inflected: Counter = field(default_factory=Counter)


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetched(source: Source, data_root: Path) -> Path:
    """Pin each download by md5, because both upstream files change without a version number."""
    path = data_root / source.name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(source.url, path)
    if _md5(path) != source.md5:
        raise SystemExit(f"{path} does not match md5 {source.md5}, so the lexicon would not rebuild byte for byte")
    return path


def verb_stem(word: str) -> str | None:
    if word.endswith("en") and len(word) - 2 >= MIN_STEM:
        return word[:-2]
    if word.endswith("n") and len(word) - 1 >= MIN_STEM:
        return word[:-1]
    return None


def is_participle_base(sense: dict) -> bool:
    tags = set(sense.get("tags") or [])
    return "participle" in tags and not tags & INFLECTION_TAGS


def is_inflected_entry(entry: dict) -> bool:
    if "form_of" in entry or "alt_of" in entry:
        return True
    senses = entry.get("senses") or []
    if not senses or not all("form_of" in sense for sense in senses):
        return False
    return not any(is_participle_base(sense) for sense in senses)


def record_short_noun(raw_word: str, pos: str, buckets: Buckets) -> None:
    if pos == "noun" and len(raw_word) == SHORT_NOUN_LETTERS and raw_word[0].isupper():
        buckets.short_noun_candidates.add(raw_word.lower())


def record_function_word(entry: dict, buckets: Buckets) -> None:
    word = entry.get("word", "").lower()
    if entry.get("pos") in FUNCTION_POS and "form_of" not in entry and WORD_RE.match(word):
        buckets.function_words.add(word)


def add_kaikki_entry(entry: dict, buckets: Buckets) -> None:
    if entry.get("lang_code") == "de":
        record_function_word(entry, buckets)
    if entry.get("lang_code") != "de" or entry.get("pos") not in KAIKKI_POS:
        return
    raw_word = entry.get("word", "")
    word = raw_word.lower()
    if not WORD_RE.match(word):
        return
    if is_inflected_entry(entry):
        buckets.skipped_inflected[entry["pos"]] += 1
        return
    record_short_noun(raw_word, entry["pos"], buckets)
    if entry["pos"] != "verb":
        buckets.nonverb.add(word)
        return
    buckets.verb_lemmas.add(word)
    stem = verb_stem(word)
    if stem:
        buckets.verb_stems.add(stem)


def german_kaikki_entries(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as handle:
        yield from (json.loads(line) for line in handle if '"lang_code": "de"' in line)


def is_noun_row(row: dict) -> bool:
    pos = row["pos"]
    word = row["lemma"].strip().lower()
    return "Substantiv" in pos and "Affix" not in pos and "Gebundenes" not in pos and bool(WORD_RE.match(word))


def add_gambolputty_nouns(path: Path, buckets: Buckets) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if is_noun_row(row)]
    for row in rows:
        raw_word = row["lemma"].strip()
        buckets.nonverb.add(raw_word.lower())
        record_short_noun(raw_word, "noun", buckets)


def write_gzip(path: Path, body: bytes) -> None:
    """Zero the gzip timestamp and name, because a rebuild must match the shipped file byte for byte."""
    with path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
        handle.write(body)


def write_words(path: Path, words: set[str]) -> None:
    write_gzip(path, ("\n".join(sorted(words)) + "\n").encode("utf-8"))


def german_verbs_module() -> ModuleType:
    sys.path.insert(0, str(REPOSITORY_ROOT / "hooks"))
    return importlib.import_module("lib.german_verbs")


def write_verbs(buckets: Buckets) -> list[str]:
    """Keep only function words that look finite, because those few are all the runtime must refuse as verbs."""
    stems = frozenset(buckets.verb_stems)
    not_finite = sorted(word for word in buckets.function_words if german_verbs_module().regular_finite(word, stems))
    body = {"not_finite": not_finite, "stems": sorted(stems)}
    write_gzip(VERBS_PATH, json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return not_finite


def main(argv: list[str]) -> None:
    data_root = Path(argv[1]) if len(argv) > 1 else CACHE_ROOT
    buckets = Buckets()
    for entry in german_kaikki_entries(fetched(KAIKKI, data_root)):
        add_kaikki_entry(entry, buckets)
    add_gambolputty_nouns(fetched(NOUNS, data_root), buckets)
    lexicon = buckets.nonverb | buckets.verb_lemmas | buckets.verb_stems
    write_words(LEXICON_PATH, lexicon)
    not_finite = write_verbs(buckets)
    candidates = data_root / "short_noun_candidates.txt"
    candidates.write_text("\n".join(sorted(buckets.short_noun_candidates)) + "\n", encoding="utf-8")
    print("skipped inflected entries by pos", dict(buckets.skipped_inflected))
    print("lexicon entries", len(lexicon), "written to", LEXICON_PATH)
    print("verb stems", len(buckets.verb_stems), "and", len(not_finite), "function-word lookalikes written to", VERBS_PATH)
    print("short noun candidates for hooks/lib/german_short_nouns.json written to", candidates)


if __name__ == "__main__":
    main(sys.argv)
