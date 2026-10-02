from __future__ import annotations

import unittest
from types import SimpleNamespace

from catlabel.printing import build_raster_job
from catlabel.protocol import (
    ImageEncoding,
    PrinterProtocol,
    ProtocolFamily,
    ProtocolJob,
)
from catlabel.protocol.families import PrintJobRequest, get_protocol_behavior
from catlabel.protocol.families.yk_common import iter_yk_frames
from catlabel.protocol.plan import ProtocolPlan
from catlabel.protocol.types import ImagePipelineConfig, PaperMode
from catlabel.raster import PixelFormat, RasterBuffer, RasterSet
from catlabel.vendors.generic.manifest import GenericManifest

_SPEED_FRAME = bytes.fromhex("64 0a 00 01 00 04 00 00 00 00 9b")
_DENSITY_FRAME = bytes.fromhex("64 09 01 01 00 09 00 00 00 00 9b")
_RASTER_FRAME_SEQUENCE_4 = bytes.fromhex(
    "64 00 04 0c 00 02 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 9b"
)
_RASTER_FRAME_SEQUENCE_5 = bytes.fromhex(
    "64 00 05 0c 00 02 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 9b"
)

_S001_TAG_ONE_DOT = (
    _SPEED_FRAME
    + _DENSITY_FRAME
    + bytes.fromhex("64 28 02 02 00 01 01 00 00 00 00 9b")
    + bytes.fromhex("64 03 03 03 00 02 20 03 00 00 00 00 9b")
    + bytes.fromhex("64 02 04 02 00 02 00 00 00 00 00 9b")
    + _RASTER_FRAME_SEQUENCE_5
    + bytes.fromhex("64 03 06 03 00 01 20 03 00 00 00 00 9b")
)
_S001_PLAIN_ONE_DOT = (
    _SPEED_FRAME
    + _DENSITY_FRAME
    + bytes.fromhex("64 28 02 02 00 01 00 00 00 00 00 9b")
    + bytes.fromhex("64 04 03 02 00 0c 00 00 00 00 00 9b")
    + _RASTER_FRAME_SEQUENCE_4
    + bytes.fromhex("64 02 05 02 00 34 00 00 00 00 00 9b")
    + bytes.fromhex("64 02 06 02 00 0c 00 00 00 00 00 9b")
)
_S001_BLACK_TAG_ONE_DOT = (
    _SPEED_FRAME
    + _DENSITY_FRAME
    + bytes.fromhex("64 28 02 02 00 01 02 00 00 00 00 9b")
    + bytes.fromhex("64 03 03 03 00 02 20 03 00 00 00 00 9b")
    + bytes.fromhex("64 02 04 02 00 02 00 00 00 00 00 9b")
    + _RASTER_FRAME_SEQUENCE_5
    + bytes.fromhex("64 03 06 03 00 01 20 03 00 00 00 00 9b")
)


