from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from catlabel.core.resource_limits import MAX_BATCH_RECORDS, MAX_DIMENSION
from catlabel.services.ai_tools import tool_set_batch_records


class AIBatchLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.canvas_state = {
            "batchRecords": [{"previous": "keep"}],
            "__actions__": [{"action": "keep"}],
            "other": "untouched",
        }

    def test_giant_cartesian_product_is_rejected_before_product_iteration(self) -> None:
        matrix = {f"axis_{index}": ["a", "b"] for index in range(100)}
        before = copy.deepcopy(self.canvas_state)

        with patch(
            "itertools.product", side_effect=AssertionError("too early")
        ) as product:
            result = tool_set_batch_records(
                {"variables_matrix": matrix}, self.canvas_state, 384, 384
            )

        self.assertTrue(result.startswith("Error:"))
        self.assertIn(str(MAX_BATCH_RECORDS), result)
        product.assert_not_called()
        self.assertEqual(self.canvas_state, before)

    def test_huge_positive_and_negative_sequences_are_rejected_before_range(
        self,
    ) -> None:
        for end in (MAX_BATCH_RECORDS, -MAX_BATCH_RECORDS):
            with self.subTest(end=end):
                before = copy.deepcopy(self.canvas_state)
                with patch(
                    "builtins.range", side_effect=AssertionError("too early")
                ) as range_mock:
                    result = tool_set_batch_records(
                        {
                            "variables_sequence": {
                                "variable_name": "serial",
                                "start": 0,
                                "end": end,
                            }
                        },
                        self.canvas_state,
                        384,
                        384,
                    )

                self.assertTrue(result.startswith("Error:"))
                self.assertIn(str(MAX_BATCH_RECORDS), result)
                range_mock.assert_not_called()
                self.assertEqual(self.canvas_state, before)

    def test_combined_overflow_is_rejected_before_sequence_or_matrix_materialize(
        self,
    ) -> None:
        explicit = [{"row": index} for index in range(500)]
        before = copy.deepcopy(self.canvas_state)

        with (
            patch(
                "builtins.range", side_effect=AssertionError("too early")
            ) as range_mock,
            patch(
                "itertools.product", side_effect=AssertionError("too early")
            ) as product,
        ):
            result = tool_set_batch_records(
                {
                    "variables_list": explicit,
                    "variables_sequence": {
                        "variable_name": "serial",
                        "start": 0,
                        "end": 498,
                    },
                    "variables_matrix": {"shade": ["red", "blue"]},
                },
                self.canvas_state,
                384,
                384,
            )

        self.assertEqual(
            result, f"Error: Combined batch exceeds {MAX_BATCH_RECORDS} records."
        )
        range_mock.assert_not_called()
        product.assert_not_called()
        self.assertEqual(self.canvas_state, before)

    def test_exact_combined_limit_preserves_order_and_legacy_values(self) -> None:
        explicit = [{"row": index} for index in range(498)]
        result = tool_set_batch_records(
            {
                "variables_list": explicit,
                "variables_sequence": {
                    "variable_name": "serial",
                    "start": -250,
                    "end": 249,
                    "prefix": "R",
                    "suffix": "X",
                    "padding": 4,
                },
                "variables_matrix": {"number": [123, 456]},
            },
            self.canvas_state,
            384,
            384,
        )

        records = self.canvas_state["batchRecords"]
        self.assertEqual(result, f"Configured {MAX_BATCH_RECORDS} batch records.")
        self.assertEqual(len(records), MAX_BATCH_RECORDS)
        self.assertEqual(records[:498], explicit)
        self.assertEqual(records[498], {"serial": "R-250X"})
        self.assertEqual(records[997], {"serial": "R0249X"})
        self.assertEqual(records[998:], [{"number": 123}, {"number": 456}])
        self.assertEqual(self.canvas_state["__actions__"], [{"action": "keep"}])
        self.assertEqual(self.canvas_state["other"], "untouched")

    def test_scalar_matrix_axis_remains_a_single_legacy_value(self) -> None:
        result = tool_set_batch_records(
            {"variables_matrix": {"quantity": 42}},
            self.canvas_state,
            384,
            384,
        )

        self.assertEqual(result, "Configured 1 batch records.")
        self.assertEqual(self.canvas_state["batchRecords"], [{"quantity": 42}])

    def test_invalid_shapes_empty_axes_and_list_count_preserve_existing_state(
        self,
    ) -> None:
        invalid_arguments = [
            {"variables_list": "not a list"},
            {"variables_list": [{"valid": 1}, "not a mapping"]},
            {"variables_list": [{}] * (MAX_BATCH_RECORDS + 1)},
            {"variables_matrix": []},
            {"variables_matrix": {"empty": []}},
            {"variables_sequence": "not a mapping"},
            {"variables_sequence": {"start": "not an integer", "end": 2}},
            {"variables_sequence": {"start": None, "end": 2}},
            {
                "variables_sequence": {
                    "variable_name": "serial",
                    "start": 1,
                    "end": 1,
                    "padding": -1,
                }
            },
            {
                "variables_sequence": {
                    "variable_name": "serial",
                    "start": 1,
                    "end": 1,
                    "padding": MAX_DIMENSION + 1,
                }
            },
        ]

        for args in invalid_arguments:
            with self.subTest(args=args):
                before = copy.deepcopy(self.canvas_state)
                result = tool_set_batch_records(args, self.canvas_state, 384, 384)
                self.assertTrue(result.startswith("Error:"), result)
                self.assertEqual(self.canvas_state, before)


if __name__ == "__main__":
    unittest.main()
