"""Path and bytes in, verdict out, because the skip must follow content and not a suffix list."""
from __future__ import annotations

import pytest

from lib import binary_content

DENSE = bytes(range(256)) * 32
PROSE = b"Some prose here.\n"
ELF = b"\x7fELF\x02\x01\x01\0"
MACHO = b"\xcf\xfa\xed\xfe\x0c\x00\x00\x01"
FAT_MACHO = b"\xca\xfe\xba\xbe"
PE_POINTER = 0x80
PORTABLE = b"MZ" + bytes(0x3A) + PE_POINTER.to_bytes(4, "little") + bytes(PE_POINTER - 0x40) + b"PE\0\0"


@pytest.mark.parametrize(("path", "content"), [
    pytest.param("claude", MACHO + DENSE, id="extensionless-macho"),
    pytest.param("codex", FAT_MACHO + DENSE, id="extensionless-fat-macho"),
    pytest.param("bun", ELF + DENSE, id="extensionless-elf"),
    pytest.param("tool", PORTABLE + DENSE, id="extensionless-pe"),
    pytest.param("2.1.312", MACHO + b"\n" * 3000, id="version-suffix-macho"),
    pytest.param("tool.exe", PORTABLE + b"\n" * 3000, id="pe-under-another-suffix"),
    pytest.param("document.pdf", b"%PDF-1.7\n", id="printable-header-beside-its-suffix"),
    pytest.param("blob.data", DENSE, id="dense-bytes-under-another-suffix"),
    pytest.param("data.bin", DENSE + b"\n" * 3000, id="dense-bytes-padded-with-newlines"),
])
def test_binary_content_is_recognized(path: str, content: bytes) -> None:
    assert binary_content.is_binary_content(path, content)


@pytest.mark.parametrize(("path", "content"), [
    pytest.param("data.bin", b"\xef\xbb\xbf" + DENSE, id="byte-order-mark"),
    pytest.param("image.png", b"%PDF-1.7\n", id="printable-header-beside-another-suffix"),
    pytest.param("notes.md", ELF + DENSE, id="signature-and-dense-bytes-under-a-text-suffix"),
    pytest.param("module.py", b"\0value = 1\n", id="nul-byte-under-a-source-suffix"),
    pytest.param("run", b"#!/bin/sh\n" + DENSE, id="shebang-script"),
    pytest.param("claude", MACHO + b"\n" * 3000, id="extensionless-signature-without-dense-bytes"),
    pytest.param("README", b"PK\x03\x04" + b"\x01" * 600 + PROSE * 20, id="extensionless-archive-signature"),
    pytest.param("blob", DENSE, id="extensionless-dense-bytes-without-signature"),
    pytest.param("tool", b"MZ" + DENSE, id="extensionless-mz-without-pe-mark"),
    pytest.param("tool.exe", b"MZ just text\n", id="mz-text-without-pe-mark"),
    pytest.param("notes.data", "Caf\xe9 na\xefve r\xe9sum\xe9 prose text\n".encode("latin-1"), id="latin-1-prose"),
    pytest.param("data.bin", PROSE * 600 + DENSE, id="dense-tail-after-longer-prose"),
    pytest.param("data.bin", DENSE + PROSE * 1500, id="dense-head-before-longer-prose"),
])
def test_text_content_is_not_recognized_as_binary(path: str, content: bytes) -> None:
    assert not binary_content.is_binary_content(path, content)
