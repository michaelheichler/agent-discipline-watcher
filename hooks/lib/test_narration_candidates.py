from lib.narration_candidates import candidates, opens_with_narration

NARRATING = (
    "Degrades to None rather than raising because the embedding layer is optional and the caller keeps its turn.",
    "Blocks the payload, because an interpreter's inline code reaches write APIs the scanner never sees.",
    "Sweeps as it reads, because a crashed session would otherwise pin the model forever.",
)
DECIDING = (
    "Set to 1.5 because Tukey's fence lands at 36.5 words on 5000 tracked sentences.",
    "Kept out of the blocking hook path because a gate that waits on a server stalls every write.",
    "Masked because a heading is a title, and scanning it reported findings against label text.",
    "Resolved, because os.replace on a symlink path destroys the link instead of its target.",
)


def test_a_third_person_opener_is_a_candidate() -> None:
    assert all(opens_with_narration(text) for text in NARRATING)


def test_a_decision_opener_is_not_a_candidate() -> None:
    assert all(not opens_with_narration(text) for text in DECIDING)


def test_a_line_without_a_why_marker_is_left_to_the_blocking_rules() -> None:
    source = "def scan():\n    # Returns the findings for the file.\n    return []\n"

    assert candidates("a.py", source) == ()


def test_a_docstring_and_a_comment_both_reach_the_judge() -> None:
    source = (
        "def scan():\n"
        '    """Returns the rows because the caller needs a stable order for the report."""\n'
        "    # Counts the rows because the report header needs a total before the body renders.\n"
        "    return []\n"
    )

    found = candidates("a.py", source)

    assert [item.line for item in found] == [2, 3]
    assert all(item.path == "a.py" for item in found)


def test_unparseable_source_yields_no_candidate() -> None:
    assert candidates("a.py", "def broken(:\n") == ()


def test_typescript_comments_reach_the_judge_without_scanning_strings() -> None:
    source = (
        'const text = "Returns the cache because callers need stable identity.";\n'
        "// Returns the cache because callers need stable identity.\n"
        "const value = 1;\n"
    )

    found = candidates("a.ts", source)

    assert [(item.line, item.text) for item in found] == [
        (2, "Returns the cache because callers need stable identity."),
    ]
