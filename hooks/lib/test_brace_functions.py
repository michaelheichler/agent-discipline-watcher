from lib.brace_functions import long_brace_functions
from lib.scanner import scan_all


def _function(name: str, body_lines: int) -> str:
    body = "".join(f"  const v{n} = {n};\n" for n in range(body_lines))
    return f"function {name}(a: number): number {{\n{body}  return a;\n}}\n"


def test_a_262_line_typescript_function_blocks_at_the_default_cap() -> None:
    source = _function("huge", 259)
    rows = [row for row in scan_all("src/huge.ts", source, {}) if row["rule"] == "function_too_long"]
    assert [(row["line"], row["snippet"]) for row in rows] == [(1, "huge")]


def test_a_short_javascript_function_passes() -> None:
    rules = {row["rule"] for row in scan_all("src/ok.js", _function("ok", 10), {})}
    assert "function_too_long" not in rules


def test_the_configured_cap_applies() -> None:
    rows = scan_all("src/a.ts", _function("mid", 20), {"function_block_lines": 10})
    assert "function_too_long" in {row["rule"] for row in rows}


def test_arrow_functions_and_methods_are_measured() -> None:
    body = "".join(f"    x{n}();\n" for n in range(6))
    source = (
        f"const run = async (a) => {{\n{body}}};\n"
        f"class Box {{\n  open(a: string): void {{\n{body}  }}\n}}\n"
    )
    assert long_brace_functions(source, 5) == [(1, "run", 8), (10, "open", 8)]


def test_control_blocks_and_braces_in_strings_or_comments_do_not_count() -> None:
    source = (
        "function f() {\n"
        "  const s = \"}}}{{{\";\n"
        "  // } closing brace in a comment\n"
        "  if (s) {\n    g();\n  }\n"
        "  return `${s}}`;\n"
        "}\n"
    )
    assert long_brace_functions(source, 100) == []
    assert long_brace_functions(source, 3) == [(1, "f", 8)]
