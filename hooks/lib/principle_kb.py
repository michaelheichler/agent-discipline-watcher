"""No source text tracked, because no repo ships a license."""
from __future__ import annotations

import io
import os
import re
import sqlite3
import ssl
import sys
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

try:
    from . import session_state
except ImportError:
    import session_state


DEVIQ_REPO = "NimblePros/deviq-hugo"
DEVIQ_COMMIT = "2c5341047e6cf62bc0598dd3cdc2f55951cd125a"
DEVIQ_SECTIONS = frozenset({
    "antipatterns", "code-smells", "principles", "practices", "laws", "testing", "terms",
})
PRINCIPLES_REPO = "webpro/programming-principles"
PRINCIPLES_COMMIT = "a0c299c981cc31f4d4bd5c265cba80d3e9471429"
BUILD_FORMAT = "2"

CODELOAD_HOST = "codeload.github.com"
RAW_HOST = "raw.githubusercontent.com"
DB_NAME = "principles.sqlite"
OFFLINE_ENV = "ADW_OFFLINE"
MAX_WORDS = 80
HTTP_TIMEOUT = 20.0
MAX_DEVIQ_ARCHIVE_BYTES = 100 << 20
MAX_PRINCIPLES_BYTES = 2 << 20
MAX_MEMBER_BYTES = 4 << 20

CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
SHORTCODE_RE = re.compile(r"\{\{[%<].*?[%>]\}\}", re.DOTALL)
REF_DEFINITION_RE = re.compile(r"(?m)^\[[^\]]+\]:.*$")
REF_CONTINUATION_RE = re.compile(r"(?m)^\s+https?://\S+\s*$")
HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s.*$")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
INLINE_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
REF_LINK_RE = re.compile(r"\[([^\]]*)\]\[[^\]]*\]")
BOLD_ITALIC_RE = re.compile(r"(\*\*|__)([^*_]+)\1|(\*|_)([^*_]+)\3")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
BARE_URL_RE = re.compile(r"https?://\S+")
BULLET_LINE_RE = re.compile(r"^\s{0,3}(?:[-*+]\s|\d+\.\s)")
FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
FRONT_MATTER_TITLE_RE = re.compile(r"(?m)^title:\s*(.+?)\s*$")
HEADING2_RE = re.compile(r"(?m)^## (.+?)\s*$")

Fetch = Callable[[str, int], bytes]


@dataclass(frozen=True, slots=True)
class Row:
    source: str
    entry_id: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class BuildResult:
    skipped: bool
    reason: str
    deviq_count: int
    principles_count: int


class _RedirectHandler(urllib.request.HTTPRedirectHandler):
    """Checked redirects, because the CDN sometimes bounces once."""

    def redirect_request(self, *args: object) -> urllib.request.Request | None:
        _validate_url(args[-1])
        return super().redirect_request(*args)


def _validate_url(url: str) -> None:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or hostname not in {CODELOAD_HOST, RAW_HOST}:
        raise ValueError("principle source URL is outside the HTTPS allowlist")
    if parsed.port not in (None, 443):
        raise ValueError("principle source URL uses an unexpected port")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("principle source URL carries credentials")


def _get_bytes(url: str, limit: int) -> bytes:
    """Two hosts only, because a redirect could go anywhere."""
    _validate_url(url)
    request = urllib.request.Request(
        url, headers={"User-Agent": "agent-discipline-watcher-principle-kb/1"},
    )
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=context),
        _RedirectHandler(),
    )
    with opener.open(request, timeout=HTTP_TIMEOUT) as response:
        status = getattr(response, "status", None) or response.getcode()
        if not 200 <= status < 300:
            raise ValueError(f"principle source request returned HTTP {status}")
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("principle source response exceeds the size limit")
        return body


def _is_bullet_paragraph(paragraph: str) -> bool:
    lines = [line for line in paragraph.splitlines() if line.strip()]
    return bool(lines) and all(BULLET_LINE_RE.match(line) for line in lines)


def _is_label_paragraph(paragraph: str) -> bool:
    lines = [line for line in paragraph.splitlines() if line.strip()]
    if len(lines) != 1:
        return False
    line = lines[0].strip()
    return len(line.split()) <= 2 and line[-1:] not in ".!?"


def _strip_inline_markup(paragraph: str) -> str:
    text = IMAGE_RE.sub(r"\1", paragraph)
    text = INLINE_LINK_RE.sub(r"\1", text)
    text = REF_LINK_RE.sub(r"\1", text)
    text = BOLD_ITALIC_RE.sub(lambda match: match.group(2) or match.group(4), text)
    text = INLINE_CODE_RE.sub(r"\1", text)
    text = BARE_URL_RE.sub("", text)
    return " ".join(text.split())