class S001EncoderTests(unittest.TestCase):
    def test_capabilities_expose_density_and_speed_without_energy_or_manual_feed(
        self,
    ) -> None:
        caps = GenericManifest()._build_capabilities(
            {
                "protocol_family": "yk_astra_p1",
                "default_speed": 25,
                "max_speed": 25,
                "min_density": 5,
                "max_density": 13,
                "default_density": 9,
            }
        )
        self.assertEqual(
            caps["density"],
            {
                "available": True,
                "min": 5,
                "max": 13,
                "default": 9,
                "allow_auto": False,
                "scale": "level",
            },
        )
        self.assertEqual(caps["speed"]["default"], 25)
        self.assertEqual(caps["speed"]["max"], 25)
        self.assertFalse(caps["energy"]["available"])
        self.assertFalse(caps["feed"]["available"])

    def build_job(
        self,
        *,
        pixels: list[int] | None = None,
        width: int = 1,
        paper_mode: PaperMode | None = PaperMode.TAG,
        page_index: int = 1,
        page_count: int = 1,
        speed: int = 4,
        density: int | None = 9,
        left_padding_pixels: int = 0,
        protocol_variant: str | None = "s001",
        image_pipeline: ImagePipelineConfig | None = None,
        pixel_format: PixelFormat = PixelFormat.BW1,
    ) -> ProtocolJob:
        behavior = get_protocol_behavior(ProtocolFamily.YK_ASTRA_P1)
        raster = RasterBuffer(
            [1] if pixels is None else pixels,
            width=width,
            pixel_format=pixel_format,
        )
        model = SimpleNamespace(
            protocol_family=ProtocolFamily.YK_ASTRA_P1,
            protocol_variant=protocol_variant,
            a4xii=False,
            dev_dpi=203,
            can_print_label=False,
            post_print_feed_count=0,
            one_length=0,
        )
        return build_raster_job(
            model=model,
            raster_set=RasterSet.from_single(raster),
            image_pipeline=(
                behavior.default_image_pipeline
                if image_pipeline is None
                else image_pipeline
            ),
            is_text=False,
            speed=speed,
            energy=0,
            density=density,
            blackening=0,
            feed_padding=0,
            paper_mode=paper_mode,
            page_index=page_index,
            page_count=page_count,
            left_padding_pixels=left_padding_pixels,
            protocol_family=ProtocolFamily.YK_ASTRA_P1,
            protocol_variant=protocol_variant,
        )

    def decoded_frames(self, job: ProtocolJob) -> list[tuple[int, int, bytes]]:
        return [
            (frame.sequence, frame.command, frame.payload)
            for frame in iter_yk_frames(job.payload)
        ]

    def test_literal_one_dot_wire_fixtures_cover_all_media_modes(self) -> None:
        fixtures = (
            (PaperMode.TAG, _S001_TAG_ONE_DOT),
            (PaperMode.PLAIN, _S001_PLAIN_ONE_DOT),
            (PaperMode.BLACK_TAG, _S001_BLACK_TAG_ONE_DOT),
        )
        for paper_mode, expected_wire in fixtures:
            with self.subTest(paper_mode=paper_mode):
                job = self.build_job(paper_mode=paper_mode)
                self.assertEqual(job.payload, expected_wire)
                self.assertEqual(job.steps, ())

    def test_default_mode_is_tag_and_emits_no_interactive_steps(self) -> None:
        behavior = get_protocol_behavior(ProtocolFamily.YK_ASTRA_P1)
        self.assertEqual(behavior.default_image_pipeline.formats, (PixelFormat.BW1,))
        self.assertIs(
            behavior.default_image_pipeline.encoding, ImageEncoding.YK_ASTRA_P1_RAW
        )
        self.assertEqual(behavior.supported_protocol_variants, ("s001",))
        self.assertEqual(
            behavior.supported_paper_modes,
            (PaperMode.PLAIN, PaperMode.TAG, PaperMode.BLACK_TAG),
        )
        job = self.build_job(paper_mode=None)
        self.assertEqual(job.payload, _S001_TAG_ONE_DOT)
        self.assertEqual(job.steps, ())
        raster_set = RasterSet.from_single(RasterBuffer([1], width=1))
        request = PrintJobRequest(
            raster_set=raster_set,
            image_pipeline=behavior.default_image_pipeline,
            is_text=False,
            speed=4,
            energy=0,
            blackening=0,
            lsb_first=False,
            protocol_family=ProtocolFamily.YK_ASTRA_P1,
            protocol_variant="s001",
            feed_padding=0,
            dev_dpi=203,
        )
        builder = behavior.job_builder
        self.assertIsNotNone(builder)
        if builder is None:
            self.fail("S001 behavior must register its stateless job builder")
        plan = builder(request)
        if not isinstance(plan, ProtocolPlan):
            self.fail("S001 encoder must return a stream plan")
        self.assertEqual(plan.payload, _S001_TAG_ONE_DOT)
        self.assertEqual(plan.steps, ())

    def test_page_setup_and_feeds_follow_first_intermediate_and_final_pages(
        self,
    ) -> None:
        plain_first = self.decoded_frames(
            self.build_job(paper_mode=PaperMode.PLAIN, page_index=1, page_count=3)
        )
        plain_middle = self.decoded_frames(
            self.build_job(paper_mode=PaperMode.PLAIN, page_index=2, page_count=3)
        )
        plain_last = self.decoded_frames(
            self.build_job(paper_mode=PaperMode.PLAIN, page_index=3, page_count=3)
        )
        raster_payload = b"\x02" + bytes(11)
        self.assertEqual(
            plain_first,
            [
                (0, 0x0A, b"\x04"),
                (1, 0x09, b"\x09"),
                (2, 0x28, b"\x01\x00"),
                (3, 0x04, b"\x0c\x00"),
                (4, 0x00, raster_payload),
                (5, 0x02, b"\x34\x00"),
            ],
        )
        self.assertEqual(
            plain_middle,
            [(0, 0x00, raster_payload), (1, 0x02, b"\x34\x00")],
        )
        self.assertEqual(
            plain_last,
            [
                (0, 0x00, raster_payload),
                (1, 0x02, b"\x34\x00"),
                (2, 0x02, b"\x0c\x00"),
            ],
        )

        tag_first = self.decoded_frames(
            self.build_job(paper_mode=PaperMode.TAG, page_index=1, page_count=3)
        )
        tag_middle = self.decoded_frames(
            self.build_job(paper_mode=PaperMode.TAG, page_index=2, page_count=3)
        )
        tag_last = self.decoded_frames(
            self.build_job(paper_mode=PaperMode.TAG, page_index=3, page_count=3)
        )
        self.assertEqual(
            tag_first,
            [
                (0, 0x0A, b"\x04"),
                (1, 0x09, b"\x09"),
                (2, 0x28, b"\x01\x01"),
                (3, 0x03, b"\x02\x20\x03"),
                (4, 0x02, b"\x02\x00"),
                (5, 0x00, raster_payload),
                (6, 0x03, b"\x00\x20\x03"),
            ],
        )
        self.assertEqual(
            tag_middle,
            [
                (0, 0x02, b"\x02\x00"),
                (1, 0x00, raster_payload),
                (2, 0x03, b"\x00\x20\x03"),
            ],
        )
        self.assertEqual(
            tag_last,
            [
                (0, 0x02, b"\x02\x00"),
                (1, 0x00, raster_payload),
                (2, 0x03, b"\x01\x20\x03"),
            ],
        )
        black_tag_middle = self.decoded_frames(
            self.build_job(
                paper_mode=PaperMode.BLACK_TAG,
                page_index=2,
                page_count=3,
            )
        )
        black_tag_last = self.decoded_frames(
            self.build_job(
                paper_mode=PaperMode.BLACK_TAG,
                page_index=3,
                page_count=3,
            )
        )
        self.assertEqual(black_tag_middle, tag_middle)
        self.assertEqual(black_tag_last, tag_last)

    def test_raster_frames_group_four_rows_and_keep_a_partial_last_frame(self) -> None:
        job = self.build_job(pixels=[0] * 9, width=1)
        frames = self.decoded_frames(job)
        raster_frames = [payload for _, command, payload in frames if command == 0]
        self.assertEqual([len(payload) for payload in raster_frames], [48, 48, 12])
        self.assertEqual(raster_frames[-1], bytes(12))

    def test_sequence_wraps_modulo_64_for_long_raster_jobs(self) -> None:
        row_count = 4 * 66
        job = self.build_job(pixels=[0] * row_count, width=1)
        frames = list(iter_yk_frames(job.payload))
        self.assertEqual(len(frames), 5 + 66 + 1)
        self.assertEqual(
            [frame.sequence for frame in frames],
            [index % 64 for index in range(len(frames))],
        )

    def test_raster_padding_preserves_msb_order_and_zero_white_bytes(self) -> None:
        default_padding = self.decoded_frames(self.build_job(pixels=[1, 0, 1], width=3))
        default_raster = next(
            payload for _, command, payload in default_padding if command == 0
        )
        self.assertEqual(default_raster, b"\x02\x80" + bytes(10))
        negative_padding = self.decoded_frames(
            self.build_job(pixels=[1, 0, 1], width=3, left_padding_pixels=-2)
        )
        negative_raster = next(
            payload for _, command, payload in negative_padding if command == 0
        )
        self.assertEqual(negative_raster, default_raster)

        additional_padding = self.decoded_frames(
            self.build_job(pixels=[1, 0, 1], width=3, left_padding_pixels=2)
        )
        padded_raster = next(
            payload for _, command, payload in additional_padding if command == 0
        )
        self.assertEqual(padded_raster, b"\x00\xa0" + bytes(10))

        white = self.decoded_frames(self.build_job(pixels=[0] * 90, width=90))
        white_raster = next(payload for _, command, payload in white if command == 0)
        self.assertEqual(white_raster, bytes(12))

    def test_raster_width_and_extra_padding_must_fit_the_96_dot_head(self) -> None:
        exact_width = self.decoded_frames(self.build_job(pixels=[1] * 90, width=90))
        raster = next(payload for _, command, payload in exact_width if command == 0)
        self.assertEqual(len(raster), 12)
        self.assertEqual(raster[-1], 0xFF)

        with self.assertRaisesRegex(ValueError, "exceeds 96px head"):
            self.build_job(pixels=[0] * 91, width=91)
        with self.assertRaisesRegex(ValueError, "exceeds 96px head"):
            self.build_job(pixels=[0] * 90, width=90, left_padding_pixels=1)

    def test_speed_and_density_accept_uint8_boundaries_and_reject_out_of_range(
        self,
    ) -> None:
        for speed, density in ((0, 0), (255, 255)):
            with self.subTest(speed=speed, density=density):
                frames = self.decoded_frames(
                    self.build_job(speed=speed, density=density)
                )
                self.assertEqual(frames[0][2], bytes((speed,)))
                self.assertEqual(frames[1][2], bytes((density,)))

        with self.assertRaisesRegex(ValueError, "speed must fit in uint8"):
            self.build_job(speed=-1)
        with self.assertRaisesRegex(ValueError, "speed must fit in uint8"):
            self.build_job(speed=256)
        with self.assertRaisesRegex(ValueError, "density must fit in uint8"):
            self.build_job(density=-1)
        with self.assertRaisesRegex(ValueError, "density must fit in uint8"):
            self.build_job(density=256)

        default_density = self.decoded_frames(self.build_job(density=None))
        self.assertEqual(default_density[1][2], b"\x09")

    def test_invalid_variant_encoding_mode_and_raster_format_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "requires an explicit protocol variant"
        ):
            self.build_job(protocol_variant=None)
        with self.assertRaisesRegex(
            ValueError, "requires an explicit protocol variant"
        ):
            self.build_job(protocol_variant="")
        with self.assertRaisesRegex(
            ValueError, "Unsupported YK Astra P1 protocol variant"
        ):
            self.build_job(protocol_variant="other")
        with self.assertRaisesRegex(ValueError, "does not support image encoding"):
            self.build_job(
                image_pipeline=ImagePipelineConfig(
                    formats=(PixelFormat.BW1,),
                    encoding=ImageEncoding.LEGACY_RAW,
                )
            )
        with self.assertRaisesRegex(ValueError, "does not support paper mode"):
            self.build_job(paper_mode=PaperMode.FOLDER)
        with self.assertRaisesRegex(ValueError, "does not support raster format"):
            self.build_job(
                pixels=[255],
                pixel_format=PixelFormat.GRAY8,
                image_pipeline=ImagePipelineConfig(
                    formats=(PixelFormat.GRAY8,),
                    encoding=ImageEncoding.YK_ASTRA_P1_RAW,
                ),
            )

    def test_public_raster_and_printer_builders_round_trip_s001(self) -> None:
        raster_set = RasterSet.from_single(RasterBuffer([1], width=1))
        from_raster_builder = self.build_job().payload
        behavior = get_protocol_behavior(ProtocolFamily.YK_ASTRA_P1)

        class Profile:
            dev_dpi = 203
            can_print_label = False
            post_print_feed_count = 0
            one_length = 0
            a4xii = False
            default_protocol_family = ProtocolFamily.YK_ASTRA_P1

            @staticmethod
            def select_speed(*, is_text: bool) -> int:
                _ = is_text
                return 4

            @staticmethod
            def select_energy(*, is_text: bool, blackening: int) -> int:
                _ = is_text, blackening
                return 0

            @staticmethod
            def select_density(*, is_text: bool, blackening: int) -> int:
                _ = is_text, blackening
                return 9

        device = SimpleNamespace(
            profile=Profile(),
            protocol_family=ProtocolFamily.YK_ASTRA_P1,
            protocol_variant="s001",
            image_pipeline=behavior.default_image_pipeline,
        )
        from_printer_protocol = PrinterProtocol(device).build_job(
            raster_set,
            is_text=False,
            blackening=0,
        )
        self.assertEqual(from_printer_protocol.payload, from_raster_builder)
        self.assertEqual(from_printer_protocol.steps, ())


if __name__ == "__main__":
    unittest.main()
