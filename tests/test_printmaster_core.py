from __future__ import annotations

import unittest
from unittest.mock import patch

from catlabel.core.resource_limits import (
    ResourceLimitError,
)
from catlabel.protocol.families import (
    printmaster_core,
)
from catlabel.protocol.families.printmaster_core import (
    build_printmaster_page,
)
from catlabel.raster import (
    PixelFormat,
    RasterBuffer,
)


class PrintMasterCoreTests(unittest.TestCase):
    def test_m110_and_m120_match_literal_setup_order_and_raster_header(self) -> None:
        raster = RasterBuffer([0] * 384, 384, PixelFormat.BW1)
        expected_prefix = bytes.fromhex("1f1102031f1123021b40")
        gs_v0 = bytes.fromhex("1d76300030000100") + bytes(48)

        m110 = build_printmaster_page(
            raster,
            variant="printmaster_m110",
            density=3,
            speed=2,
        )
        m120 = build_printmaster_page(
            raster,
            variant="printmaster_m120",
            density=3,
            speed=2,
        )

        self.assertEqual(m110, expected_prefix + gs_v0)
        self.assertEqual(m120, expected_prefix + bytes.fromhex("1f112101") + gs_v0)
        self.assertNotIn(b"\x1b\x64", m110)
        self.assertNotIn(b"\x1b\x4a", m110)
        self.assertNotIn(b"\x1b\x61", m110)
        self.assertEqual(raster.pixels, [0] * 384)

    def test_density_omission_clamping_and_speed_zero(self) -> None:
        raster = RasterBuffer([1] * 384, 384, PixelFormat.BW1)

        defaults = build_printmaster_page(raster, variant="printmaster_m110")
        omitted = build_printmaster_page(
            raster,
            variant="printmaster_m110",
            density=0,
        )
        clamped = build_printmaster_page(
            raster,
            variant="printmaster_m110",
            density=-3,
            speed=300,
        )
        explicit_zero_speed = build_printmaster_page(
            raster,
            variant="printmaster_m110",
            speed=0,
        )

        self.assertTrue(defaults.startswith(b"\x1b\x40"))
        self.assertEqual(omitted, defaults)
        self.assertEqual(defaults[-48:], bytes((0xFF,)) * 48)
        self.assertTrue(clamped.startswith(bytes.fromhex("1f1102011f1123ff1b40")))
        self.assertTrue(explicit_zero_speed.startswith(bytes.fromhex("1f1123001b40")))

    def test_width_format_empty_and_unsupported_variant_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported Print Master"):
            _ = build_printmaster_page(
                RasterBuffer([0] * 384, 384),
                variant="m110",
            )
        with self.assertRaisesRegex(ValueError, "384px width"):
            _ = build_printmaster_page(
                RasterBuffer([0] * 383, 383),
                variant="printmaster_m110",
            )
        with self.assertRaisesRegex(ValueError, "BW1 raster"):
            _ = build_printmaster_page(
                RasterBuffer([0] * 384, 384, PixelFormat.GRAY8),
                variant="printmaster_m110",
            )
        with self.assertRaisesRegex(ValueError, "height must be positive"):
            _ = build_printmaster_page(
                RasterBuffer([], 384),
                variant="printmaster_m110",
            )
        with self.assertRaisesRegex(ValueError, "complete rows"):
            _ = build_printmaster_page(
                RasterBuffer([0] * 385, 384),
                variant="printmaster_m110",
            )

    def test_resource_budget_rejects_before_reading_or_packing_pixels(self) -> None:
        raster = RasterBuffer(range(384 * 20_001), 384)
        with (
            patch.object(
                printmaster_core,
                "build_gs_v0_blocks",
            ) as build_blocks,
            self.assertRaises(ResourceLimitError),
        ):
            _ = build_printmaster_page(raster, variant="printmaster_m110")
        build_blocks.assert_not_called()

    def test_blocks_split_at_configured_limit_and_use_48_byte_rows(self) -> None:
        raster = RasterBuffer([0] * (384 * 3), 384)
        self.assertEqual(
            build_printmaster_page(raster, variant="printmaster_m110")[:2],
            b"\x1b\x40",
        )
        # Keep the test allocation small while exercising a split across blocks.
        with patch.object(printmaster_core, "_MAX_LINES_PER_BLOCK", 2):
            payload = build_printmaster_page(raster, variant="printmaster_m110")

        first_block = bytes.fromhex("1d76300030000200") + bytes(96)
        second_block = bytes.fromhex("1d76300030000100") + bytes(48)
        self.assertEqual(payload, bytes.fromhex("1b40") + first_block + second_block)


if __name__ == "__main__":
    _ = unittest.main()