def _kept_paragraph(paragraph: str) -> bool:
    if not paragraph.strip():
        return False
    if _is_bullet_paragraph(paragraph) or _is_label_paragraph(paragraph):
        return False
    return not paragraph.strip().lower().startswith("see also")


def _plain_text(body: str) -> str:
    """Prose only, because headings and lists carry no explanation."""
    cleaned = CODE_FENCE_RE.sub(" ", body)
    cleaned = SHORTCODE_RE.sub(" ", cleaned)
    cleaned = REF_DEFINITION_RE.sub("", cleaned)
    cleaned = REF_CONTINUATION_RE.sub("", cleaned)
    cleaned = HEADING_RE.sub("", cleaned)
    words: list[str] = []
    for paragraph in re.split(r"\n\s*\n", cleaned):
        if not _kept_paragraph(paragraph):
            continue
        words.extend(_strip_inline_markup(paragraph).split())
        if len(words) >= MAX_WORDS:
            break
    return " ".join(words[:MAX_WORDS])


def _slugify(title: str) -> str:
    """GitHub slug rule, because ids must equal the README anchors."""
    lowered = title.lower()
    kept = re.sub(r"[^a-z0-9 -]", "", lowered)
    return re.sub(r"\s+", "-", kept.strip())


def _front_matter(raw: str) -> tuple[str, str]:
    """Normalize first, because DevIQ pages mix CRLF and bare CR."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    match = FRONT_MATTER_RE.match(text)
    if match is None:
        return "", text
    title_match = FRONT_MATTER_TITLE_RE.search(match.group(1))
    title = title_match.group(1).strip().strip('"') if title_match else ""
    return title, text[match.end():]


def _deviq_member_entry(name: str) -> tuple[str, str] | None:
    parts = name.split("/")
    if len(parts) != 4 or parts[1] != "content" or parts[2] not in DEVIQ_SECTIONS:
        return None
    if not parts[3].endswith(".md") or parts[3] == "_index.md":
        return None
    return parts[2], parts[3][:-3]


def _deviq_row(bundle: tarfile.TarFile, member: tarfile.TarInfo) -> Row | None:
    if not member.isfile():
        return None
    entry = _deviq_member_entry(member.name)
    if entry is None:
        return None
    if member.size > MAX_MEMBER_BYTES:
        raise ValueError(f"DevIQ entry exceeds the size limit: {member.name}")
    stream = bundle.extractfile(member)
    if stream is None:
        return None
    with stream:
        data = stream.read(MAX_MEMBER_BYTES + 1)
    title, body = _front_matter(data.decode("utf-8", errors="replace"))
    section, stem = entry
    return Row("deviq", f"{section}/{stem}", title or stem, _plain_text(body))


def _fetch_deviq(fetch: Fetch) -> list[Row]:
    url = f"https://{CODELOAD_HOST}/{DEVIQ_REPO}/tar.gz/{DEVIQ_COMMIT}"
    archive = fetch(url, MAX_DEVIQ_ARCHIVE_BYTES)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        candidates = (_deviq_row(bundle, member) for member in bundle)
        return [row for row in candidates if row is not None]


def _principle_row(text: str, match: re.Match, end: int) -> Row | None:
    title = match.group(1).strip()
    if title.lower() == "contents":
        return None
    section = text[match.end():end]
    return Row("programming-principles", _slugify(title), title, _plain_text(section))


def _fetch_principles(fetch: Fetch) -> list[Row]:
    url = f"https://{RAW_HOST}/{PRINCIPLES_REPO}/{PRINCIPLES_COMMIT}/README.md"
    data = fetch(url, MAX_PRINCIPLES_BYTES)
    text = data.decode("utf-8", errors="replace")
    matches = list(HEADING2_RE.finditer(text))
    rows: list[Row] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        row = _principle_row(text, match, end)
        if row is None:
            continue
        rows.append(row)
    return rows


def _cache_path(root: Path | None) -> Path:
    cache_root = Path(root) if root is not None else session_state.plugin_data_home() / "cache"
    return cache_root / DB_NAME


def _stored_meta(db_path: Path) -> dict[str, str] | None:
    if not db_path.is_file():
        return None
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return dict(connection.execute("SELECT key, value FROM meta").fetchall())
        finally:
            connection.close()
    except sqlite3.Error:
        return None


def _stored_counts(db_path: Path) -> tuple[int, int]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        deviq = connection.execute(
            "SELECT COUNT(*) FROM principle WHERE source = ?", ("deviq",),
        ).fetchone()[0]
        principles = connection.execute(
            "SELECT COUNT(*) FROM principle WHERE source = ?", ("programming-principles",),
        ).fetchone()[0]
        return deviq, principles
    finally:
        connection.close()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute(
        "CREATE TABLE principle ("
        "source TEXT NOT NULL, entry_id TEXT NOT NULL, title TEXT NOT NULL, "
        "text TEXT NOT NULL, PRIMARY KEY (source, entry_id))"
    )
    connection.execute("CREATE UNIQUE INDEX principle_entry_id ON principle(entry_id)")


def _pinned_meta() -> dict[str, str]:
    """Format joins the shas, because a parser fix changes rows."""
    return {"deviq_commit": DEVIQ_COMMIT, "principles_commit": PRINCIPLES_COMMIT, "format": BUILD_FORMAT}


def _insert_rows(connection: sqlite3.Connection, rows: list[Row]) -> None:
    connection.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", sorted(_pinned_meta().items()))
    ordered = sorted(rows, key=lambda row: (row.source, row.entry_id))
    connection.executemany(
        "INSERT INTO principle (source, entry_id, title, text) VALUES (?, ?, ?, ?)",
        [(row.source, row.entry_id, row.title, row.text) for row in ordered],
    )


def _write_database(db_path: Path, rows: list[Row]) -> None:
    """One fresh file, because a diff cannot trust stale rows."""
    descriptor, tmp_name = tempfile.mkstemp(
        prefix=".principles-", suffix=".sqlite", dir=str(db_path.parent),
    )
    os.close(descriptor)
    tmp_path = Path(tmp_name)
    tmp_path.unlink()
    try:
        connection = sqlite3.connect(str(tmp_path))
        try:
            _create_schema(connection)
            _insert_rows(connection, rows)
            connection.commit()
        finally:
            connection.close()
        os.replace(tmp_path, db_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _skip_result(db_path: Path, reason: str) -> BuildResult:
    if db_path.is_file():
        deviq_count, principles_count = _stored_counts(db_path)
        return BuildResult(True, reason, deviq_count, principles_count)
    return BuildResult(True, reason, 0, 0)


def build(*, root: Path | None = None, fetch: Fetch = _get_bytes) -> BuildResult:
    """Stored shas gate rebuilds, because equal commits match."""
    db_path = _cache_path(root)
    if os.environ.get(OFFLINE_ENV) == "1":
        return _skip_result(db_path, f"{OFFLINE_ENV}=1")
    if _stored_meta(db_path) == _pinned_meta():
        return _skip_result(db_path, "pinned commits already built")
    try:
        deviq_rows = _fetch_deviq(fetch)
        principle_rows = _fetch_principles(fetch)
    except Exception as error:
        return _skip_result(db_path, f"fetch failed: {error}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _write_database(db_path, deviq_rows + principle_rows)
    return BuildResult(False, "", len(deviq_rows), len(principle_rows))


def lookup(entry_id: str, *, root: Path | None = None) -> str | None:
    """Read-only and silent, because a hook must not crash here."""
    try:
        db_path = _cache_path(root)
        if not db_path.is_file():
            return None
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
        try:
            row = connection.execute(
                "SELECT text FROM principle WHERE entry_id = ?", (entry_id,),
            ).fetchone()
        finally:
            connection.close()
        return row[0] if row else None
    except Exception:
        return None


def entry(entry_id: str, *, root: Path | None = None) -> Row | None:
    """Return source and title too, because a label names them."""
    try:
        db_path = _cache_path(root)
        if not db_path.is_file():
            return None
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
        try:
            found = connection.execute(
                "SELECT source, entry_id, title, text FROM principle WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
        finally:
            connection.close()
        return Row(*found) if found else None
    except Exception:
        return None


def main(argv: list[str] | None = None, *, fetch: Fetch = _get_bytes) -> int:
    """Only the build path, because a hook must not trigger fetch."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != ["build"]:
        print("usage: principle_kb.py build", file=sys.stderr)
        return 2
    result = build(fetch=fetch)
    state = "unchanged" if result.skipped else "built"
    reason = f" ({result.reason})" if result.skipped and result.reason else ""
    print(
        f"principle KB {state}{reason}: deviq {result.deviq_count} rows, "
        f"programming-principles {result.principles_count} rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
