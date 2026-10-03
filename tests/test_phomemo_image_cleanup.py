from __future__ import annotations

import asyncio
import unittest
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageOps

from catlabel.protocol.encoding import pack_line
from catlabel.raster import PixelFormat
from catlabel.rendering.renderer import image_to_raster
from catlabel.vendors.phomemo.client import PhomemoClient


@contextmanager
def _track_image_outputs(
    *operation_names: str,
    skip_l_mode_converts: bool = False,
) -> Iterator[tuple[list[tuple[str, Image.Image]], list[Image.Image]]]:
    created: list[tuple[str, Image.Image]] = []
    closed: list[Image.Image] = []

    with ExitStack() as patches:
        for operation_name in operation_names:
            original_operation = getattr(Image.Image, operation_name)

            def track_output(
                image: Image.Image,
                *args: object,
                _operation_name: str = operation_name,
                _original_operation=original_operation,
                **kwargs: object,
            ) -> Image.Image:
                output = _original_operation(image, *args, **kwargs)
                if (
                    skip_l_mode_converts
                    and _operation_name == "convert"
                    and image.mode == "L"
                ):
                    return output
                created.append((_operation_name, output))
                return output

            patches.enter_context(
                patch.object(Image.Image, operation_name, new=track_output)
            )

        original_close = Image.Image.close

        def track_close(image: Image.Image) -> None:
            closed.append(image)
            original_close(image)

        patches.enter_context(patch.object(Image.Image, "close", new=track_close))
        yield created, closed


def _previous_raster_output(
    image: Image.Image,
    *,
    rotate_cw: bool,
    invert: bool,
    dither: bool,
) -> tuple[bytes, int, int]:
    owned_images: list[Image.Image] = []
    try:
        if rotate_cw:
            image = image.rotate(-90, expand=True)
            owned_images.append(image)
        if invert:
            grayscale_image = image.convert("L")
            owned_images.append(grayscale_image)
            image = ImageOps.invert(grayscale_image)
            owned_images.append(image)

        raster = image_to_raster(image, PixelFormat.BW1, dither=dither)
        width_bytes = (raster.width + 7) // 8
        packed_rows = [
            pack_line(
                list(raster.pixels[row * raster.width : (row + 1) * raster.width]),
                lsb_first=False,
            )
            for row in range(raster.height)
        ]
        return b"".join(packed_rows), width_bytes, raster.height
    finally:
        for owned_image in reversed(owned_images):
            owned_image.close()


def _legacy_client() -> PhomemoClient:
    return PhomemoClient(
        SimpleNamespace(address="test-device"),
        {"protocol_family": "legacy", "width_px": 8, "dpi": 406},
        SimpleNamespace(paper_mode=None, energy=None, feed_lines=None),
        SimpleNamespace(energy=0, feed_lines=None),
    )


class PhomemoLegacyImageCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_always_closes_owned_images_and_keeps_source_open(
        self,
    ) -> None:
        for outcome in ("success", "error", "cancel"):
            with self.subTest(outcome=outcome):
                source = Image.new("L", (6, 2), 127)
                client = _legacy_client()
                dispatched_images: list[Image.Image] = []

                async def dispatch(
                    image: Image.Image,
                    *args,
                    _outcome: str = outcome,
                    _dispatched_images: list[Image.Image] = dispatched_images,
                    **kwargs,
                ) -> None:
                    _dispatched_images.append(image)
                    self.assertEqual(image.size, (8, 3))
                    image.load()
                    if _outcome == "error":
                        raise RuntimeError("dispatch failed")
                    if _outcome == "cancel":
                        raise asyncio.CancelledError

                with (
                    _track_image_outputs("copy", "resize") as (created, closed),
                    patch.object(client, "_print_m_series", new=dispatch),
                ):
                    if outcome == "error":
                        with self.assertRaisesRegex(RuntimeError, "dispatch failed"):
                            await client.print_images([source])
                    elif outcome == "cancel":
                        with self.assertRaises(asyncio.CancelledError):
                            await client.print_images([source])
                    else:
                        await client.print_images([source])

                self.assertEqual(
                    [(name, image.size) for name, image in created],
                    [("copy", (6, 2)), ("resize", (12, 4)), ("resize", (8, 3))],
                )
                self.assertEqual(len(dispatched_images), 1)
                self.assertIs(dispatched_images[0], created[-1][1])
                self.assertCountEqual(
                    [id(image) for _, image in created],
                    [id(image) for image in closed],
                )
                self.assertEqual(len(closed), len(created))
                self.assertNotIn(id(source), [id(image) for image in closed])
                self.assertEqual(source.getpixel((0, 0)), 127)
                source.close()


class PhomemoRasterImageCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = object.__new__(PhomemoClient)

    @staticmethod
    def _source() -> Image.Image:
        image = Image.new("RGB", (5, 3))
        image.putdata(
            [
                ((index * 31) % 256, (index * 67) % 256, (index * 109) % 256)
                for index in range(15)
            ]
        )
        return image

    @staticmethod
    def _tracked_invert(created: list[tuple[str, Image.Image]]):
        original_invert = ImageOps.invert

        def invert(image: Image.Image) -> Image.Image:
            output = original_invert(image)
            created.append(("invert", output))
            return output

        return invert

    def _assert_temporaries_closed(
        self,
        source: Image.Image,
        created: list[tuple[str, Image.Image]],
        closed: list[Image.Image],
    ) -> None:
        self.assertEqual([name for name, _ in created], ["rotate", "convert", "invert"])
        self.assertCountEqual(
            [id(image) for _, image in created],
            [id(image) for image in closed],
        )
        self.assertEqual(len(closed), len(created))
        self.assertNotIn(id(source), [id(image) for image in closed])
        self.assertEqual(source.getpixel((0, 0)), (0, 0, 0))

    def test_rotated_inverted_odd_width_output_matches_previous_helper(self) -> None:
        source = self._source()
        expected = _previous_raster_output(
            source,
            rotate_cw=True,
            invert=True,
            dither=False,
        )
        self.assertEqual(expected[1:], (1, 5))

        with (
            _track_image_outputs(
                "rotate",
                "convert",
                skip_l_mode_converts=True,
            ) as (created, closed),
            patch.object(
                ImageOps,
                "invert",
                new=self._tracked_invert(created),
            ),
        ):
            actual = self.client._render_to_raster(
                source,
                rotate_cw=True,
                invert=True,
                dither=False,
            )

        self.assertEqual(actual, expected)
        self._assert_temporaries_closed(source, created, closed)
        source.close()

    def test_rasterization_error_closes_rotation_and_inversion_temporaries(
        self,
    ) -> None:
        source = self._source()
        with (
            _track_image_outputs(
                "rotate",
                "convert",
                skip_l_mode_converts=True,
            ) as (created, closed),
            patch.object(
                ImageOps,
                "invert",
                new=self._tracked_invert(created),
            ),
            patch(
                "catlabel.vendors.phomemo.client.image_to_raster",
                side_effect=RuntimeError("rasterization failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "rasterization failed"),
        ):
            self.client._render_to_raster(
                source,
                rotate_cw=True,
                invert=True,
                dither=False,
            )

        self._assert_temporaries_closed(source, created, closed)
        source.close()


if __name__ == "__main__":
    unittest.main()
