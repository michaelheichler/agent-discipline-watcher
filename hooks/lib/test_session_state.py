from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from lib import session_state


class PluginDataHomeTests(unittest.TestCase):
    def test_resolves_under_the_adw_home(self):
        self.assertEqual(session_state.plugin_data_home(), Path.home() / ".adw")
        self.assertEqual(session_state.models_root(), Path.home() / ".adw" / "models")

    def test_a_host_data_directory_no_longer_splits_the_root(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": "/tmp/adw-data"}):
            self.assertEqual(session_state.plugin_data_home(), Path.home() / ".adw")

    def test_an_existing_legacy_home_is_migrated_once(self):
        with tempfile.TemporaryDirectory() as home:
            legacy = Path(home) / session_state.LEGACY_DATA_DIRNAME
            (legacy / "state").mkdir(parents=True)
            with mock.patch.object(Path, "home", staticmethod(lambda: Path(home))):
                first = session_state.plugin_data_home()
                second = session_state.plugin_data_home()

            self.assertEqual(first, second)
            self.assertTrue((first / "state").is_dir())
            self.assertFalse(legacy.exists())


class SessionStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_write_and_read_back(self):
        session_state.write_state("s1", {"count": 1}, root=self.root)
        self.assertEqual(session_state.read_state("s1", root=self.root), {"count": 1})

    def test_read_missing_file_returns_empty(self):
        self.assertEqual(session_state.read_state("nope", root=self.root), {})

    def test_read_corrupt_json_returns_empty(self):
        directory = self.root / "s1"
        directory.mkdir(parents=True)
        (directory / "state.json").write_text("{not valid", encoding="utf-8")
        self.assertEqual(session_state.read_state("s1", root=self.root), {})

    def test_read_non_dict_json_returns_empty(self):
        directory = self.root / "s1"
        directory.mkdir(parents=True)
        (directory / "state.json").write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(session_state.read_state("s1", root=self.root), {})

    def test_corrupt_json_then_update_overwrites(self):
        directory = self.root / "s1"
        directory.mkdir(parents=True)
        (directory / "state.json").write_text("BROKEN", encoding="utf-8")
        result = session_state.update_state(
            "s1",
            lambda state: {**state, "count": state.get("count", 0) + 1},
            root=self.root,
        )
        self.assertEqual(result, {"count": 1})
        self.assertEqual(session_state.read_state("s1", root=self.root), {"count": 1})

    def test_update_state_read_modify_write(self):
        session_state.write_state("s1", {"count": 1}, root=self.root)
        result = session_state.update_state(
            "s1",
            lambda state: {**state, "count": state["count"] + 1},
            root=self.root,
        )
        self.assertEqual(result, {"count": 2})
        self.assertEqual(session_state.read_state("s1", root=self.root), {"count": 2})

    def test_update_state_on_missing_file(self):
        result = session_state.update_state(
            "s1",
            lambda state: {**state, "count": state.get("count", 0) + 1},
            root=self.root,
        )
        self.assertEqual(result, {"count": 1})

    def test_concurrent_writers_do_not_lose_updates(self):
        writers = 8
        per_writer = 100

        def bump(state):
            # Delay because without it the test could pass even with a broken lock.
            time.sleep(0.0002)
            return {**state, "count": state.get("count", 0) + 1}

        def run_writers():
            for _ in range(per_writer):
                session_state.update_state("s1", bump, root=self.root)

        threads = [threading.Thread(target=run_writers) for _ in range(writers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(
            session_state.read_state("s1", root=self.root)["count"],
            writers * per_writer,
        )

    def test_unsafe_session_id_rejected(self):
        bad_ids = ("../evil", "a/b", "a\\b", "..", ".", "", "a\x00b")
        for bad in bad_ids:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    session_state.write_state(bad, {}, root=self.root)

    def test_unsafe_session_id_cannot_escape_root(self):
        before = set(self.root.iterdir()) if self.root.exists() else set()
        try:
            session_state.write_state("../escape", {"x": 1}, root=self.root)
        except ValueError:
            pass
        after = set(self.root.iterdir()) if self.root.exists() else set()
        self.assertEqual(before, after)

    def test_symlink_session_id_cannot_redirect_write_outside_root(self):
        with tempfile.TemporaryDirectory() as outside:
            victim = Path(outside)
            (self.root / "s1").symlink_to(victim)
            with self.assertRaises(ValueError):
                session_state.write_state("s1", {"pwned": True}, root=self.root)
            self.assertFalse((victim / "state.json").exists())

    def test_symlink_session_id_cannot_redirect_cleanup_outside_root(self):
        """Cleanup deletes a tree, so an escape here destroys data rather than merely misplacing it."""
        with tempfile.TemporaryDirectory() as outside:
            keep = Path(outside) / "keep.txt"
            keep.write_text("data", encoding="utf-8")
            (self.root / "c1").symlink_to(outside)
            with self.assertRaises(ValueError):
                session_state.cleanup_session("c1", root=self.root)
            self.assertTrue(keep.exists())

    def test_symlink_pointing_inside_root_is_allowed(self):
        target = self.root / "real-target"
        target.mkdir()
        (self.root / "alias").symlink_to(target)
        session_state.write_state("alias", {"ok": True}, root=self.root)
        self.assertEqual(session_state.read_state("alias", root=self.root), {"ok": True})

    def test_session_id_with_internal_dot_is_accepted(self):
        session_state.write_state("my.session", {"ok": True}, root=self.root)
        self.assertEqual(session_state.read_state("my.session", root=self.root), {"ok": True})
        self.assertTrue((self.root / "my.session").is_dir())

    def test_advance_turn_sets_the_first_turn(self) -> None:
        state = session_state.advance_turn("s1", root=self.root)
        self.assertEqual(state["turn_count"], 1)
        self.assertEqual(state["turn_id"], "turn-1")

    def test_advance_turn_increments_existing_state(self) -> None:
        session_state.write_state("s1", {"turn_count": 2, "other": True}, root=self.root)
        state = session_state.advance_turn("s1", root=self.root)
        self.assertEqual(state, {"turn_count": 3, "turn_id": "turn-3", "other": True})

    def test_cleanup_session_removes_directory(self):
        session_state.write_state("s1", {"count": 1}, root=self.root)
        self.assertTrue((self.root / "s1").exists())
        session_state.cleanup_session("s1", root=self.root)
        self.assertFalse((self.root / "s1").exists())

    def test_cleanup_missing_session_is_noop(self):
        session_state.cleanup_session("never", root=self.root)
        self.assertFalse((self.root / "never").exists())

    def test_sweep_stale_removes_only_old_directories(self):
        fresh = self.root / "fresh"
        stale_dir = self.root / "old"
        fresh.mkdir()
        stale_dir.mkdir()
        (fresh / "state.json").write_text("{}", encoding="utf-8")
        (stale_dir / "state.json").write_text("{}", encoding="utf-8")
        now = time.time()
        old_mtime = now - 7200
        os.utime(stale_dir, (old_mtime, old_mtime))
        removed = session_state.sweep_stale(
            max_age_seconds=3600, root=self.root, now=now
        )
        self.assertEqual(removed, 1)
        self.assertTrue(fresh.exists())
        self.assertFalse(stale_dir.exists())

    def test_sweep_stale_also_removes_a_live_but_quiet_session(self):
        # Pinning the known ceiling because mtime cannot tell a live quiet session from an abandoned one.
        quiet = self.root / "quiet-live"
        quiet.mkdir()
        (quiet / "state.json").write_text("{}", encoding="utf-8")
        now = time.time()
        backdated = now - 7200
        os.utime(quiet, (backdated, backdated))
        removed = session_state.sweep_stale(
            max_age_seconds=3600, root=self.root, now=now
        )
        self.assertEqual(removed, 1)
        self.assertFalse(quiet.exists())

    def test_sweep_stale_keeps_an_old_session_with_a_live_lease(self):
        session = self.root / "live"
        session.mkdir()
        (session / "state.json").write_text("{}", encoding="utf-8")
        now = time.time()
        old_mtime = now - 31 * 24 * 60 * 60
        os.utime(session, (old_mtime, old_mtime))
        session_state.acquire_session_lease("live", root=self.root, now=now)

        removed = session_state.sweep_stale(
            max_age_seconds=30 * 24 * 60 * 60, root=self.root, now=now
        )

        self.assertEqual(removed, 0)
        self.assertTrue(session.exists())

    def test_released_session_lease_no_longer_protects_stale_session(self):
        session = self.root / "ended"
        session.mkdir()
        (session / "state.json").write_text("{}", encoding="utf-8")
        now = time.time()
        old_mtime = now - 31 * 24 * 60 * 60
        os.utime(session, (old_mtime, old_mtime))
        session_state.acquire_session_lease("ended", root=self.root, now=now)
        session_state.release_session_lease("ended", root=self.root)

        removed = session_state.sweep_stale(
            max_age_seconds=30 * 24 * 60 * 60, root=self.root, now=now
        )

        self.assertEqual(removed, 1)
        self.assertFalse(session.exists())

    def test_sweep_stale_ignores_stray_files(self):
        (self.root / "stray.txt").write_text("x", encoding="utf-8")
        removed = session_state.sweep_stale(
            max_age_seconds=3600, root=self.root, now=time.time()
        )
        self.assertEqual(removed, 0)

    def test_sweep_stale_on_missing_root_returns_zero(self):
        removed = session_state.sweep_stale(
            max_age_seconds=3600, root=self.root / "nonexistent"
        )
        self.assertEqual(removed, 0)

    def test_sweep_stale_tolerates_rmtree_failure(self):
        stale_dir = self.root / "old"
        stale_dir.mkdir()
        (stale_dir / "state.json").write_text("{}", encoding="utf-8")
        now = time.time()
        old_mtime = now - 7200
        os.utime(stale_dir, (old_mtime, old_mtime))
        with mock.patch.object(
            session_state.shutil, "rmtree", side_effect=OSError("busy")
        ):
            removed = session_state.sweep_stale(
                max_age_seconds=3600, root=self.root, now=now
            )
        self.assertEqual(removed, 0)
        self.assertTrue(stale_dir.exists())


if __name__ == "__main__":
    unittest.main()
