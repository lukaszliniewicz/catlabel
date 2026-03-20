from __future__ import annotations

import unittest

from tests.helpers import reset_registry_cache
from timiniprint.devices.models import (
    PrinterModel,
    PrinterModelAliasKind,
    PrinterModelAliasRegistry,
    PrinterModelHeadAlias,
    PrinterModelMacAlias,
    PrinterModelMatchSource,
    PrinterModelRegistry,
)


def _model(model_no: str, head_name: str) -> PrinterModel:
    return PrinterModel(
        model_no=model_no,
        model=1,
        size=1,
        paper_size=1,
        print_size=384,
        one_length=1,
        head_name=head_name,
        can_change_mtu=False,
        dev_dpi=203,
        img_print_speed=10,
        text_print_speed=8,
        img_mtu=180,
        new_compress=False,
        paper_num=1,
        interval_ms=4,
        thin_energy=0,
        moderation_energy=5000,
        deepen_energy=0,
        text_energy=8000,
        has_id=False,
        use_spp=False,
        new_format=False,
        can_print_label=False,
        label_value="",
        back_paper_num=0,
    )


class DevicesModelsTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_registry_cache()

    def test_registry_load_get_and_detect(self) -> None:
        reg = PrinterModelRegistry.load()
        self.assertGreater(len(reg.models), 0)
        self.assertIsNotNone(reg.get("X6H"))
        match = reg.detect_with_origin("X6H-123")
        self.assertIsNotNone(match)

    def test_longest_prefix_priority(self) -> None:
        m1 = _model("A", "X")
        m2 = _model("B", "X6")
        reg = PrinterModelRegistry([m1, m2], PrinterModelAliasRegistry([], []))
        match = reg.detect_with_origin("X6H-AB")
        self.assertEqual(match.model.model_no, "B")
        self.assertEqual(match.source, PrinterModelMatchSource.HEAD_NAME)

    def test_case_sensitive_match_beats_case_insensitive_fallback(self) -> None:
        upper = _model("UPPER", "X6H-")
        lower = _model("LOWER", "X6h-")
        reg = PrinterModelRegistry([upper, lower], PrinterModelAliasRegistry([], []))

        match_upper = reg.detect_with_origin("X6H-AB")
        self.assertIsNotNone(match_upper)
        self.assertEqual(match_upper.model.model_no, "UPPER")

        match_lower = reg.detect_with_origin("X6h-AB")
        self.assertIsNotNone(match_lower)
        self.assertEqual(match_lower.model.model_no, "LOWER")

    def test_case_insensitive_fallback_still_detects_model(self) -> None:
        upper = _model("UPPER", "X6H-")
        reg = PrinterModelRegistry([upper], PrinterModelAliasRegistry([], []))

        match = reg.detect_with_origin("x6h-AB")
        self.assertIsNotNone(match)
        self.assertEqual(match.model.model_no, "UPPER")
        self.assertEqual(match.source, PrinterModelMatchSource.HEAD_NAME)

    def test_alias_parse_validation_and_mac_alias(self) -> None:
        with self.assertRaises(ValueError):
            PrinterModelAliasRegistry._parse([{"bad": 1}])

        alias = PrinterModelMacAlias(suffixes=["59"], map_model_head_name="X6H")
        self.assertFalse(alias.matches("F4B3C8E3-C284-9C3A-C549-D786345CB553"))
        self.assertTrue(alias.matches("AA:BB:CC:DD:EE:59"))

    def test_alias_resolution_kind(self) -> None:
        reg = PrinterModelAliasRegistry(
            [PrinterModelHeadAlias(prefixes=["MX01"], map_model_head_name="X6H")],
            [PrinterModelMacAlias(suffixes=["59"], map_model_head_name="X7H")],
        )
        out = reg.resolve("MX01-AB", "AA:BB:CC:DD:EE:59")
        self.assertIsNotNone(out)
        self.assertEqual(out.kind, PrinterModelAliasKind.MAC)

    def test_phomemo_derived_aliases_map_to_new_base_models(self) -> None:
        reg = PrinterModelRegistry.load()

        tp84 = reg.detect_with_origin("TP84-ABCD")
        self.assertIsNotNone(tp84)
        self.assertEqual(tp84.model.model_no, "TP81")
        self.assertEqual(tp84.source, PrinterModelMatchSource.ALIAS)

        m836 = reg.detect_with_origin("M836-ABCD")
        self.assertIsNotNone(m836)
        self.assertEqual(m836.model.model_no, "M832")
        self.assertEqual(m836.source, PrinterModelMatchSource.ALIAS)

        q580 = reg.detect_with_origin("Q580-ABCD")
        self.assertIsNotNone(q580)
        self.assertEqual(q580.model.model_no, "Q302")
        self.assertEqual(q580.source, PrinterModelMatchSource.ALIAS)

        for derived in ("T02E-ABCD", "Q02E-ABCD", "C02E-ABCD"):
            mapped = reg.detect_with_origin(derived)
            self.assertIsNotNone(mapped)
            self.assertEqual(mapped.model.model_no, "T02")
            self.assertIn(
                mapped.source,
                (PrinterModelMatchSource.ALIAS, PrinterModelMatchSource.MODEL_NO),
            )

    def test_experimental_models_are_marked_testing(self) -> None:
        reg = PrinterModelRegistry.load()

        for model_no in ("P100", "MP100", "P100S", "MP100S", "LP100S", "P3", "P3S"):
            model = reg.get(model_no)
            self.assertIsNotNone(model)
            self.assertTrue(model.testing)
            self.assertTrue(model.testing_note)

    def test_experimental_aliases_resolve(self) -> None:
        reg = PrinterModelRegistry.load()

        cases = {
            "YINTIBAO-V5-ABCD": "P100",
            "MP200-ABCD": "P100",
            "YINTIBAO-V5PRO-ABCD": "P100S",
            "LP220-ABCD": "LP100",
            "LP220S-ABCD": "LP100S",
            "MP300-ABCD": "P3",
            "MP300S-ABCD": "P3S",
            "JK01-ABCD": "GT02",
            "KERUI-ABCD": "GT02",
            "BH03-ABCD": "GT02",
            "MXW01-ABCD": "GT02",
            "MXW01-1-ABCD": "GT02",
            "X2-ABCD": "GT02",
            "C17-ABCD": "GT02",
            "MXW-W5-ABCD": "GT02",
            "AC695X_PRINT-ABCD": "GT02",
            "C21-ABCD": "D1",
            "MXW-A4-ABCD": "M08F",
            "YTB01-ABCD": "GT01",
        }

        for name, expected_model_no in cases.items():
            with self.subTest(name=name):
                match = reg.detect_with_origin(name)
                self.assertIsNotNone(match)
                self.assertEqual(match.model.model_no, expected_model_no)
                self.assertEqual(match.source, PrinterModelMatchSource.ALIAS)
                self.assertTrue(match.testing)

    def test_testing_flag_reaches_match_for_direct_and_alias_detection(self) -> None:
        reg = PrinterModelRegistry.load()

        direct = reg.detect_with_origin("P100-ABCD")
        self.assertIsNotNone(direct)
        self.assertTrue(direct.testing)
        self.assertFalse(direct.used_alias)

        alias = reg.detect_with_origin("JK01-ABCD")
        self.assertIsNotNone(alias)
        self.assertTrue(alias.testing)
        self.assertTrue(alias.used_alias)

    def test_direct_x1_model_still_beats_experimental_x1_alias(self) -> None:
        reg = PrinterModelRegistry.load()

        match = reg.detect_with_origin("X1-ABCD")
        self.assertIsNotNone(match)
        self.assertEqual(match.model.model_no, "X1")
        self.assertEqual(match.source, PrinterModelMatchSource.HEAD_NAME)
        self.assertFalse(match.used_alias)
        self.assertTrue(match.has_brand_conflict)
        self.assertEqual(match.conflict_models, ("GT02",))

    def test_non_conflicting_model_has_no_brand_conflict(self) -> None:
        reg = PrinterModelRegistry.load()

        match = reg.detect_with_origin("X6H-ABCD")
        self.assertIsNotNone(match)
        self.assertFalse(match.has_brand_conflict)
        self.assertEqual(match.conflict_models, ())

    def test_mac_suffix_59_promotes_gt_bucket_to_gt02(self) -> None:
        reg = PrinterModelRegistry.load()

        match = reg.detect_with_origin("MX01-ABCD", "AA:BB:CC:DD:EE:59")
        self.assertIsNotNone(match)
        self.assertEqual(match.model.model_no, "GT02")
        self.assertEqual(match.source, PrinterModelMatchSource.ALIAS)
        self.assertEqual(match.alias_kind, PrinterModelAliasKind.MAC)

    def test_mac_suffix_59_does_not_override_unrelated_alias_families(self) -> None:
        reg = PrinterModelRegistry.load()

        cases = {
            "TP84-ABCD": "TP81",
            "M836-ABCD": "M832",
            "Q580-ABCD": "Q302",
            "C02E-ABCD": "T02",
        }
        for name, expected_model_no in cases.items():
            with self.subTest(name=name):
                match = reg.detect_with_origin(name, "AA:BB:CC:DD:EE:59")
                self.assertIsNotNone(match)
                self.assertEqual(match.model.model_no, expected_model_no)
                self.assertNotEqual(match.alias_kind, PrinterModelAliasKind.MAC)


if __name__ == "__main__":
    unittest.main()
