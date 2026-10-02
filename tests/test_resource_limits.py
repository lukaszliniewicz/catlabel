from __future__ import annotations

import unittest
from collections.abc import Sequence
from math import inf, nan
from typing import NoReturn

from catlabel.core.resource_limits import (
    MAX_BATCH_RECORDS,
    MAX_CANVAS_ENTRIES,
    MAX_DIMENSION,
    MAX_IMAGE_BYTES,
    MAX_PRINT_COPIES,
    MAX_PRINT_JOBS,
    MAX_RENDER_PIXELS,
    MAX_REQUEST_BYTES,
    MAX_UPLOAD_BYTES,
    ResourceLimitError,
    batch_record_count,
    require_count,
    validate_image_budget,
    validate_render_budget,
)


class LengthOnlyAxis(Sequence[str]):
    def __init__(self, length: int) -> None:
        self.length = length
        self.length_calls = 0

    def __len__(self) -> int:
        self.length_calls += 1
        return self.length

    def __getitem__(self, index: int | slice) -> NoReturn:
        raise AssertionError(f"axis values must not be enumerated: {index}")


class ResourceLimitTests(unittest.TestCase):
    def test_configured_limits_are_positive_and_exposed_as_explicit_constants(
        self,
    ) -> None:
        self.assertEqual(
            (
                MAX_BATCH_RECORDS,
                MAX_PRINT_COPIES,
                MAX_PRINT_JOBS,
                MAX_RENDER_PIXELS,
                MAX_DIMENSION,
                MAX_CANVAS_ENTRIES,
                MAX_REQUEST_BYTES,
                MAX_UPLOAD_BYTES,
                MAX_IMAGE_BYTES,
            ),
            (
                1000,
                100,
                500,
                50_000_000,
                20_000,
                10_000,
                67_108_864,
                16_777_216,
                8_388_608,
            ),
        )

    def test_require_count_accepts_limits_and_rejects_nonpositive_or_coerced_values(
        self,
    ) -> None:
        self.assertEqual(require_count(1, name="count", maximum=3), 1)
        self.assertEqual(require_count(3, name="count", maximum=3), 3)
        for value in (True, False, "2", 2.0, 0, -1, 4):
            with self.subTest(value=value), self.assertRaises(ResourceLimitError):
                require_count(value, name="count", maximum=3)

    def test_batch_record_count_defaults_and_accepts_exact_limit(self) -> None:
        self.assertEqual(batch_record_count([], None), 1)
        self.assertEqual(batch_record_count([], {}), 1)
        self.assertEqual(batch_record_count([{}] * 4, {}), 4)
        self.assertEqual(batch_record_count([{}] * MAX_BATCH_RECORDS, None), 1000)
        self.assertEqual(
            batch_record_count([], {"serial": ["x"] * MAX_BATCH_RECORDS}), 1000
        )

    def test_batch_record_count_rejects_oversized_lists_and_empty_or_large_axes(
        self,
    ) -> None:
        with self.assertRaises(ResourceLimitError):
            batch_record_count([{}] * (MAX_BATCH_RECORDS + 1), None)
        for matrix in ({"empty": []}, {"large": ["x"] * (MAX_BATCH_RECORDS + 1)}):
            with (
                self.subTest(matrix=tuple(matrix)),
                self.assertRaises(ResourceLimitError),
            ):
                batch_record_count([], matrix)

    def test_batch_product_stops_after_first_oversized_product_without_iteration(
        self,
    ) -> None:
        first = LengthOnlyAxis(40)
        second = LengthOnlyAxis(30)
        third = LengthOnlyAxis(2)
        with self.assertRaises(ResourceLimitError):
            batch_record_count([], {"first": first, "second": second, "third": third})
        self.assertEqual(
            (first.length_calls, second.length_calls, third.length_calls), (1, 1, 0)
        )

    def test_batch_record_count_caps_combined_list_and_matrix_total(self) -> None:
        self.assertEqual(
            batch_record_count([{}], {"axis": ["x"] * (MAX_BATCH_RECORDS - 1)}),
            MAX_BATCH_RECORDS,
        )
        with self.assertRaises(ResourceLimitError):
            batch_record_count([{}, {}], {"axis": ["x"] * (MAX_BATCH_RECORDS - 1)})

    def test_render_budget_counts_unique_item_and_layout_pages(self) -> None:
        canvas = {
            "width": 10,
            "height": 20,
            "currentPage": 499,
            "items": [{"pageIndex": "2"}, {"pageIndex": 2}],
            "pageLayouts": [
                {"pageIndex": None},
                {"pageIndex": "1.0"},
                {"pageIndex": 2},
            ],
        }
        self.assertEqual(
            validate_render_budget(canvas, records=3, copies=2), (18, 3600)
        )

    def test_render_budget_uses_default_dimensions_and_ignores_current_page(
        self,
    ) -> None:
        self.assertEqual(
            validate_render_budget({}, records=1, copies=1), (1, 384 * 384)
        )
        self.assertEqual(
            validate_render_budget({"currentPage": 499}, records=1, copies=1),
            (1, 384 * 384),
        )
        self.assertEqual(
            validate_render_budget(
                {"width": 1.25, "height": 2.25}, records=1, copies=1
            ),
            (1, 6),
        )

    def test_render_budget_accepts_job_and_pixel_boundaries(self) -> None:
        self.assertEqual(
            validate_render_budget({"width": 1, "height": 1}, records=250, copies=2),
            (MAX_PRINT_JOBS, MAX_PRINT_JOBS),
        )
        self.assertEqual(
            validate_render_budget({}, records=339, copies=1),
            (339, 339 * 384 * 384),
        )
        with self.assertRaises(ResourceLimitError):
            validate_render_budget({"width": 1, "height": 1}, records=251, copies=2)
        with self.assertRaises(ResourceLimitError):
            validate_render_budget({}, records=340, copies=1)

    def test_render_budget_rejects_invalid_counts_dimensions_and_page_indices(
        self,
    ) -> None:
        for records, copies in ((0, 1), (True, 1), (1001, 1), (1, 0), (1, 101)):
            with (
                self.subTest(records=records, copies=copies),
                self.assertRaises(ResourceLimitError),
            ):
                validate_render_budget({}, records=records, copies=copies)

        for dimension in (True, "384", 0, -1, 20_001, inf, nan):
            with (
                self.subTest(dimension=dimension),
                self.assertRaises(ResourceLimitError),
            ):
                validate_render_budget({"width": dimension}, records=1, copies=1)

        for page_index in (
            True,
            -1,
            1.5,
            inf,
            nan,
            "not-a-number",
            "1.0000000000000001",
            500,
        ):
            with (
                self.subTest(page_index=page_index),
                self.assertRaises(ResourceLimitError),
            ):
                validate_render_budget(
                    {"items": [{"pageIndex": page_index}]}, records=1, copies=1
                )

    def test_render_budget_limits_canvas_entry_lists_and_requires_mappings(
        self,
    ) -> None:
        valid_entries = [{"pageIndex": 0}] * MAX_CANVAS_ENTRIES
        self.assertEqual(
            validate_render_budget({"items": valid_entries}, records=1, copies=1),
            (1, 384 * 384),
        )
        with self.assertRaises(ResourceLimitError):
            validate_render_budget({"items": valid_entries + [{}]}, records=1, copies=1)
        for canvas in (
            {"items": ()},
            {"pageLayouts": [None]},
            {"items": [{"pageIndex": 0}], "pageLayouts": [object()]},
        ):
            with (
                self.subTest(canvas=canvas.keys()),
                self.assertRaises(ResourceLimitError),
            ):
                validate_render_budget(canvas, records=1, copies=1)

    def test_image_budget_accumulates_before_allocation(self) -> None:
        self.assertEqual(validate_image_budget(1, 1), 1)
        self.assertEqual(
            validate_image_budget(1, 1, MAX_RENDER_PIXELS - 1), MAX_RENDER_PIXELS
        )
        with self.assertRaises(ResourceLimitError):
            validate_image_budget(1, 1, MAX_RENDER_PIXELS)
        with self.assertRaises(ResourceLimitError):
            validate_image_budget(20_000, 20_000)

    def test_image_budget_requires_positive_integer_dimensions_and_prior_total(
        self,
    ) -> None:
        for args in (
            (True, 1, 0),
            (1, False, 0),
            (0, 1, 0),
            (1, -1, 0),
            (20_001, 1, 0),
            (1.0, 1, 0),
            (1, 1, -1),
            (1, 1, True),
            (1, 1, 0.0),
        ):
            with self.subTest(args=args), self.assertRaises(ResourceLimitError):
                validate_image_budget(*args)


if __name__ == "__main__":
    unittest.main()
