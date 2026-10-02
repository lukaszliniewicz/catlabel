from __future__ import annotations

import unittest
from types import SimpleNamespace

from catlabel.printing import build_raster_job
from catlabel.protocol import PageFlow, PrinterProtocol, ProtocolFamily
from catlabel.protocol.families import PrintJobRequest, get_protocol_behavior
from catlabel.protocol.types import ImageEncoding, PaperMode
from catlabel.raster import PixelFormat, RasterBuffer, RasterSet


class ReleasedElephAndToPrintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pixels = [1, 0, 0, 0, 0, 0, 0, 0]

    def build_job(
        self,
        family: ProtocolFamily,
        *,
        variant: str | None,
        paper_mode: PaperMode | None = PaperMode.TAG,
        page_flow: PageFlow = PageFlow.PAGED,
        page_index: int = 1,
        page_count: int = 1,
        pixels: list[int] | None = None,
        width: int = 8,
    ):
        behavior = get_protocol_behavior(family)
        model = SimpleNamespace(
            a4xii=False,
            dev_dpi=203,
            can_print_label=False,
            post_print_feed_count=0,
            one_length=0,
        )
        raster = RasterBuffer(
            self.pixels if pixels is None else pixels,
            width=width,
            pixel_format=PixelFormat.BW1,
        )
        return build_raster_job(
            model=model,
            raster_set=RasterSet.from_single(raster),
            image_pipeline=behavior.default_image_pipeline,
            is_text=False,
            speed=4,
            energy=5,
            density=9,
            blackening=3,
            feed_padding=0,
            paper_mode=paper_mode,
            protocol_family=family,
            protocol_variant=variant,
            page_index=page_index,
            page_count=page_count,
            page_flow=page_flow,
        )

    def test_eleph_p1_matches_released_commands_and_inverts_bitmap(self) -> None:
        pixels = self.pixels + [0] * 56
        job = self.build_job(
            ProtocolFamily.ELEPH_TSPL,
            variant="p1",
            pixels=pixels,
            width=8,
        )

        expected = (
            b"SIZE 1 mm,1 mm\r\n"
            b"GAP 2 mm,0 mm\r\n"
            b"DIRECTION 0\r\n"
            b"CLS\r\n"
            b"BITMAP 0,0,1,8,0,\x7f\xff\xff\xff\xff\xff\xff\xff\r\n"
            b"PRINT 1,1\r\n"
        )
        self.assertEqual(job.payload, expected)
        self.assertNotIn(b"\x10\xff\x10\x03", job.payload)
        for command in (b"SET RIBBON", b"DENSITY", b"REFERENCE", b"SPEED"):
            self.assertNotIn(command, job.payload)

    def test_toprint_p1_preserves_three_media_recipes_and_raw_bitmap(self) -> None:
        cases = (
            (
                PaperMode.TAG,
                b"\x10\xff\x10\x03\x02",
                b"SIZE 1 mm,0.13 mm\r\n",
                b"GAP 3 mm,0 mm\r\n",
                b"SPEED 4\r\n",
            ),
            (
                PaperMode.PLAIN,
                b"\x10\xff\x10\x03\x01",
                b"SIZE 1 mm,5.13 mm\r\n",
                b"GAP 0 mm,0 mm\r\n",
                b"",
            ),
            (
                PaperMode.BLACK_TAG,
                b"\x10\xff\x10\x03\x03",
                b"SIZE 1 mm,0.13 mm\r\n",
                b"BLINE 3 mm,0 mm\r\n",
                b"",
            ),
        )
        for mode, media, size, sensor, speed in cases:
            with self.subTest(mode=mode):
                job = self.build_job(
                    ProtocolFamily.TOPRINT_TSPL,
                    variant="p1",
                    paper_mode=mode,
                )
                self.assertEqual(
                    job.payload,
                    media
                    + size
                    + b"DIRECTION 0,0\r\n"
                    + sensor
                    + b"SET RIBBON OFF\r\n"
                    + b"DENSITY 9\r\n"
                    + b"REFERENCE 0,0\r\n"
                    + speed
                    + b"CLS\r\n"
                    + b"BITMAP 0,0,1,1,0,\x80\r\n"
                    + b"PRINT 1,1\r\n",
                )

    def test_page_flow_controls_tspl_height_and_hprt_position(self) -> None:
        paged_intermediate = self.build_job(
            ProtocolFamily.TOPRINT_TSPL,
            variant="p1",
            paper_mode=PaperMode.PLAIN,
            page_index=1,
            page_count=2,
        )
        continuous_intermediate = self.build_job(
            ProtocolFamily.TOPRINT_TSPL,
            variant="p1",
            paper_mode=PaperMode.PLAIN,
            page_flow=PageFlow.CONTINUOUS,
            page_index=1,
            page_count=2,
        )
        continuous_final = self.build_job(
            ProtocolFamily.TOPRINT_TSPL,
            variant="p1",
            paper_mode=PaperMode.PLAIN,
            page_flow=PageFlow.CONTINUOUS,
            page_index=2,
            page_count=2,
        )
        self.assertIn(b"SIZE 1 mm,5.13 mm\r\n", paged_intermediate.payload)
        self.assertIn(b"SIZE 1 mm,0.13 mm\r\n", continuous_intermediate.payload)
        self.assertIn(b"SIZE 1 mm,5.13 mm\r\n", continuous_final.payload)

        paged_hprt = self.build_job(
            ProtocolFamily.TOPRINT_HPRT_ESC,
            variant="zl1",
            page_index=1,
            page_count=2,
        )
        continuous_hprt = self.build_job(
            ProtocolFamily.TOPRINT_HPRT_ESC,
            variant="zl1",
            page_flow=PageFlow.CONTINUOUS,
            page_index=1,
            page_count=2,
        )
        final_hprt = self.build_job(
            ProtocolFamily.TOPRINT_HPRT_ESC,
            variant="zl1",
            page_flow=PageFlow.CONTINUOUS,
            page_index=2,
            page_count=2,
        )
        position = b"\x1d\x0c"
        self.assertIn(position, paged_hprt.payload)
        self.assertNotIn(position, continuous_hprt.payload)
        self.assertIn(position, final_hprt.payload)

    def test_public_printer_protocol_threads_continuous_page_flow(self) -> None:
        behavior = get_protocol_behavior(ProtocolFamily.TOPRINT_TSPL)

        class Profile:
            dev_dpi = 203
            can_print_label = False
            post_print_feed_count = 0
            one_length = 0
            a4xii = False
            default_protocol_family = ProtocolFamily.TOPRINT_TSPL

            @staticmethod
            def select_speed(*, is_text: bool) -> int:
                _ = is_text
                return 4

            @staticmethod
            def select_energy(*, is_text: bool, blackening: int) -> int:
                _ = is_text, blackening
                return 5

            @staticmethod
            def select_density(*, is_text: bool, blackening: int) -> int:
                _ = is_text, blackening
                return 9

        device = SimpleNamespace(
            profile=Profile(),
            protocol_family=ProtocolFamily.TOPRINT_TSPL,
            protocol_variant="p1",
            image_pipeline=behavior.default_image_pipeline,
        )
        raster = RasterBuffer(
            self.pixels,
            width=8,
            pixel_format=PixelFormat.BW1,
        )
        job = PrinterProtocol(device).build_job(
            RasterSet.from_single(raster),
            is_text=False,
            paper_mode=PaperMode.PLAIN,
            page_index=1,
            page_count=2,
            page_flow=PageFlow.CONTINUOUS,
        )
        self.assertIn(b"SIZE 1 mm,0.13 mm\r\n", job.payload)
        self.assertNotIn(b"SIZE 1 mm,5.13 mm\r\n", job.payload)

    def test_page_flow_marks_physical_page_boundaries(self) -> None:
        raster_set = RasterSet.from_single(
            RasterBuffer(self.pixels, width=8, pixel_format=PixelFormat.BW1)
        )
        pipeline = get_protocol_behavior(
            ProtocolFamily.TOPRINT_TSPL
        ).default_image_pipeline
        request = PrintJobRequest(
            raster_set=raster_set,
            image_pipeline=pipeline,
            is_text=False,
            speed=4,
            energy=5,
            blackening=3,
            lsb_first=False,
            protocol_family=ProtocolFamily.TOPRINT_TSPL,
            protocol_variant="p1",
            feed_padding=0,
            dev_dpi=203,
            page_index=2,
            page_count=3,
            page_flow=PageFlow.CONTINUOUS,
        )
        self.assertIs(request.page_flow, PageFlow.CONTINUOUS)
        self.assertFalse(request.starts_media_page)
        self.assertFalse(request.ends_media_page)
        first = PrintJobRequest(
            raster_set=raster_set,
            image_pipeline=pipeline,
            is_text=False,
            speed=4,
            energy=5,
            blackening=3,
            lsb_first=False,
            protocol_family=ProtocolFamily.TOPRINT_TSPL,
            protocol_variant="p1",
            feed_padding=0,
            dev_dpi=203,
            page_index=1,
            page_count=3,
            page_flow=PageFlow.CONTINUOUS,
        )
        last = PrintJobRequest(
            raster_set=raster_set,
            image_pipeline=pipeline,
            is_text=False,
            speed=4,
            energy=5,
            blackening=3,
            lsb_first=False,
            protocol_family=ProtocolFamily.TOPRINT_TSPL,
            protocol_variant="p1",
            feed_padding=0,
            dev_dpi=203,
            page_index=3,
            page_count=3,
            page_flow=PageFlow.CONTINUOUS,
        )
        self.assertTrue(first.starts_media_page)
        self.assertFalse(first.ends_media_page)
        self.assertFalse(last.starts_media_page)
        self.assertTrue(last.ends_media_page)

    def test_new_families_use_distinct_encodings_and_reject_invalid_inputs(
        self,
    ) -> None:
        self.assertIs(
            get_protocol_behavior(
                ProtocolFamily.TOPRINT_TSPL
            ).default_image_pipeline.encoding,
            ImageEncoding.TOPRINT_TSPL_BITMAP,
        )
        self.assertIs(
            get_protocol_behavior(
                ProtocolFamily.TOPRINT_HPRT_ESC
            ).default_image_pipeline.encoding,
            ImageEncoding.TOPRINT_HPRT_ESC_RASTER,
        )
        self.assertEqual(str(PageFlow.PAGED), "PageFlow.PAGED")
        self.assertEqual(f"{PageFlow.CONTINUOUS}", "PageFlow.CONTINUOUS")

        with self.assertRaisesRegex(ValueError, "Unsupported Eleph-label TSPL"):
            self.build_job(
                ProtocolFamily.ELEPH_TSPL,
                variant="unknown",
            )
        with self.assertRaisesRegex(ValueError, "does not support paper mode"):
            self.build_job(
                ProtocolFamily.TOPRINT_TSPL,
                variant="p1",
                paper_mode=PaperMode.CIRCLE_TAG,
            )
        with self.assertRaisesRegex(ValueError, "divisible by 8"):
            self.build_job(
                ProtocolFamily.TOPRINT_TSPL,
                variant="p1",
                pixels=self.pixels + [0],
                width=9,
            )


if __name__ == "__main__":
    unittest.main()
