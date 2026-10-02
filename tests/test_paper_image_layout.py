from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from typing import cast
from unittest.mock import Mock, patch

from PIL import Image

import catlabel.rendering.paper_layout as paper_layout_module
from catlabel.core.resource_limits import (
    MAX_DIMENSION,
    MAX_RENDER_PIXELS,
    ResourceLimitError,
)
from catlabel.rendering.paper_layout import (
    PaperImageLayout,
    plan_image_layout,
    prepare_paper_images,
)


class _SizeOnlyImage:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.transpose = Mock(side_effect=AssertionError("unexpected transpose"))
        self.convert = Mock(side_effect=AssertionError("unexpected conversion"))
        self.crop = Mock(side_effect=AssertionError("unexpected crop"))
        self.resize = Mock(side_effect=AssertionError("unexpected resize"))


def _pixel_rows(image: Image.Image) -> list[list[tuple[int, int, int]]]:
    return [
        [cast(tuple[int, int, int], image.getpixel((x, y))) for x in range(image.width)]
        for y in range(image.height)
    ]


def _asymmetric_image() -> Image.Image:
    image = Image.new("RGB", (2, 3))
    image.putdata(
        [
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 0),
            (255, 255, 255),
            (0, 0, 0),
        ]
    )
    return image


def _patterned_image(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGB", size)
    image.putdata(
        [
            (
                (x * 73 + y * 29 + 11) % 256,
                (x * 31 + y * 61 + 17) % 256,
                (x * 47 + y * 19 + 23) % 256,
            )
            for y in range(size[1])
            for x in range(size[0])
        ]
    )
    return image


def _reference_normalize_then_fit(
    source: Image.Image,
    render_width_px: int,
    render_height_px: int,
    rotation_degrees: int,
) -> Image.Image:
    transpose = {
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }.get(rotation_degrees)
    rotated = source.transpose(transpose) if transpose is not None else source.copy()
    rgb = rotated.convert("RGB")
    try:
        if rgb.width > render_width_px:
            normalized_height = max(
                1,
                int(rgb.height * render_width_px / float(rgb.width)),
            )
            normalized = rgb.resize(
                (render_width_px, normalized_height), Image.Resampling.LANCZOS
            )
        elif rgb.width < render_width_px:
            normalized = Image.new("RGB", (render_width_px, rgb.height), "white")
            normalized.paste(
                rgb,
                ((render_width_px - rgb.width) // 2, 0),
            )
        else:
            normalized = rgb.copy()

        try:
            if normalized.height > render_height_px:
                fitted_width = max(
                    1,
                    round(render_width_px * render_height_px / normalized.height),
                )
                fitted = normalized.resize(
                    (fitted_width, render_height_px), Image.Resampling.LANCZOS
                )
            else:
                fitted = normalized

            try:
                canvas = Image.new("RGB", (render_width_px, render_height_px), "white")
                vertical_offset = (
                    (render_height_px - fitted.height) // 2
                    if normalized.height <= render_height_px
                    else 0
                )
                canvas.paste(
                    fitted,
                    ((render_width_px - fitted.width) // 2, vertical_offset),
                )
                return canvas
            finally:
                if fitted is not normalized:
                    fitted.close()
        finally:
            normalized.close()
    finally:
        rgb.close()
        rotated.close()


class PaperImageLayoutTests(unittest.TestCase):
    def test_layout_normalizes_rotation_and_rejects_invalid_values(self) -> None:
        layout = PaperImageLayout(4, rotation_degrees=-270)
        self.assertEqual(layout.rotation_degrees, 90)
        with self.assertRaises(FrozenInstanceError):
            layout.rotation_degrees = 180  # type: ignore[misc]
        with self.assertRaises(ValueError):
            PaperImageLayout(4, rotation_degrees=45)
        with self.assertRaises(ValueError):
            PaperImageLayout(4, rotation_degrees=True)  # type: ignore[arg-type]

    def test_layout_rejects_nonpositive_and_oversized_render_dimensions(self) -> None:
        for kwargs in (
            {"render_width_px": 0},
            {"render_width_px": MAX_DIMENSION + 1},
            {"render_width_px": 4, "render_height_px": 0},
            {"render_width_px": 4, "render_height_px": MAX_DIMENSION + 1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ResourceLimitError):
                PaperImageLayout(**kwargs)  # type: ignore[arg-type]

    def test_clockwise_rotation_pixels_and_composition(self) -> None:
        expected = {
            90: [
                [(255, 255, 255), (0, 0, 255), (255, 0, 0)],
                [(0, 0, 0), (255, 255, 0), (0, 255, 0)],
            ],
            180: [
                [(0, 0, 0), (255, 255, 255)],
                [(255, 255, 0), (0, 0, 255)],
                [(0, 255, 0), (255, 0, 0)],
            ],
            270: [
                [(0, 255, 0), (255, 255, 0), (0, 0, 0)],
                [(255, 0, 0), (0, 0, 255), (255, 255, 255)],
            ],
        }
        for rotation, pixels in expected.items():
            source = _asymmetric_image()
            outputs = prepare_paper_images(
                [source],
                PaperImageLayout(
                    render_width_px=len(pixels[0]),
                    rotation_degrees=rotation,
                ),
            )
            try:
                self.assertEqual(_pixel_rows(outputs[0]), pixels)
            finally:
                for output in outputs:
                    output.close()
                source.close()

        source = _asymmetric_image()
        user_rotated = source.transpose(Image.Transpose.ROTATE_270)
        outputs = prepare_paper_images(
            [user_rotated], PaperImageLayout(2, rotation_degrees=90)
        )
        try:
            self.assertEqual(_pixel_rows(outputs[0]), expected[180])
        finally:
            for output in outputs:
                output.close()
            user_rotated.close()
            source.close()

    def test_narrow_images_are_centered_without_upscaling(self) -> None:
        source = Image.new("RGB", (3, 2), "black")
        outputs = prepare_paper_images([source], PaperImageLayout(6))
        try:
            self.assertEqual(outputs[0].size, (6, 2))
            self.assertEqual(
                _pixel_rows(outputs[0]),
                [
                    [
                        (255, 255, 255),
                        (0, 0, 0),
                        (0, 0, 0),
                        (0, 0, 0),
                        (255, 255, 255),
                        (255, 255, 255),
                    ],
                    [
                        (255, 255, 255),
                        (0, 0, 0),
                        (0, 0, 0),
                        (0, 0, 0),
                        (255, 255, 255),
                        (255, 255, 255),
                    ],
                ],
            )
        finally:
            outputs[0].close()
            source.close()

    def test_wide_images_fit_render_width_with_existing_floor_rounding(self) -> None:
        source = Image.new("RGB", (10, 7), (12, 34, 56))
        outputs = prepare_paper_images([source], PaperImageLayout(6))
        try:
            self.assertEqual(outputs[0].size, (6, 4))
            self.assertEqual(outputs[0].getpixel((2, 2)), (12, 34, 56))
        finally:
            outputs[0].close()
            source.close()

    def test_fixed_height_aspect_fits_and_centers_with_white_edges(self) -> None:
        tall = Image.new("RGB", (4, 9), "black")
        fitted = prepare_paper_images([tall], PaperImageLayout(8, 3))[0]
        expected = _reference_normalize_then_fit(tall, 8, 3, 0)
        try:
            self.assertEqual(fitted.size, (8, 3))
            self.assertEqual(_pixel_rows(fitted), _pixel_rows(expected))
        finally:
            fitted.close()
            expected.close()
            tall.close()

        short = Image.new("RGB", (2, 2), "black")
        padded = prepare_paper_images([short], PaperImageLayout(6, 7))[0]
        try:
            self.assertEqual(padded.size, (6, 7))
            self.assertEqual(padded.getpixel((2, 2)), (0, 0, 0))
            self.assertEqual(padded.getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(padded.getpixel((2, 0)), (255, 255, 255))
        finally:
            padded.close()
            short.close()

    def test_height_fit_resamples_width_normalized_narrow_and_wide_images(self) -> None:
        cases = (
            ((7, 3), 5, 4, 90),
            ((7, 11), 5, 4, 0),
        )
        for size, render_width, render_height, rotation in cases:
            with self.subTest(
                size=size,
                render_width=render_width,
                render_height=render_height,
                rotation=rotation,
            ):
                source = _patterned_image(size)
                expected = _reference_normalize_then_fit(
                    source,
                    render_width,
                    render_height,
                    rotation,
                )
                outputs = prepare_paper_images(
                    [source],
                    PaperImageLayout(render_width, render_height, rotation),
                )
                try:
                    self.assertEqual(outputs[0].size, (render_width, render_height))
                    self.assertEqual(_pixel_rows(outputs[0]), _pixel_rows(expected))
                finally:
                    outputs[0].close()
                    expected.close()
                    source.close()

    def test_split_remainder_is_left_aligned(self) -> None:
        source = Image.new("RGB", (6, 2))
        source.putdata([(index * 30, 0, 0) for _y in range(2) for index in range(6)])
        outputs = prepare_paper_images([source], PaperImageLayout(4), split_mode=True)
        try:
            self.assertEqual([output.size for output in outputs], [(4, 2), (4, 2)])
            self.assertEqual(
                [outputs[1].getpixel((x, 0)) for x in range(4)],
                [(120, 0, 0), (150, 0, 0), (255, 255, 255), (255, 255, 255)],
            )
        finally:
            for output in outputs:
                output.close()
            source.close()

    def test_rotation_happens_before_split(self) -> None:
        source = Image.new("RGB", (2, 5))
        source.putdata([(x * 70, y * 30, 0) for y in range(5) for x in range(2)])
        rotated = source.transpose(Image.Transpose.ROTATE_270)
        outputs = prepare_paper_images(
            [source],
            PaperImageLayout(3, rotation_degrees=90),
            split_mode=True,
        )
        try:
            self.assertEqual([output.size for output in outputs], [(3, 2), (3, 2)])
            self.assertEqual(
                [outputs[0].getpixel((x, 0)) for x in range(3)],
                [rotated.getpixel((x, 0)) for x in range(3)],
            )
            self.assertEqual(
                [outputs[1].getpixel((x, 0)) for x in range(3)],
                [
                    rotated.getpixel((3, 0)),
                    rotated.getpixel((4, 0)),
                    (255, 255, 255),
                ],
            )
        finally:
            for output in outputs:
                output.close()
            rotated.close()
            source.close()

    def test_preflight_rejects_budgets_before_transformations(self) -> None:
        too_wide = _SizeOnlyImage(MAX_DIMENSION + 1, 1)
        with self.assertRaises(ResourceLimitError):
            prepare_paper_images([too_wide], PaperImageLayout(4))  # type: ignore[list-item]
        too_wide.transpose.assert_not_called()
        too_wide.convert.assert_not_called()

        too_many_strips = _SizeOnlyImage(MAX_DIMENSION, 1)
        with (
            patch.object(
                paper_layout_module.Image,
                "new",
                side_effect=AssertionError("unexpected canvas allocation"),
            ) as image_new,
            self.assertRaises(ResourceLimitError),
        ):
            prepare_paper_images(
                [too_many_strips],  # type: ignore[list-item]
                PaperImageLayout(1),
                split_mode=True,
            )
        image_new.assert_not_called()
        too_many_strips.crop.assert_not_called()
        too_many_strips.transpose.assert_not_called()
        too_many_strips.convert.assert_not_called()
        too_many_strips.resize.assert_not_called()

        oversized_final = _SizeOnlyImage(1, MAX_DIMENSION)
        with self.assertRaises(ResourceLimitError):
            prepare_paper_images(
                [oversized_final],  # type: ignore[list-item]
                PaperImageLayout(3_000),
            )
        oversized_final.resize.assert_not_called()
        oversized_final.convert.assert_not_called()
        self.assertGreater(3_000 * MAX_DIMENSION, MAX_RENDER_PIXELS)

        oversized_normalized = _SizeOnlyImage(1, MAX_DIMENSION)
        with (
            patch.object(
                paper_layout_module.Image,
                "new",
                side_effect=AssertionError("unexpected normalized allocation"),
            ) as image_new,
            self.assertRaises(ResourceLimitError),
        ):
            prepare_paper_images(
                [oversized_normalized],  # type: ignore[list-item]
                PaperImageLayout(3_000, 1),
            )
        image_new.assert_not_called()
        oversized_normalized.transpose.assert_not_called()
        oversized_normalized.convert.assert_not_called()
        oversized_normalized.resize.assert_not_called()
        self.assertLess(3_000 * 1, MAX_RENDER_PIXELS)
        self.assertGreater(3_000 * MAX_DIMENSION, MAX_RENDER_PIXELS)

    def test_partial_outputs_and_intermediates_close_after_transform_error(
        self,
    ) -> None:
        sources = [Image.new("RGB", (3, 2), "black")]
        canvases: list[Image.Image] = []
        converted_images: list[Image.Image] = []
        cropped_images: list[Image.Image] = []
        real_new = Image.new
        real_convert = Image.Image.convert
        real_crop = Image.Image.crop
        real_paste = Image.Image.paste
        paste_calls = 0

        def record_canvas(*args: object, **kwargs: object) -> Image.Image:
            canvas = real_new(*args, **kwargs)  # type: ignore[arg-type]
            canvases.append(canvas)
            return canvas

        def record_convert(
            image: Image.Image, *args: object, **kwargs: object
        ) -> Image.Image:
            converted = real_convert(image, *args, **kwargs)  # type: ignore[arg-type]
            converted_images.append(converted)
            return converted

        def record_crop(
            image: Image.Image, *args: object, **kwargs: object
        ) -> Image.Image:
            cropped = real_crop(image, *args, **kwargs)  # type: ignore[arg-type]
            cropped_images.append(cropped)
            return cropped

        def fail_on_second_paste(
            image: Image.Image,
            content: Image.Image,
            box: tuple[int, int] | None = None,
            mask: Image.Image | None = None,
        ) -> None:
            nonlocal paste_calls
            paste_calls += 1
            if paste_calls == 2:
                raise RuntimeError("injected paste failure")
            real_paste(image, content, box, mask)

        try:
            with (
                patch.object(paper_layout_module.Image, "new", new=record_canvas),
                patch.object(Image.Image, "convert", new=record_convert),
                patch.object(Image.Image, "crop", new=record_crop),
                patch.object(Image.Image, "paste", new=fail_on_second_paste),
                self.assertRaisesRegex(RuntimeError, "injected paste failure"),
            ):
                prepare_paper_images(
                    sources,
                    PaperImageLayout(2),
                    split_mode=True,
                )

            self.assertEqual(len(canvases), 2)
            self.assertEqual(len(converted_images), 1)
            self.assertEqual(len(cropped_images), 2)
            for image in [*canvases, *converted_images, *cropped_images]:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))
            self.assertEqual(
                [source.getpixel((0, 0)) for source in sources],
                [(0, 0, 0)],
            )
        finally:
            for source in sources:
                source.close()

    def test_outputs_are_independent_of_source_images(self) -> None:
        source = Image.new("RGB", (2, 2), (11, 22, 33))
        output = prepare_paper_images([source], PaperImageLayout(2))[0]
        self.assertIsNot(output, source)
        output.putpixel((0, 0), (200, 201, 202))
        output.close()
        self.assertEqual(source.getpixel((0, 0)), (11, 22, 33))
        source.close()

    def test_planned_and_prepared_dimensions_match_odd_geometry(self) -> None:
        cases = (
            ((7, 5), PaperImageLayout(4), False),
            ((3, 4), PaperImageLayout(6, 7), False),
            ((7, 5), PaperImageLayout(4, 3, 90), True),
            ((5, 3), PaperImageLayout(4, 2, 270), True),
            ((5, 7), PaperImageLayout(6, 8, 180), False),
        )
        for size, layout, split_mode in cases:
            with self.subTest(size=size, layout=layout, split_mode=split_mode):
                source = Image.new("RGB", size, (1, 2, 3))
                planned = plan_image_layout([source], layout, split_mode=split_mode)
                outputs = prepare_paper_images([source], layout, split_mode=split_mode)
                try:
                    self.assertEqual(tuple(output.size for output in outputs), planned)
                finally:
                    for output in outputs:
                        output.close()
                    source.close()


if __name__ == "__main__":
    unittest.main()
