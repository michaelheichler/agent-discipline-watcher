import time

import pytest

from lib import markup
from lib.scanner import scan_all

PATCH_REGEX_LINE = (
    r'''const EXISTING = /\/\*ccpatch:model-picker-options\*\/var __lfcModelPickerOptions=JSON\.parse\("(?:[^"\\]|\\.)*"\);'''
    r'''__lfcModelPickerOptions\.forEach\(function\(_o\)\{if\(!([\w$]+)\.some\(function\(_i\)\{return _i\.value===_o\.value\}\)\)'''
    r'''\1\.push\(_o\)\}\);/g;'''
)
# Odd, because three quotes per line leave the last quote unpartnered.
PATCH_LINES = 199
SCAN_BOUND_SECONDS = 1.0


def test_a_script_full_of_unpartnered_quotes_before_backslash_runs_scans_quickly() -> None:
    text = "\n".join([PATCH_REGEX_LINE] * PATCH_LINES) + "\n"
    started = time.monotonic()

    scan_all("patch.ts", text, {})

    assert time.monotonic() - started < SCAN_BOUND_SECONDS


@pytest.mark.parametrize(("source", "masked"), [
    pytest.param('x = "ab" + y', "x = " + " " * 4 + " + y", id="plain-double-quotes"),
    pytest.param('x = "a\\"b" + y', "x = " + " " * 6 + " + y", id="escaped-quote-inside"),
    pytest.param('x = "a\\\\" + y', "x = " + " " * 5 + " + y", id="escaped-backslash-before-the-closing-quote"),
    pytest.param("x = 'it' + `t`", "x = " + " " * 4 + " + " + " " * 3, id="single-quotes-and-backticks"),
    pytest.param("x = `a\nb`;", "x = " + " " * 2 + "\n" + " " * 2 + ";", id="template-across-lines-keeps-the-newline"),
    pytest.param("it's x", "it's x", id="unpartnered-quote-stays"),
])
def test_source_masking_blanks_each_string_literal_and_nothing_else(source: str, masked: str) -> None:
    assert markup.mask_source_strings(source) == masked
