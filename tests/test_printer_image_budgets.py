from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

import catlabel.vendors.generic.client as generic_client_module
import catlabel.vendors.niimbot.client as niimbot_client_module
import catlabel.vendors.phomemo.client as phomemo_client_module
from catlabel.core.resource_limits import (
    MAX_PRINT_JOBS,
    MAX_RENDER_PIXELS,
    ResourceLimitError,
)
from catlabel.rendering.paper_layout import plan_image_layout
from catlabel.vendors.generic.client import GenericClient
from catlabel.vendors.niimbot.client import NiimbotClient
from catlabel.vendors.phomemo.client import PhomemoClient


class _SizeOnlyImage:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.copy = Mock(side_effect=AssertionError("unexpected image copy"))
        self.crop = Mock(side_effect=AssertionError("unexpected image crop"))
        self.resize = Mock(side_effect=AssertionError("unexpected image resize"))


def _image(width: int, height: int) -> tuple[Image.Image, _SizeOnlyImage]:
    image = _SizeOnlyImage(width, height)
    return cast(Image.Image, image), image


def _generic_client(
    default_width: int,
    alternate_width: int | None = None,
    paper_mode: str | None = None,
) -> tuple[GenericClient, AsyncMock]:
    default_paper = SimpleNamespace(
        key="default",
        label="Default",
        paper_width_px=default_width,
        render_width_px=default_width,
        left_padding_px=0,
        paper_mode="default",
        max_height_px=None,
        render_height_px=None,
        rotation_degrees=0,
    )
    papers = [default_paper]
    if alternate_width is not None:
        papers.append(
            SimpleNamespace(
                key="alternate",
                label="Alternate",
                paper_width_px=alternate_width,
                render_width_px=alternate_width,
                left_padding_px=0,
                paper_mode="alternate",
                max_height_px=None,
                render_height_px=None,
                rotation_degrees=0,
            )
        )
    model = SimpleNamespace(
        paper_presets=tuple(papers),
        paper_preset=lambda: default_paper,
        image_pipeline=SimpleNamespace(),
    )
    device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", model=model)
    profile = SimpleNamespace(paper_mode=paper_mode)
    settings = SimpleNamespace(speed=0, energy=0, feed_lines=0)
    client = GenericClient(device, {}, profile, settings)
    backend_write = AsyncMock()
    client.backend.write = backend_write
    return client, backend_write


def _phomemo_client(hardware_info: dict[str, object]) -> PhomemoClient:
    return PhomemoClient(
        SimpleNamespace(address="AA:BB:CC:DD:EE:FF"),
        hardware_info,
        SimpleNamespace(energy=None, feed_lines=None),
        SimpleNamespace(energy=0, feed_lines=None),
    )


def _niimbot_client(hardware_info: dict[str, object]) -> NiimbotClient:
    return NiimbotClient(
        SimpleNamespace(address="AA:BB:CC:DD:EE:FF"),
        hardware_info,
        SimpleNamespace(energy=3),
        None,
    )


