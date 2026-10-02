from __future__ import annotations

import unittest
from dataclasses import replace

from catlabel.protocol.families.base import PrintJobRequest
from catlabel.protocol.families.luck_normal import RECIPE as NORMAL_RECIPE
from catlabel.protocol.families.luck_normal_a4 import A4_MARKED_TAG_RECIPE
from catlabel.protocol.families.luck_normal_a4 import RECIPE as A4_RECIPE
from catlabel.protocol.families.luck_normal_core import LuckNormalVariantRecipe
from catlabel.protocol.families.luck_transactions import (
    LUJIANG_A4_FINALIZE_TIMEOUT_SEC,
    NORMAL_FINALIZE_TIMEOUT_SEC,
    QUERY_TIMEOUT_SEC,
    density_setting,
    finalize,
    paper_setting,
    status_query,
)
from catlabel.protocol.family import ProtocolFamily
from catlabel.protocol.plan import ProtocolPlan
from catlabel.protocol.steps import (
    ProtocolReplyExpectation,
    ProtocolStep,
    ProtocolStepOperation,
)
from catlabel.protocol.types import (
    ImageEncoding,
    ImagePipelineConfig,
    PageFlow,
    PaperMode,
)
from catlabel.raster import PixelFormat, RasterBuffer, RasterSet


def _request(
    family: ProtocolFamily,
    *,
    variant: str | None = None,
    paper_mode: PaperMode = PaperMode.PLAIN,
    page_index: int = 1,
    page_count: int = 1,
    page_flow: PageFlow = PageFlow.PAGED,
    pixels: tuple[int, ...] = (1, 1, 1, 1, 1, 1, 1, 1),
) -> PrintJobRequest:
    raster = RasterBuffer(pixels, 8, PixelFormat.BW1)
    return PrintJobRequest(
        raster_set=RasterSet.from_single(raster),
        image_pipeline=ImagePipelineConfig(
            formats=(PixelFormat.BW1,), encoding=ImageEncoding.LUCK_NORMAL_RAW
        ),
        is_text=False,
        speed=10,
        energy=5000,
        blackening=3,
        lsb_first=False,
        protocol_family=family,
        protocol_variant=variant,
        feed_padding=0,
        dev_dpi=203,
        density=1,
        paper_mode=paper_mode,
        page_index=page_index,
        page_count=page_count,
        page_flow=page_flow,
    )


def _step_named(plan: ProtocolPlan, label: str) -> ProtocolStep:
    return next(step for step in plan.steps if step.label == label)


