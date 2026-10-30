"""Judged by content, because an executable named claude or 2.1.312 carries no binary suffix."""
from __future__ import annotations

import codecs
from pathlib import PurePath

try:
    from .brace_functions import BRACE_LANGUAGE_EXTS
    from .markup import (
        COMMENTABLE_EXTS, CONFIG_EXTS, DATA_TEXT_EXTS, LOG_EXTS, MIXED_LANGUAGE_EXTS, PLAIN_TEXT_EXTS, PROSE_EXTS, SCRIPT_EXTS,
    )
    from .test_units import LANGUAGES
except ImportError:
    from brace_functions import BRACE_LANGUAGE_EXTS
    from markup import (
        COMMENTABLE_EXTS, CONFIG_EXTS, DATA_TEXT_EXTS, LOG_EXTS, MIXED_LANGUAGE_EXTS, PLAIN_TEXT_EXTS, PROSE_EXTS, SCRIPT_EXTS,
    )
    from test_units import LANGUAGES

CONTENT_SAMPLE_BYTES = 8192
TEXT_SUFFIXES = (
    PROSE_EXTS | CONFIG_EXTS | COMMENTABLE_EXTS | SCRIPT_EXTS | MIXED_LANGUAGE_EXTS | PLAIN_TEXT_EXTS
    | LOG_EXTS | DATA_TEXT_EXTS | BRACE_LANGUAGE_EXTS | frozenset(LANGUAGES)
)
TEXT_BOMS = (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")
TEXT_CONTROLS = frozenset("\t\n\r\f\v\b\x1b")
SHEBANG = b"#!"
# Because perlfunc -X calls a block binary past a third strange characters.
STRANGE_SHARE = 1 / 3
ESCAPED_BYTES = range(0xDC80, 0xDD00)
# Because no source file starts with these bytes, a match proves the format.
EXECUTABLE_SIGNATURES = (
    b"\x7fELF",
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf",
)
SIGNATURES = EXECUTABLE_SIGNATURES + (
    b"\0asm", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08",
    b"\x1f\x8b", b"\xfd7zXZ\0", b"\x28\xb5\x2f\xfd", b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07",
    b"SQLite format 3\0", b"\x93NUMPY", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"\x1aE\xdf\xa3",
    b"II*\0", b"MM\0*", b"\0\0\1\0", b"\x04\x22\x4d\x18",
)
# Because a format name such as PNG survives a lossy decode, it still proves.
DECODED_SIGNATURES = tuple(
    decoded for decoded in {signature.decode("utf-8", "replace").encode("utf-8") for signature in SIGNATURES}
    if decoded not in SIGNATURES and sum(chr(byte).isalpha() for byte in decoded if byte < 0x80) >= 2
)
CHUNK_TAGS = (b"RIFF", b"RIFX", b"FORM")
BOX_TAG = b"ftyp"
LEAD_WORD = slice(0, 4)
SECOND_WORD = slice(4, 8)
PE_POINTER_OFFSET = 0x3C
PE_MARK = b"PE\0\0"
# Printable, so each counts only beside the suffix of its own format.
TEXTUAL_HEADERS = {
    ".pdf": (b"%PDF-",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".woff": (b"wOFF",),
    ".woff2": (b"wOF2",),
    ".otf": (b"OTTO",),
    ".psd": (b"8BPS",),
    ".flac": (b"fLaC",),
    ".ogg": (b"OggS",),
    ".opus": (b"OggS",),
}


def _encoded(content: bytes | str) -> bytes:
    """Surrogates kept as bytes, because a decoded binary must still fail the text check."""
    return content if isinstance(content, bytes) else content.encode("utf-8", "surrogatepass")


def _sample(content: bytes | str) -> bytes:
    return _encoded(content[:CONTENT_SAMPLE_BYTES])


def strange_share(data: bytes) -> float:
    """Undecodable bytes and stray controls count, because Latin-1 prose holds few of either."""
    text = data.decode("utf-8", "surrogateescape")
    strange = sum(1 for char in text if (ord(char) < 0x20 and char not in TEXT_CONTROLS) or ord(char) in ESCAPED_BYTES)
    return strange / len(text) if text else 0.0


def _portable_executable(sample: bytes) -> bool:
    """MZ alone is printable, so the PE mark at the header pointer must confirm it."""
    pointer = int.from_bytes(sample[PE_POINTER_OFFSET:PE_POINTER_OFFSET + 4], "little")
    return sample.startswith(b"MZ") and sample[pointer:pointer + len(PE_MARK)] == PE_MARK


def _sized_container(sample: bytes) -> bool:
    """Tags are printable, so only a binary size field beside the tag proves the format."""
    if sample.startswith(CHUNK_TAGS):
        return not _clean_text(sample[SECOND_WORD])
    return sample[SECOND_WORD] == BOX_TAG and not _clean_text(sample[LEAD_WORD])


def _executable(sample: bytes) -> bool:
    """Executables only, because a file without a suffix that is binary is in practice a program."""
    return sample.startswith(EXECUTABLE_SIGNATURES) or _portable_executable(sample)


def _signed(sample: bytes) -> bool:
    return sample.startswith(SIGNATURES + DECODED_SIGNATURES) or _portable_executable(sample) or _sized_container(sample)


def _clean_text(sample: bytes) -> bool:
    """Lenient at the end, because the sample may cut a multibyte character in half."""
    try:
        text = codecs.getincrementaldecoder("utf-8")().decode(sample)
    except UnicodeDecodeError:
        return False
    return not any(ord(char) < 0x20 and char not in TEXT_CONTROLS for char in text)


def is_binary_content(path: str | PurePath, content: bytes | str) -> bool:
    """Never for text suffixes, because padding can forge any share a source file is judged by."""
    sample = _sample(content)
    if sample.startswith(TEXT_BOMS):
        return False
    suffix = PurePath(str(path)).suffix.lower()
    if sample.startswith(TEXTUAL_HEADERS.get(suffix, ())):
        return True
    if sample.startswith(SHEBANG) or (suffix and suffix in TEXT_SUFFIXES):
        return False
    dense = strange_share(_encoded(content)) > STRANGE_SHARE
    return _signed(sample) or dense if suffix else _executable(sample) and dense
