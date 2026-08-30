from __future__ import annotations

import io

import pytest

import host_picker
from lib import host, host_manifest, picker_state
from lib.picker_state import Action, Picker


def _picker() -> Picker:
    return Picker(picker_state.rows_for(host_manifest.load_all()))


def _index_of(picker: Picker, name: str) -> int:
    return next(index for index, row in enumerate(picker.rows) if row.manifest.name == name)


def test_arrow_keys_move_the_cursor_without_selecting() -> None:
    """Separate movement from selection because a reader browsing must not install by scrolling."""
    moved = _picker().apply(picker_state.decode("\x1b[B"))

    assert moved.cursor == 1
    assert moved.chosen() == ()


def test_the_cursor_stops_at_both_ends() -> None:
    """Refuse to wrap because a cursor that jumps to the far end hides which row the reader left."""
    picker = _picker()

    assert picker.move(-1).cursor == 0
    assert picker.move(len(picker.rows) + 5).cursor == len(picker.rows) - 1


def test_space_toggles_the_row_under_the_cursor() -> None:
    """Toggle rather than set because a reader who picks wrongly must be able to unpick."""
    picker = _picker().move(_index_of(_picker(), host.CODEX))

    selected = picker.apply(picker_state.decode(" "))
    cleared = selected.apply(picker_state.decode(" "))

    assert selected.chosen() == (host.CODEX,)
    assert cleared.chosen() == ()


def test_a_host_without_an_installer_cannot_be_selected() -> None:
    """Refuse the toggle because this script does not perform a plugin install or an account sync."""
    picker = _picker()
    cowork_row = _index_of(picker, host.COWORK)

    assert picker.toggle(cowork_row).chosen() == ()


def test_an_unselectable_row_still_renders_with_its_reason() -> None:
    """Show every host because a reader deciding needs to see the ones they cannot pick and why."""
    frame = picker_state.render(_picker())

    assert "Claude Cowork" in frame
    assert "[-]" in frame
    assert host_manifest.load(host.COWORK).installer_note in frame


def test_a_mouse_release_on_a_row_toggles_it() -> None:
    """Act on release because a press followed by a drag is not a click on that row."""
    picker = _picker()
    codex_line = picker_state.HEADER_LINES + _index_of(picker, host.CODEX) * picker_state.LINES_PER_ROW + 1

    event = picker_state.decode(f"\x1b[<0;10;{codex_line}m")

    assert event == picker_state.Event(Action.CLICK, _index_of(picker, host.CODEX))
    assert picker.apply(event).chosen() == (host.CODEX,)


def test_a_mouse_press_is_ignored_until_release() -> None:
    """Ignore the press because acting twice on one click would toggle the row back off."""
    assert picker_state.decode("\x1b[<0;10;3M").action is Action.NONE


def test_a_click_on_a_detail_line_selects_nothing() -> None:
    """Return nothing off a gap line because a stray click must not toggle the row above it."""
    assert picker_state.row_at_line(picker_state.HEADER_LINES + 2) is None


def test_a_right_button_click_is_ignored() -> None:
    """Read only the left button because a context click is not a selection anywhere else either."""
    assert picker_state.decode("\x1b[<2;10;3m").action is Action.NONE


def test_the_frame_lists_what_each_selected_host_writes() -> None:
    """Name the paths because D4 requires the reader to see what lands before they confirm."""
    picker = _picker().toggle(_index_of(_picker(), host.CODEX))

    written = picker_state.writes_for(picker)

    assert written
    assert all(host_manifest.load(host.CODEX).title in line for line in written)


def test_enter_returns_the_selection_in_row_order() -> None:
    """Answer in row order because the router installs in the order the reader saw."""
    keys = io.StringIO(" \x1b[B \r")
    picker = Picker(picker_state.rows_for(host_manifest.load_all()), cursor=_index_of(_picker(), host.CODEX))

    chosen = host_picker.drive(picker, keys, io.StringIO())

    assert chosen == (host.CODEX, host.OMP)


def test_cancelling_returns_nothing_rather_than_an_empty_choice() -> None:
    """Separate cancel from empty because one must leave disk alone and the other already does."""
    assert host_picker.drive(_picker(), io.StringIO("q"), io.StringIO()) is None


def test_confirming_with_no_row_selected_returns_an_empty_choice() -> None:
    """Return empty because the router must then install nothing and touch no file."""
    assert host_picker.drive(_picker(), io.StringIO("\r"), io.StringIO()) == ()


def test_a_closed_stream_cancels_rather_than_installing() -> None:
    """Treat end of input as cancel because a lost terminal must never confirm a selection."""
    assert host_picker.drive(_picker(), io.StringIO(""), io.StringIO()) is None


def test_the_flag_path_needs_no_terminal(capsys) -> None:
    """Skip the picker because an agent or a CI job has no terminal to draw on."""
    status = host_picker.main(["--host", host.CODEX, "--host", host.OMP])

    assert status == 0
    assert capsys.readouterr().out.split() == [host.CODEX, host.OMP]


def test_the_flag_path_refuses_a_host_with_no_installer(capsys) -> None:
    """Name the refusal because silently dropping Claude would look like a successful install."""
    status = host_picker.main(["--host", host.COWORK])

    assert status == 2
    assert "no installer" in capsys.readouterr().err


def test_the_flag_path_reports_each_host_once(capsys) -> None:
    """Collapse repeats because running an installer twice doubles its backup files."""
    host_picker.main(["--host", host.CODEX, "--host", host.CODEX])

    assert capsys.readouterr().out.split() == [host.CODEX]


def test_the_list_flag_names_only_installable_hosts(capsys) -> None:
    """List what the router can run because a name with no installer sends it into a dead end."""
    status = host_picker.main(["--list"])

    assert status == 0
    assert capsys.readouterr().out.split() == [host.CLAUDE, host.CODEX, host.OMP]


@pytest.mark.parametrize("sequence", ("\x1b[A", "k"))
def test_both_arrow_and_vi_keys_move_up(sequence: str) -> None:
    """Accept both because a reader on a terminal without arrow reporting still needs to move."""
    assert picker_state.decode(sequence).action is Action.MOVE_UP
