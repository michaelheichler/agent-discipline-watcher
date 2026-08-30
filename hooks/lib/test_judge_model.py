from __future__ import annotations

from lib import judge_model


def test_only_haiku_names_pass_the_screen() -> None:
    """Name every accepted family because a drift here lets a stronger agent run."""
    assert judge_model.is_haiku("claude-haiku-4-5")
    assert judge_model.is_haiku("claude-3-5-haiku-20241022")
    assert judge_model.is_haiku("  CLAUDE-HAIKU-4-5  ")

    assert not judge_model.is_haiku("claude-sonnet-5")
    assert not judge_model.is_haiku("claude-opus-4-1")
    assert not judge_model.is_haiku("gpt-5.6")
    assert not judge_model.is_haiku("haiku")
    assert not judge_model.is_haiku("")
    assert not judge_model.is_haiku(None)
    assert not judge_model.is_haiku(4)


def test_a_stronger_selection_falls_back_to_the_default() -> None:
    """Downgrade rather than raise because a blocked judge would clear findings."""
    assert judge_model.judge_model("claude-3-5-haiku-20241022") == "claude-3-5-haiku-20241022"
    assert judge_model.judge_model("claude-sonnet-5") == judge_model.DEFAULT_JUDGE_MODEL
    assert judge_model.judge_model("claude-opus-4-1") == judge_model.DEFAULT_JUDGE_MODEL
    assert judge_model.judge_model("") == judge_model.DEFAULT_JUDGE_MODEL
    assert judge_model.judge_model(None) == judge_model.DEFAULT_JUDGE_MODEL
    assert judge_model.judge_model() == judge_model.DEFAULT_JUDGE_MODEL


def test_the_default_is_a_haiku_model() -> None:
    """Pin the default because every call site falls back to it."""
    assert judge_model.DEFAULT_JUDGE_MODEL == "claude-haiku-4-5"
    assert judge_model.is_haiku(judge_model.DEFAULT_JUDGE_MODEL)
