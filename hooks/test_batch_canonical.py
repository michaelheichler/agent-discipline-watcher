"""Split out of test_batch.py because canonical hashing internals do not belong beside ledger correlation or filesystem-race coverage in one file."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import batch
from lib import canonical
from testing import BatchTestCase


def doubling_dag(depth: int) -> object:
    """Module-level because two canonical-hashing tests below both build this alias-heavy shape."""
    node: object = {"leaf": 1}
    for _ in range(depth):
        node = [node, node]
    return node


def duplicated_tree(depth: int) -> object:
    """Built without shared references so that the two still canonicalize equal despite doubling_dag sharing nodes."""
    if depth == 0:
        return {"leaf": 1}
    return [duplicated_tree(depth - 1), duplicated_tree(depth - 1)]


def _counting_wrapper(target):
    """Records every call's args and return value, because two tests below must prove memoization collapses repeated visits to one."""
    calls: list[tuple[tuple, object]] = []

    def wrapper(*args, **kwargs):
        result = target(*args, **kwargs)
        calls.append((args, result))
        return result

    return wrapper, calls


class BatchCanonicalHashingTests(BatchTestCase):
    def test_arbitrary_size_integers_fully_correlate(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        for digits, value in ((101, 10**100), (5001, 10**5000)):
            with self.subTest(digits=digits):
                call = self._call(path, "same")
                call["tool_input"]["value"] = value
                duplicate = {
                    **call,
                    "tool_input": {
                        "value": value,
                        "file_path": str(path),
                    },
                }

                single = batch.findings_for_batch(
                    self._payload([call]), self.cfg, "turn-4"
                )
                repeated = batch.findings_for_batch(
                    self._payload([call, duplicate]), self.cfg, "turn-4"
                )

                self.assertEqual(repeated, single)
                self.assertIn(
                    "deferred_work_comment", {finding["rule"] for finding in repeated}
                )

    def test_huge_integer_patch_member_is_never_stringified_or_extracted(self):
        call = self._call("ignored.py", "huge-patch")
        del call["tool_input"]["file_path"]
        call["tool_input"]["patch"] = [
            "*** Add File: must-not-scan.py",
            10**5000,
        ]

        with patch.object(batch, "_normalized_path") as normalized_path:
            self.assertEqual(batch.run(self._payload([call]), self.cfg), {})

        normalized_path.assert_not_called()
        self.assertEqual(self._batch_decisions(), [])

    def test_canonical_dict_key_order_collapses(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        first = self._call(path, "same")
        first["tool_input"] = {"file_path": str(path), "value": [True, 1, None]}
        second = self._call(path, "same")
        second["tool_input"] = {"value": [True, 1, None], "file_path": str(path)}

        single = batch.findings_for_batch(self._payload([first]), self.cfg, "turn-4")
        repeated = batch.findings_for_batch(
            self._payload([first, second]), self.cfg, "turn-4"
        )

        self.assertEqual(repeated, single)

    def test_deep_canonical_input_correlates_without_recursion(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        nested: object = "leaf"
        for _ in range(600):
            nested = [nested]
        call = self._call(path, "deep")
        call["tool_input"]["nested"] = nested
        duplicate = dict(call)

        response = batch.run(self._payload([call, duplicate]), self.cfg)

        self.assert_block(response, "deferred_work_comment")
        self.assertNotIn(
            batch.DEGRADED_RULE, {row["rule"] for row in self._batch_decisions()}
        )

    def test_canonical_cycles_degrade_but_shared_acyclic_values_correlate(self):
        cycle: list[object] = []
        cycle.append(cycle)
        cyclic_call = self._call("bad.py", "cycle")
        cyclic_call["tool_input"]["nested"] = cycle

        self.assertEqual(batch.run(self._payload([cyclic_call]), self.cfg), {})
        self.assertEqual(self._batch_decisions()[-1]["rule"], batch.DEGRADED_RULE)

        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        shared = [{"value": 1}]
        shared_call = self._call(path, "shared")
        shared_call["tool_input"].update({"left": shared, "right": shared})
        response = batch.run(self._payload([shared_call, dict(shared_call)]), self.cfg)

        self.assert_block(response, "deferred_work_comment")
        self.assertNotEqual(self._batch_decisions()[-1]["rule"], batch.DEGRADED_RULE)

    def test_compact_dag_has_linear_work_and_alias_insensitive_equality(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        first = self._call(path, "dag")
        first["tool_input"]["nested"] = doubling_dag(18)
        second = self._call(path, "dag")
        second["tool_input"]["nested"] = doubling_dag(18)
        count_atom, atom_calls = _counting_wrapper(canonical._canonical_atom)

        with patch.object(canonical, "_canonical_atom", side_effect=count_atom):
            response = batch.run(self._payload([first, second]), self.cfg)

        self.assert_block(response, "deferred_work_comment")
        self.assertNotIn(
            batch.DEGRADED_RULE, {row["rule"] for row in self._batch_decisions()}
        )
        self.assertLessEqual(len(atom_calls), 20)
        self.assertEqual(
            canonical._canonical_value(doubling_dag(6)),
            canonical._canonical_value(duplicated_tree(6)),
        )

    def test_shared_dict_is_enumerated_once_and_equals_duplicated_values(self):
        size = 128
        shared = {str(index): index for index in range(size)}
        shared_value = [shared] * size
        duplicated_value = [dict(shared) for _ in range(size)]
        count_keys, key_calls = _counting_wrapper(canonical._exact_dict_keys)
        count_atom, atom_calls = _counting_wrapper(canonical._canonical_atom)

        with (
            patch.object(canonical, "_exact_dict_keys", side_effect=count_keys),
            patch.object(canonical, "_canonical_atom", side_effect=count_atom),
        ):
            shared_canonical = canonical._canonical_value(shared_value)

        shared_calls = [result for args, result in key_calls if args and args[0] is shared]
        self.assertEqual(len(shared_calls), 1)
        self.assertEqual(len(shared_calls[0]), size)
        self.assertEqual(len(atom_calls), size)
        self.assertEqual(shared_canonical, canonical._canonical_value(duplicated_value))

    def test_float_negative_zero_identity_is_preserved(self):
        path = self._write("bad.py", "# " + ("TO" + "DO") + " later\n")
        positive = self._call(path, "same")
        positive["tool_input"]["value"] = 0.0
        negative = self._call(path, "same")
        negative["tool_input"]["value"] = -0.0

        self.assertEqual(batch.run(self._payload([positive, negative]), self.cfg), {})
        self.assertEqual(
            [row["rule"] for row in self._batch_decisions()],
            [batch.DEGRADED_RULE],
        )


if __name__ == "__main__":
    unittest.main()
