"""Split out of test_batch.py because filesystem-race coverage does not belong beside ledger correlation or canonical hashing in one file."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

import batch
from lib import session_state
from testing import BatchTestCase


def _mutating_read(original_read, changing: Path, mutated: str, mutations: list) -> callable:
    """Swaps changing's content between stat and read exactly once, because two tests below both need this same race simulation."""

    def mutate(candidate: Path, config: dict) -> str | None:
        if candidate == changing:
            before = candidate.stat()
            old_text = original_read(candidate, config)
            candidate.write_text(mutated, encoding="utf-8")
            os.utime(candidate, ns=(before.st_atime_ns, before.st_mtime_ns))
            mutations.append((before, candidate.stat()))
            return old_text
        return original_read(candidate, config)

    return mutate


def _fingerprint_without_ctime(original_fingerprint) -> callable:
    """Closes over the real fingerprint captured before patching, because a live batch._stat_fingerprint lookup would resolve to this same patch and recurse."""

    def fingerprint(file_stat: os.stat_result) -> tuple[int, ...]:
        return original_fingerprint(file_stat)[:4]

    return fingerprint


class BatchFilesystemRaceTests(BatchTestCase):
    def test_symlink_aliases_do_not_trigger_duplicate_file_content(self):
        target = self._write("target.py", self._duplicate_text())
        alias = self.root / "alias.py"
        try:
            alias.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symlinks unsupported: {exc}")

        response = batch.run(
            self._payload([self._call(target, None), self._call(alias, None)]),
            self.cfg,
        )

        self.assertEqual(response, {})

    def test_hardlink_aliases_do_not_trigger_duplicate_file_content(self):
        target = self._write("target.py", self._duplicate_text())
        alias = self.root / "alias.py"
        try:
            os.link(target, alias)
        except OSError as exc:
            self.skipTest(f"hardlinks unsupported: {exc}")

        response = batch.run(
            self._payload([self._call(target, None), self._call(alias, None)]),
            self.cfg,
        )

        self.assertEqual(response, {})

    def test_symlink_and_hardlink_aliases_are_one_file(self):
        actual = self._write("actual.py", self._duplicate_text())
        symlink = self.root / "alias.py"
        hardlink = self.root / "hardlink.py"
        try:
            symlink.symlink_to(actual)
            os.link(actual, hardlink)
        except OSError as exc:
            self.skipTest(f"symlinks or hardlinks unsupported: {exc}")
        calls = [
            self._call(actual, None),
            self._call(symlink, None),
            self._call(hardlink, None),
        ]

        self.assertEqual(batch.run(self._payload(calls), self.cfg), {})

    def test_relative_and_absolute_paths_to_one_inode_are_not_duplicates(self):
        actual = self._write("actual.py", self._duplicate_text())

        response = batch.run(
            self._payload(
                [self._call(actual.name, "relative"), self._call(actual, "absolute")]
            ),
            self.cfg,
        )

        self.assertEqual(response, {})
        self.assertNotIn(
            "duplicate_file_content",
            {row["rule"] for row in self._batch_decisions()},
        )

    def test_duplicate_content_requires_200_nonspace_characters(self):
        for size, should_report in ((199, False), (200, True)):
            with self.subTest(size=size):
                session_id = f"boundary-{size}"
                session_state.write_state(
                    session_id, {"turn_id": "turn-4"}, self.state_root
                )
                text = "x" * size
                left = self._write(f"left-{size}.py", text)
                right = self._write(f"right-{size}.py", text)

                response = batch.run(
                    self._payload(
                        [self._call(left, "left"), self._call(right, "right")],
                        session_id,
                    ),
                    self.cfg,
                )

                if should_report:
                    self.assert_block(response, "duplicate_file_content")
                else:
                    self.assertEqual(response, {})

    def test_disappearance_between_stat_and_read_is_harmless(self):
        path = self._write("vanishing.py", self._duplicate_text())

        def disappear(candidate: Path, _config: dict) -> None:
            candidate.unlink()

        with patch.object(batch, "read_scannable", side_effect=disappear):
            response = batch.run(self._payload([self._call(path, None)]), self.cfg)

        self.assertEqual(response, {})

    def test_inode_replacement_between_stat_and_read_is_harmless(self):
        path = self._write("first.py", self._duplicate_text())
        stable = self._write("second.py", self._duplicate_text())
        replacement = self._write("replacement.py", self._duplicate_text())
        original_read = batch.read_scannable
        replacements = 0

        def replace(candidate: Path, config: dict) -> str | None:
            nonlocal replacements
            if candidate == path:
                replacement.replace(candidate)
                replacements += 1
            return original_read(candidate, config)

        with patch.object(batch, "read_scannable", side_effect=replace):
            response = batch.run(
                self._payload([self._call(path, None), self._call(stable, None)]),
                self.cfg,
            )

        self.assertEqual(replacements, 1)
        self.assertEqual(response, {})
        self.assertNotIn(
            "duplicate_file_content",
            {row["rule"] for row in self._batch_decisions()},
        )

    def _assert_harmless_mutation(
        self, response: dict, mutations: list, changing: Path, original_inode: int, mutated: str,
    ) -> None:
        self.assertEqual(len(mutations), 1)
        before, after = mutations[0]
        self.assertEqual(after.st_size, before.st_size)
        self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
        self.assertNotEqual(after.st_ctime_ns, before.st_ctime_ns)
        self.assertEqual(changing.stat().st_ino, original_inode)
        self.assertEqual(changing.read_text(encoding="utf-8"), mutated)
        self.assertEqual(response, {})
        self.assertNotIn(
            "duplicate_file_content",
            {row["rule"] for row in self._batch_decisions()},
        )

    def test_in_place_mutation_between_stat_and_read_is_harmless_unless_ctime_is_ignored(self):
        original = self._duplicate_text()
        mutated = "x" * len(original)
        changing = self._write("first.py", original)
        stable = self._write("second.py", original)
        original_inode = changing.stat().st_ino
        mutations: list[tuple[os.stat_result, os.stat_result]] = []
        mutate = _mutating_read(batch.read_scannable, changing, mutated, mutations)

        with patch.object(batch, "read_scannable", side_effect=mutate):
            response = batch.run(
                self._payload([self._call(changing, None), self._call(stable, None)]), self.cfg,
            )
        self._assert_harmless_mutation(response, mutations, changing, original_inode, mutated)
        changing.write_text(original, encoding="utf-8")
        session_state.write_state("mutant", {"turn_id": "turn-4"}, self.state_root)
        with (
            patch.object(batch, "read_scannable", side_effect=mutate),
            patch.object(batch, "_stat_fingerprint", side_effect=_fingerprint_without_ctime(batch._stat_fingerprint)),
        ):
            mutant = batch.run(
                self._payload([self._call(changing, None), self._call(stable, None)], "mutant"), self.cfg,
            )

        self.assertEqual(len(mutations), 2)
        self.assert_block(mutant, "duplicate_file_content")


if __name__ == "__main__":
    unittest.main()