class LuckSelectedTransactionTests(unittest.TestCase):
    def test_a4_plain_job_keeps_literal_wire_payload_and_declares_every_transaction(
        self,
    ) -> None:
        plan = A4_RECIPE.build_job(_request(ProtocolFamily.LUCK_NORMAL_A4))

        self.assertIsInstance(plan, ProtocolPlan)
        self.assertEqual(
            plan.payload,
            bytes.fromhex(
                "10 ff 10 00 01"
                "10 ff f1 03"
                "00 00 00 00 00 00 00 00 00 00 00 00"
                "1f 80 01 10"
                "1d 76 30 00 01 00 01 00 ff"
                "1b 4a 90"
                "10 ff f1 45"
            ),
        )
        self.assertEqual(
            [step.label for step in plan.steps],
            [
                "density",
                "status",
                "enable",
                "wakeup",
                "paper type",
                "bitmap",
                "line feed",
                "finalize",
            ],
        )
        self.assertEqual(_step_named(plan, "status").data, bytes.fromhex("10 ff 40"))
        self.assertFalse(_step_named(plan, "status").include_in_payload)
        self.assertIs(_step_named(plan, "density").expect, ProtocolReplyExpectation.OK)
        self.assertTrue(_step_named(plan, "density").reply_required)
        self.assertIs(
            _step_named(plan, "paper type").operation, ProtocolStepOperation.QUERY
        )
        self.assertFalse(_step_named(plan, "paper type").reply_required)
        self.assertTrue(_step_named(plan, "finalize").reply_required)
        self.assertEqual(
            _step_named(plan, "finalize").timeout_sec, NORMAL_FINALIZE_TIMEOUT_SEC
        )

    def test_released_reply_matchers_keep_exact_completion_and_prefix_rules(
        self,
    ) -> None:
        status = status_query().reply_matcher
        assert status is not None
        self.assertFalse(status.complete(b""))
        self.assertTrue(status.complete(b"\x20"))
        assert status.matches is not None
        self.assertEqual(
            [status.matches(bytes([value])) for value in (0, 0x20, 0x80, 0xA0)],
            [True, True, True, True],
        )
        self.assertEqual(
            [status.matches(bytes([value])) for value in (1, 2, 4, 8, 16, 64)],
            [False, False, False, False, False, False],
        )

        density = density_setting(b"density").reply_matcher
        assert density is not None and density.matches is not None
        self.assertFalse(density.complete(b""))
        self.assertFalse(density.complete(b"O"))
        self.assertTrue(density.complete(b"OK"))
        self.assertTrue(density.matches(b"OK"))
        self.assertFalse(density.matches(b"OKextra"))
        self.assertFalse(density.matches(b"\x00OK"))

        paper = paper_setting(b"paper").reply_matcher
        assert paper is not None and paper.matches is not None
        self.assertFalse(paper.complete(b"O"))
        self.assertTrue(paper.complete(b"OK"))
        self.assertTrue(paper.matches(b"OKextra"))
        self.assertFalse(paper.matches(b"NO"))

        finalizer = finalize(b"end", timeout_sec=70).reply_matcher
        assert finalizer is not None
        assert finalizer.matches is not None
        for reply in (b"OK", b"OKextra", b"\xaa", b"\xaa\x00"):
            self.assertTrue(finalizer.complete(reply))
            assert finalizer.matches is not None
            self.assertTrue(finalizer.matches(reply))
        self.assertFalse(finalizer.matches(None))
        for reply in (b"", b"NO", b"\x00\xaa", b"\x00OK"):
            self.assertFalse(finalizer.complete(reply))
            self.assertFalse(finalizer.matches(reply))

    def test_paper_setting_can_skip_wait_or_reserve_optional_reply_window(self) -> None:
        packet = b"\x1f\x80\x01\x20"
        sent = paper_setting(packet, wait_for_reply=False)
        self.assertIs(sent.operation, ProtocolStepOperation.SEND)
        self.assertEqual(sent.data, packet)

        optional = paper_setting(packet)
        self.assertIs(optional.operation, ProtocolStepOperation.QUERY)
        self.assertEqual(optional.timeout_sec, QUERY_TIMEOUT_SEC)
        self.assertFalse(optional.reply_required)

    def test_every_existing_variant_uses_required_transactions_and_timeout(
        self,
    ) -> None:
        for recipe, family in (
            (NORMAL_RECIPE, ProtocolFamily.LUCK_NORMAL),
            (A4_RECIPE, ProtocolFamily.LUCK_NORMAL_A4),
        ):
            for variant in recipe.supported_variants():
                with self.subTest(family=family.value, variant=variant):
                    mode = next(iter(recipe.mode_recipes_for_variant(variant)))
                    plan = recipe.build_job(
                        _request(family, variant=variant, paper_mode=mode)
                    )

                    self.assertIsInstance(plan, ProtocolPlan)
                    self.assertTrue(plan.steps)
                    self.assertEqual(plan.steps[0].label, "density")
                    status = _step_named(plan, "status")
                    self.assertIs(status.operation, ProtocolStepOperation.QUERY)
                    self.assertEqual(status.timeout_sec, QUERY_TIMEOUT_SEC)
                    self.assertFalse(status.include_in_payload)
                    density = _step_named(plan, "density")
                    self.assertIs(density.operation, ProtocolStepOperation.QUERY)
                    self.assertEqual(density.timeout_sec, QUERY_TIMEOUT_SEC)
                    self.assertTrue(density.reply_required)
                    final = plan.steps[-1]
                    self.assertEqual(final.label, "finalize")
                    self.assertIs(final.operation, ProtocolStepOperation.QUERY)
                    self.assertTrue(final.reply_required)
                    expected_timeout = (
                        LUJIANG_A4_FINALIZE_TIMEOUT_SEC
                        if family is ProtocolFamily.LUCK_NORMAL_A4
                        and variant == "lujiang_a4"
                        else NORMAL_FINALIZE_TIMEOUT_SEC
                    )
                    self.assertEqual(final.timeout_sec, expected_timeout)
                    for setting in (
                        step for step in plan.steps if step.label == "paper type"
                    ):
                        self.assertIs(setting.operation, ProtocolStepOperation.QUERY)
                        self.assertEqual(setting.timeout_sec, QUERY_TIMEOUT_SEC)
                        self.assertFalse(setting.reply_required)

    def test_a4_adjustments_and_last_marker_keep_first_middle_last_order(self) -> None:
        variant = "scope_test"
        recipe = replace(
            A4_RECIPE,
            mode_recipes={
                PaperMode.TAG: replace(
                    A4_MARKED_TAG_RECIPE, mark_last_scope="last_page"
                )
            },
            variants={variant: LuckNormalVariantRecipe()},
        )

        pages = [
            recipe.build_job(
                _request(
                    ProtocolFamily.LUCK_NORMAL_A4,
                    variant=variant,
                    paper_mode=PaperMode.TAG,
                    page_index=index,
                    page_count=3,
                    page_flow=PageFlow.CONTINUOUS,
                )
            )
            for index in (1, 2, 3)
        ]
        boundary_labels = {"adjust before", "position", "mark last", "adjust after"}
        scopes = [
            [step.label for step in plan.steps if step.label in boundary_labels]
            for plan in pages
        ]

        self.assertEqual(
            scopes, [["adjust before"], [], ["position", "mark last", "adjust after"]]
        )
        last = pages[-1]
        self.assertEqual(
            [
                step.data
                for step in last.steps
                if step.label in {"mark last", "adjust after"}
            ],
            [bytes.fromhex("1b bb bb"), bytes.fromhex("1f 11 50")],
        )
        self.assertNotIn(b"\x1d\x0c", pages[0].payload)
        self.assertNotIn(b"\x1d\x0c", pages[1].payload)

    def test_a4_defaults_and_image_support_are_monochrome_only(self) -> None:
        self.assertEqual(A4_RECIPE.default_image_pipeline.formats, (PixelFormat.BW1,))
        self.assertEqual(
            A4_RECIPE.image_encoding_support,
            {
                ImageEncoding.LUCK_NORMAL_RAW: (PixelFormat.BW1,),
                ImageEncoding.LUCK_NORMAL_COMPRESSED: (PixelFormat.BW1,),
            },
        )
        self.assertEqual(
            NORMAL_RECIPE.default_image_pipeline.formats,
            (PixelFormat.BW1, PixelFormat.GRAY4, PixelFormat.GRAY8),
        )


if __name__ == "__main__":
    unittest.main()
