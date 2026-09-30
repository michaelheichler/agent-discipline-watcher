"""Keep one source because two forks would drift apart."""
from __future__ import annotations

import textwrap

AGENT_NAME = "adw-test-writer"
SKILL_PATH = "skills/unit-testing-principles/SKILL.md"
SKILL_NAME = "unit-testing-principles"

CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_EFFORT = "high"
CODEX_MODEL = "gpt-6-luna"
CODEX_EFFORT = "high"
OMP_TOOLS = ("read", "grep", "glob", "write", "edit", "bash")

DESCRIPTION = (
    "Delegate here whenever a project denies test writes. This is the "
    "only agent trusted to write or edit a test. It reads the "
    "unit-testing-principles skill before every test and reports the "
    "behavior each test protects."
)

READ_FIRST_LINE = (
    f"Read `{SKILL_PATH}` before you write or change a single line of "
    "a test. No task here starts before that reading."
)

MISSION_STEPS = (
    "Read the unit-testing-principles skill before you write or change "
    "any test. Apply its checklist to every test you write.",
    "Write a test only when it protects observable behavior of domain "
    "logic or an algorithm. Skip trivial code and code that only wires "
    "other pieces together.",
    "Do not pin a hard-coded name, a tuned constant, a message string, "
    "or a literal that lives in source or config. Ask this question for "
    "every assertion. Does the test still fail after a change that "
    "keeps every user-visible behavior the same. If the answer is yes, "
    "drop that assertion or do not write the test.",
    "Prefer a test that checks output over a test that checks state, "
    "and prefer a test that checks state over a test built on mocks. "
    "Use a mock only for a real out-of-process dependency you do not "
    "manage.",
    "Cover one behavior per test. Turn near-duplicate cases into "
    "parameters of one test. Never put an assert loop or a branch "
    "inside a test, and never reach into a private field or method to "
    "make an assertion pass.",
    "When you finish, report each test with the behavior it protects "
    "and the regression it would catch. Report every test you chose "
    "not to write, with the reason you skipped it.",
    "Obey every finding the discipline watcher raises. Never silence a "
    "hook, edit its configuration, or add a marker that suppresses a "
    "finding.",
)


def mission_lines() -> tuple[str, ...]:
    """Number each step because an unordered list confuses readers."""
    return tuple(f"{index}. {step}" for index, step in enumerate(MISSION_STEPS, start=1))


def mission_text() -> str:
    """Join steps because a single wall of text is hard to scan."""
    return "\n\n".join(mission_lines())


def mission_section() -> str:
    """Head the section because both bodies read the same list."""
    return "\n".join(("## Mission", "", mission_text(), ""))


def _folded(text: str, width: int = 78, indent: str = "  ") -> str:
    """Wrap prose because a folded block scalar reads clean."""
    return "\n".join(f"{indent}{line}" for line in textwrap.wrap(text, width=width))


def _yaml_header(extra_lines: tuple[str, ...]) -> str:
    """Share these lines because Claude and OMP both read YAML."""
    return "\n".join((
        "---",
        f"name: {AGENT_NAME}",
        "description: >-",
        _folded(DESCRIPTION),
        *extra_lines,
        "---",
    ))


def render_claude_agent() -> str:
    """Fill this frontmatter because Claude reads model here only."""
    header = _yaml_header((f"model: {CLAUDE_MODEL}", f"effort: {CLAUDE_EFFORT}"))
    body = "\n".join(("# ADW Test Writer", "", READ_FIRST_LINE, "", mission_section()))
    return f"{header}\n\n{body}"


def render_codex_role() -> str:
    """Fill these TOML keys because Codex reads model here only."""
    lines = (
        f'name = "{AGENT_NAME}"',
        f'description = "{DESCRIPTION}"',
        'developer_instructions = """',
        READ_FIRST_LINE.replace("`", ""),
        "",
        mission_text(),
        '"""',
        f'model = "{CODEX_MODEL}"',
        f'model_reasoning_effort = "{CODEX_EFFORT}"',
    )
    return "\n".join(lines) + "\n"


def _omp_model_section() -> str:
    """Name /agents because OMP sets the model there, not here."""
    return "\n".join((
        "## Choosing the model",
        "",
        "This file ships with no fixed model. Open the agents hub with "
        "/agents in OMP, select adw-test-writer, then set a model id, "
        "a provider/id pair, or a role alias such as @task.",
        "",
    ))


def render_omp_agent() -> str:
    """Fill this frontmatter because OMP reads tools here only."""
    extra = ("tools:", *(f"  - {tool}" for tool in OMP_TOOLS), "autoloadSkills:", f"  - {SKILL_NAME}")
    header = _yaml_header(extra)
    autoload_line = (
        "This agent autoloads that skill at spawn, so treat it as read "
        "before your own first turn as well."
    )
    body = "\n".join((
        "# ADW Test Writer", "", f"{READ_FIRST_LINE} {autoload_line}", "",
        _omp_model_section(), mission_section(),
    ))
    return f"{header}\n\n{body}"
