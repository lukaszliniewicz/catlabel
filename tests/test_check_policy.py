from __future__ import annotations

import unittest

from tools.check import compare_debt


class DebtPolicyTests(unittest.TestCase):
    def test_same_count_cannot_exchange_an_old_error_for_a_new_error(self) -> None:
        old = {
            "path": "catlabel/example.py",
            "rule": "F821",
            "message": "old",
            "line": 4,
        }
        new = dict(old, message="new")
        added, resolved = compare_debt([new], [old])
        self.assertEqual(len(added), 1)
        self.assertEqual(resolved, 1)

    def test_identical_duplicate_errors_are_counted(self) -> None:
        error = {"path": "catlabel/example.py", "rule": "F821", "line": 4}
        added, resolved = compare_debt([error, error], [error])
        self.assertEqual(len(added), 1)
        self.assertEqual(resolved, 0)

    def test_removed_errors_do_not_allow_new_positions(self) -> None:
        old = {"path": "catlabel/example.py", "rule": "F821", "line": 4}
        self.assertEqual(compare_debt([], [old]), ([], 1))
        added, _ = compare_debt([dict(old, line=5)], [old])
        self.assertEqual(len(added), 1)


if __name__ == "__main__":
    unittest.main()
