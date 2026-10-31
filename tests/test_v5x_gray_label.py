from __future__ import annotations

import unittest

from catlabel.protocol.families.base import PrintJobRequest
from catlabel.protocol.families.v5x import build_job
from catlabel.protocol.family import ProtocolFamily
from catlabel.protocol.types import ImageEncoding, ImagePipelineConfig, PaperMode
from catlabel.raster import PixelFormat, RasterBuffer, RasterSet


class V5XGrayLabelTests(unittest.TestCase):
    def test_label_variant_uses_its_own_wire_mode_without_changing_ordinary_gray(
        self,
    ) -> None:
        for variant, gray, paper, mode in (
            (None, False, PaperMode.PLAIN, 0),
            (None, False, PaperMode.TAG, 1),
            (None, True, PaperMode.TAG, 2),
            ("gray_label", True, PaperMode.PLAIN, 2),
            ("gray_label", True, PaperMode.TAG, 3),
            ("gray_label", False, PaperMode.TAG, 1),
        ):
            with self.subTest(variant=variant, gray=gray, paper=paper):
                pixel_format = PixelFormat.GRAY8 if gray else PixelFormat.BW1
                raster = RasterBuffer([0] * 8, 8, pixel_format)
                request = PrintJobRequest(
                    raster_set=RasterSet.from_single(raster),
                    image_pipeline=ImagePipelineConfig(
                        (pixel_format,),
                        ImageEncoding.V5X_GRAY if gray else ImageEncoding.V5X_DOT,
                    ),
                    is_text=False,
                    speed=1,
                    energy=1,
                    blackening=3,
                    lsb_first=False,
                    protocol_family=ProtocolFamily.V5X,
                    protocol_variant=variant,
                    feed_padding=0,
                    dev_dpi=203,
                    paper_mode=paper,
                )
                plan = build_job(request)
                self.assertEqual(
                    plan.steps[1].data,
                    bytes.fromhex("2221a9000400010030") + bytes([mode, 0, 0]),
                )


if __name__ == "__main__":
    unittest.main()