class PrinterImageBudgetTests(unittest.IsolatedAsyncioTestCase):
    def test_base_source_count_limit_is_checked_before_driver_geometry(self) -> None:
        client = _phomemo_client({"width_px": 384, "dpi": 203})
        images = [_image(1, 1)[0] for _ in range(MAX_PRINT_JOBS + 1)]

        with self.assertRaises(ResourceLimitError):
            client.validate_images(images)

    def test_base_source_pixel_budget_is_cumulative(self) -> None:
        client = _phomemo_client({"width_px": 384, "dpi": 203})
        images = [_image(5001, 5000)[0], _image(5001, 5000)[0]]

        with self.assertRaises(ResourceLimitError):
            client.validate_images(images)

    def test_generic_uses_selected_paper_for_split_padding_and_scaling(self) -> None:
        client, _backend_write = _generic_client(
            4,
            alternate_width=6,
            paper_mode="alternate",
        )
        selected_paper = client._selected_paper()
        self.assertEqual(selected_paper.render_width_px, 6)

        for width, height, split, expected in (
            (10, 3, True, ((6, 3), (6, 3))),
            (10, 7, False, ((6, 4),)),
            (2, 3, False, ((6, 3),)),
        ):
            with self.subTest(source=(width, height), split=split):
                image, fake = _image(width, height)
                self.assertEqual(client.validate_images([image], split), len(expected))
                self.assertEqual(
                    plan_image_layout(
                        [image], client._paper_image_layout(), split_mode=split
                    ),
                    expected,
                )
                fake.copy.assert_not_called()
                fake.crop.assert_not_called()
                fake.resize.assert_not_called()

    async def test_generic_rejects_split_job_explosion_before_allocating(self) -> None:
        client, backend_write = _generic_client(5)
        images = [_image(20, 1)[0] for _ in range(MAX_PRINT_JOBS)]
        image_new = Mock(side_effect=AssertionError("unexpected padding allocation"))

        with (
            patch.object(generic_client_module.Image, "new", new=image_new),
            self.assertRaises(ResourceLimitError),
        ):
            await client.print_images(images, split_mode=True)

        image_new.assert_not_called()
        backend_write.assert_not_awaited()

    async def test_generic_rejects_aggregate_padded_pixels_before_allocating(
        self,
    ) -> None:
        client, backend_write = _generic_client(2500)
        images = [_image(1, 10_100)[0], _image(1, 10_100)[0]]
        image_new = Mock(side_effect=AssertionError("unexpected padding allocation"))

        self.assertLess(2 * 10_100, MAX_RENDER_PIXELS)
        with (
            patch.object(generic_client_module.Image, "new", new=image_new),
            self.assertRaises(ResourceLimitError),
        ):
            await client.print_images(images)

        image_new.assert_not_called()
        backend_write.assert_not_awaited()

    def test_phomemo_geometry_matches_dpi_rounding_and_split_behavior(self) -> None:
        client = _phomemo_client(
            {"protocol_family": "m_series", "width_px": 120, "dpi": 300}
        )
        image, _fake = _image(100, 100)
        calls: list[tuple[int, int, int]] = []
        validate = phomemo_client_module.validate_image_budget

        def record_budget(width: int, height: int, pixels_so_far: int = 0) -> int:
            calls.append((width, height, pixels_so_far))
            return validate(width, height, pixels_so_far)

        with patch.object(
            phomemo_client_module,
            "validate_image_budget",
            new=record_budget,
        ):
            self.assertEqual(client.validate_images([image]), 1)
        self.assertEqual(calls, [(148, 148, 0), (120, 120, 0)])

        calls.clear()
        with patch.object(
            phomemo_client_module,
            "validate_image_budget",
            new=record_budget,
        ):
            self.assertEqual(client.validate_images([image], split_mode=True), 1)
        self.assertEqual(calls, [(148, 148, 0), (148, 148, 0)])

    async def test_phomemo_rejects_oversized_dpi_intermediate_before_copy(self) -> None:
        client = _phomemo_client(
            {"protocol_family": "m_series", "width_px": 384, "dpi": 300}
        )
        image, fake = _image(5000, 5000)
        send = AsyncMock()

        self.assertEqual(5000 * 5000, MAX_RENDER_PIXELS // 2)
        with (
            patch.object(client, "_send", new=send),
            self.assertRaises(ResourceLimitError),
        ):
            await client.print_images([image])

        fake.copy.assert_not_called()
        send.assert_not_awaited()

    def test_niimbot_geometry_matches_scale_down_and_byte_padding(self) -> None:
        client = _niimbot_client({"width_px": 6})
        image, _fake = _image(10, 7)
        calls: list[tuple[int, int, int]] = []
        validate = niimbot_client_module.validate_image_budget

        def record_budget(width: int, height: int, pixels_so_far: int = 0) -> int:
            calls.append((width, height, pixels_so_far))
            return validate(width, height, pixels_so_far)

        with patch.object(
            niimbot_client_module,
            "validate_image_budget",
            new=record_budget,
        ):
            self.assertEqual(client.validate_images([image]), 1)

        self.assertEqual(calls, [(8, 4, 0)])

    async def test_niimbot_rejects_padded_pixel_overflow_before_raster_or_gatt(
        self,
    ) -> None:
        client = _niimbot_client({"width_px": 9993})
        image, fake = _image(9993, 5001)
        send_command = AsyncMock()
        write_raw = AsyncMock()
        rasterize = Mock(side_effect=AssertionError("unexpected raster allocation"))

        self.assertLess(9993 * 5001, MAX_RENDER_PIXELS)
        with (
            patch.object(client, "send_command", new=send_command),
            patch.object(client, "write_raw", new=write_raw),
            patch.object(niimbot_client_module, "image_to_raster", new=rasterize),
            self.assertRaises(ResourceLimitError),
        ):
            await client.print_images([image])

        fake.copy.assert_not_called()
        rasterize.assert_not_called()
        send_command.assert_not_awaited()
        write_raw.assert_not_awaited()
        self.assertFalse(client._print_active)


if __name__ == "__main__":
    unittest.main()
