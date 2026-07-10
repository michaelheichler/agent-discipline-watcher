from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "pi" / "extensions" / "agent-discipline-watcher" / "index.ts"
README = ROOT / "README.md"
SKILL = ROOT / "SKILL.md"


def read(path: Path) -> str:
    return path.read_text()


def owned_policy_text(path: Path, text: str) -> str:
    if path.suffix != ".md":
        return text

    kept = []
    in_fence = False
    for line in _without_frontmatter(text.splitlines()):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if is_markdown_table_separator(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _without_frontmatter(lines: list[str]) -> list[str]:
    if not lines or lines[0].strip() != "---":
        return lines
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[index + 1:]
    return lines


def is_markdown_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) < 2:
        return False
    return all(cell and set(cell) <= {"-", ":"} and "-" in cell for cell in cells)


def test_owned_policy_text_excludes_markdown_code_and_table_separators():
    text = "\n".join(
        [
            "Prose stays checked.",
            "",
            "```bash",
            "agent-discipline configure --checks punctuation,english",
            "```",
            "",
            "| Check | Purpose |",
            "| --- | --- |",
        ]
    )
    assert ("-" + "-") not in owned_policy_text(README, text)


def test_owned_policy_text_keeps_prose_double_hyphen_strict():
    text = "Normal prose with left" + "--" + "right remains checked."
    assert ("-" + "-") in owned_policy_text(README, text)


def test_owned_policy_text_excludes_yaml_frontmatter():
    text = "\n".join(
        [
            "---",
            "name: agent-discipline-watcher",
            "description: >-",
            "  Use when an agent writes files.",
            "---",
            "Prose stays checked.",
        ]
    )
    assert ("-" + "-") not in owned_policy_text(SKILL, text)


def test_pi_extension_registers_one_combined_lifecycle():
    source = read(EXTENSION)
    assert source.count('pi.on("session_start"') == 1
    assert source.count('pi.on("before_agent_start"') == 1
    assert source.count('pi.on("tool_result"') == 1
    assert source.count('pi.on("agent_end"') == 1
    assert "const ledger = new Map<string, Finding[]>()" in source
    assert "const POLICY =" in source


def test_pi_extension_shells_to_combined_python_scanner():
    source = read(EXTENSION)
    assert 'run("python3", ["-c", PY_SCAN, file, ROOT]' in source
    assert "scan_all(target, text, config)" in source
    assert '"punctuation": True' in source
    assert '"english": True' in source
    assert '"clean_code": True' in source


def test_pi_extension_scans_write_results_and_sends_one_steer():
    source = read(EXTENSION)
    assert 'tool === "write" || tool === "edit" || tool === "multiedit"' in source
    assert "compactReport(rows)" in source
    assert 'deliverAs: "steer"' in source
    assert source.count("compactReport(rows)") == 1
    assert "Full report:" in source


def test_owned_text_has_no_legacy_extension_or_banned_markers():
    text = "\n".join(owned_policy_text(path, read(path)) for path in (EXTENSION, README, SKILL))
    assert "punctuation-discipline/pi" not in text
    assert "english-for-agents/pi" not in text
    assert "clean-coder-discipline/pi" not in text
    assert "\u2013" not in text
    assert "\u2014" not in text
    assert ("-" + "-") not in text
    assert ("TO" + "DO") not in text
    assert ("FIX" + "ME") not in text


def test_docs_state_replacement_and_pi_scope():
    text = f"{read(README)}\n{read(SKILL)}"
    assert "professional-agent-helper" in text
    assert "one Pi extension" in text
    assert "one ledger" in text


if __name__ == "__main__":
    test_owned_policy_text_excludes_markdown_code_and_table_separators()
    test_owned_policy_text_keeps_prose_double_hyphen_strict()
    test_owned_policy_text_excludes_yaml_frontmatter()
    test_pi_extension_registers_one_combined_lifecycle()
    test_pi_extension_shells_to_combined_python_scanner()
    test_pi_extension_scans_write_results_and_sends_one_steer()
    test_owned_text_has_no_legacy_extension_or_banned_markers()
    test_docs_state_replacement_and_pi_scope()
