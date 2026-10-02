from __future__ import annotations

import unittest

from catlabel.printing import build_raster_job
from catlabel.printing.paper import apply_paper_layout_to_raster_set
from catlabel.protocol.types import PaperMode
from catlabel.raster import PixelFormat, RasterBuffer, RasterSet
from catlabel.vendors.generic.models import PrinterModelRegistry


class PrintingPaperTests(unittest.TestCase):
    def test_centers_render_width_inside_wider_paper_width(self) -> None:
        source = RasterSet.from_single(
            RasterBuffer(
                pixels=[1] * 90,
                width=90,
                pixel_format=PixelFormat.BW1,
            )
        )

        result = apply_paper_layout_to_raster_set(
            source,
            paper_width_pixels=96,
        ).require(PixelFormat.BW1)

        self.assertEqual(result.width, 96)
        self.assertEqual(list(result.pixels[:3]), [0, 0, 0])
        self.assertEqual(list(result.pixels[-3:]), [0, 0, 0])

    def test_explicit_left_padding_remains_protocol_owned(self) -> None:
        source = RasterSet.from_single(
            RasterBuffer(
                pixels=[1] * 90,
                width=90,
                pixel_format=PixelFormat.BW1,
            )
        )

        result = apply_paper_layout_to_raster_set(
            source,
            paper_width_pixels=96,
            left_padding_pixels=6,
        )

        self.assertIs(result, source)

    def test_all_catalog_paper_layouts_are_byte_aligned_when_required(self) -> None:
        registry = PrinterModelRegistry.load()
        failures: list[str] = []
        for model in registry.models:
            for preset in model.paper_presets:
                raster = RasterSet.from_single(
                    RasterBuffer(
                        pixels=[0] * preset.render_width_px,
                        width=preset.render_width_px,
                        pixel_format=model.image_pipeline.default_format,
                    )
                )
                laid_out = apply_paper_layout_to_raster_set(
                    raster,
                    paper_width_pixels=preset.paper_width_px,
                    left_padding_pixels=preset.left_padding_px,
                )
                # S001 applies six leading dots and pads to its 96-dot head
                # in the encoder. Its image-space paper width is deliberately 90.
                if model.protocol_family.value == "yk_astra_p1":
                    continue
                # Luck packs each row with ceil(width / 8) bytes. Its physical
                # presets deliberately preserve non-byte-aligned dot widths.
                if model.protocol_family.value in {"luck_normal", "luck_normal_a4"}:
                    continue
                effective_width = laid_out.width + preset.left_padding_px
                if (
                    model.protocol_family.value != "legacy"
                    or model.protocol_variant not in {"esc_star", "esc_star_eight"}
                ) and effective_width % 8:
                    failures.append(
                        f"{model.model_no}/{preset.key}: {effective_width}px"
                    )
        self.assertEqual(failures, [])

    def test_90_pixel_tiny_catalog_model_builds_after_layout(self) -> None:
        model = PrinterModelRegistry.load().get("label_printer")
        self.assertIsNotNone(model)
        if model is None:
            self.fail("label_printer profile should exist")
        preset = model.paper_preset()
        raster = RasterSet.from_single(
            RasterBuffer(
                pixels=[0] * preset.render_width_px,
                width=preset.render_width_px,
                pixel_format=model.image_pipeline.default_format,
            )
        )

        job = build_raster_job(
            model=model,
            raster_set=raster,
            image_pipeline=model.image_pipeline,
            is_text=False,
            speed=model.img_print_speed,
            energy=model.moderation_energy,
            density=None,
            blackening=3,
            feed_padding=0,
            paper_mode=(
                PaperMode(preset.paper_mode) if preset.paper_mode is not None else None
            ),
            paper_width_pixels=preset.paper_width_px,
            left_padding_pixels=preset.left_padding_px,
        )

        self.assertTrue(job.payload)


if __name__ == "__main__":
    unittest.main()
