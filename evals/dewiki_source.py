#!/usr/bin/env python3
import bz2
import html
import re
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator, NamedTuple

DUMP_URL = "https://archive.org/download/dewiki-20180920/dewiki-20180920-pages-articles.xml.bz2"
CACHE_ROOT = Path.home() / ".adw" / "cache" / "dewiki"
DUMP_PATH = CACHE_ROOT / "dewiki-20180920-pages-articles.xml.bz2"
DOWNLOAD_CHUNK_BYTES = 1 << 20
REQUEST_TIMEOUT = 120
MEDIAWIKI_NAMESPACE = "{http://www.mediawiki.org/xml/export-0.10/}"
PAGE_TAG = f"{MEDIAWIKI_NAMESPACE}page"
NS_TAG = f"{MEDIAWIKI_NAMESPACE}ns"
TITLE_TAG = f"{MEDIAWIKI_NAMESPACE}title"
ID_TAG = f"{MEDIAWIKI_NAMESPACE}id"
REDIRECT_TAG = f"{MEDIAWIKI_NAMESPACE}redirect"
TEXT_PATH = f"{MEDIAWIKI_NAMESPACE}revision/{MEDIAWIKI_NAMESPACE}text"
ARTICLE_NAMESPACE = "0"

TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
TABLE_RE = re.compile(r"\{\|.*?\n\|\}", re.DOTALL)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
REF_RE = re.compile(r"<ref[^>]*?/>|<ref[^>]*?>.*?</ref>", re.DOTALL | re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
FILE_LINK_RE = re.compile(r"\[\[(Datei|File|Bild|Kategorie|Category):[^\]]*\]\]", re.IGNORECASE)
PIPED_LINK_RE = re.compile(r"\[\[[^\]|]*\|([^\]]*)\]\]")
PLAIN_LINK_RE = re.compile(r"\[\[([^\]]*)\]\]")
EXTERNAL_LINK_TEXT_RE = re.compile(r"\[https?://\S+?\s+([^\]]*)\]")
BARE_EXTERNAL_RE = re.compile(r"\[https?://[^\]]*\]")
HEADING_RE = re.compile(r"^\s*=+\s*.*?\s*=+\s*$", re.MULTILINE)
BOLD_ITALIC_RE = re.compile(r"'{2,5}")
LIST_LINE_RE = re.compile(r"^[*#:;].*$", re.MULTILINE)
BLANK_RUN_RE = re.compile(r"\n{3,}")


class Article(NamedTuple):
    page_id: int
    title: str
    wikitext: str


class _SkipPage(Exception):
    pass


def _download(destination: Path, url: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    resume_at = partial.stat().st_size if partial.is_file() else 0
    request = urllib.request.Request(url)
    if resume_at:
        request.add_header("Range", f"bytes={resume_at}-")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        with partial.open("ab") as handle:
            shutil.copyfileobj(response, handle, length=DOWNLOAD_CHUNK_BYTES)
    partial.rename(destination)


def ensure_dump() -> Path:
    if not DUMP_PATH.is_file():
        _download(DUMP_PATH, DUMP_URL)
    return DUMP_PATH


def _article_from(element: ET.Element) -> Article:
    if element.findtext(NS_TAG) != ARTICLE_NAMESPACE or element.find(REDIRECT_TAG) is not None:
        raise _SkipPage()
    title = element.findtext(TITLE_TAG)
    page_id = element.findtext(ID_TAG)
    wikitext = element.findtext(TEXT_PATH)
    if not title or page_id is None or not wikitext:
        raise _SkipPage()
    return Article(int(page_id), title, wikitext)


def _article_or_none(element: ET.Element) -> Article | None:
    try:
        return _article_from(element)
    except _SkipPage:
        return None


def _page_elements(context: ET.XMLPullParser) -> Iterator[ET.Element]:
    for event, element in context:
        if event == "end" and element.tag == PAGE_TAG:
            yield element


def _articles_from(context: ET.XMLPullParser, root: ET.Element) -> Iterator[Article]:
    for element in _page_elements(context):
        article = _article_or_none(element)
        root.clear()
        if article is not None:
            yield article


def iter_articles(dump_path: Path) -> Iterator[Article]:
    with bz2.BZ2File(dump_path, "rb") as handle:
        context = ET.iterparse(handle, events=("start", "end"))
        try:
            _, root = next(context)
        except StopIteration:
            return
        yield from _articles_from(context, root)


def _collapse_templates(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = TEMPLATE_RE.sub("", text)
    return text


def clean_wikitext(wikitext: str) -> str:
    text = html.unescape(wikitext)
    text = COMMENT_RE.sub("", text)
    text = REF_RE.sub("", text)
    text = TABLE_RE.sub("", text)
    text = _collapse_templates(text)
    text = FILE_LINK_RE.sub("", text)
    text = PIPED_LINK_RE.sub(r"\1", text)
    text = PLAIN_LINK_RE.sub(r"\1", text)
    text = EXTERNAL_LINK_TEXT_RE.sub(r"\1", text)
    text = BARE_EXTERNAL_RE.sub("", text)
    text = HEADING_RE.sub("", text)
    text = LIST_LINE_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    text = BOLD_ITALIC_RE.sub("", text)
    return BLANK_RUN_RE.sub("\n\n", text)
