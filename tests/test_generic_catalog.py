from __future__ import annotations

import unittest
from collections import Counter

from catlabel.protocol import ProtocolFamily
from catlabel.vendors.generic.manifest import GenericManifest
from catlabel.vendors.generic.models import DetectionRule, PrinterModelRegistry
from catlabel.vendors.utils import extract_raw_hardware_info


class GenericCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = PrinterModelRegistry.load()

    def test_catalog_is_pinned_to_timiniprint_073(self) -> None:
        self.assertEqual(
            self.registry.source_metadata["commit"],
            "3373a037ccbaafc32cfafd5ed9ef496efd1efacd",
        )
        self.assertEqual(self.registry.source_metadata["revision"], "v0.7.3")
        self.assertEqual(self.registry.unsupported_model_count, 165)
        self.assertEqual(self.registry.deferred_model_count, 11)

    def test_only_executable_generic_profiles_are_advertised(self) -> None:
        counts = Counter(model.protocol_family for model in self.registry.models)
        self.assertEqual(len(self.registry.models), 132)
        self.assertEqual(counts[ProtocolFamily.LEGACY], 79)
        self.assertEqual(counts[ProtocolFamily.V5G], 14)
        self.assertEqual(counts[ProtocolFamily.ELEPH_TSPL], 1)
        self.assertEqual(counts[ProtocolFamily.TOPRINT_TSPL], 1)
        self.assertEqual(counts[ProtocolFamily.TOPRINT_HPRT_ESC], 1)
        self.assertNotIn(ProtocolFamily.ELEPH_HPRT_ESC, counts)
        self.assertEqual(counts[ProtocolFamily.INSTAPRINT_CORE], 1)
        self.assertEqual(counts[ProtocolFamily.FUNNY_LX], 1)
        self.assertNotIn(ProtocolFamily.DCK, counts)

    def test_mac_constrained_v5x_variant_beats_v5g_name(self) -> None:
        ordinary = self.registry.detect_with_origin("MX10")
        constrained = self.registry.detect_with_origin("MX10", "00:11:22:33:44:59")

        self.assertIsNotNone(ordinary)
        if ordinary is None:
            self.fail("ordinary MX10 detection should match")
        self.assertEqual(ordinary.protocol_family, ProtocolFamily.V5G)
        self.assertIsNotNone(constrained)
        if constrained is None:
            self.fail("MAC-constrained MX10 detection should match")
        self.assertEqual(constrained.protocol_family, ProtocolFamily.V5X)

    def test_mac_constrained_rule_rejects_uuid_address(self) -> None:
        match = self.registry.detect_with_origin(
            "MX10",
            "F4B3C8E3-C284-9C3A-C549-D786345CB559",
        )

        self.assertIsNotNone(match)
        if match is None:
            self.fail("UUID-like address should retain ordinary MX10 match")
        self.assertEqual(match.protocol_family, ProtocolFamily.V5G)

    def test_detection_specificity_prefers_exact_for_equal_length(self) -> None:
        exact = DetectionRule(display_name="exact", exact_names=("X6",))
        prefix = DetectionRule(display_name="prefix", prefixes=("X6",))
        exact_score = exact.match_score("X6", None, casefold=False)
        prefix_score = prefix.match_score("X6", None, casefold=False)

        self.assertIsNotNone(exact_score)
        if exact_score is None:
            self.fail("exact detection rule should match X6")
        self.assertIsNotNone(prefix_score)
        if prefix_score is None:
            self.fail("prefix detection rule should match X6")
        self.assertGreater(exact_score, prefix_score)

    def test_known_unsupported_models_are_not_claimed(self) -> None:
        for name in (
            "C21",
            "D110",
            "M02",
        ):
            with self.subTest(name=name):
                self.assertIsNone(self.registry.detect_with_origin(name))

    def test_new_runtime_and_protocol_families_are_claimed(self) -> None:
        expected = {
            "PPA2L_1234": ProtocolFamily.LUCK_NORMAL,
            "PPA2LH_1234": ProtocolFamily.LUCK_NORMAL,
            "CorePrint": ProtocolFamily.INSTAPRINT_CORE,
            "LX-D01": ProtocolFamily.FUNNY_LX,
            "P1_F30E": ProtocolFamily.ELEPH_TSPL,
            "P11_F30E": ProtocolFamily.TOPRINT_HPRT_ESC,
        }
        for name, family in expected.items():
            with self.subTest(name=name):
                match = self.registry.detect_with_origin(name)
                self.assertIsNotNone(match)
                if match is None:
                    self.fail(f"{name} should be detected")
                self.assertEqual(match.protocol_family, family)

    def test_new_family_detection_keeps_source_ambiguities_unresolved(self) -> None:
        self.assertIsNone(self.registry.detect_with_origin("P1"))
        self.assertIsNone(self.registry.detect_with_origin("P1-1234"))
        self.assertIsNone(self.registry.detect_with_origin("YHK"))
        self.assertIsNone(self.registry.detect_with_origin("LX-D02-60"))

    def test_profile_exposes_paper_geometry_and_packet_variant(self) -> None:
        model = self.registry.get("p4")
        self.assertIsNotNone(model)
        if model is None:
            self.fail("p4 profile should exist")
        self.assertEqual(model.protocol_family, ProtocolFamily.LEGACY)
        self.assertEqual(model.protocol_variant, "line_eight")
        self.assertEqual(
            model.paper_preset("a4sheet_1600r_1624p_24pl").left_padding_px, 24
        )

    def test_v5g_tuned_density_is_not_reported_as_protocol_limit(self) -> None:
        model = self.registry.get("mx11")
        self.assertIsNotNone(model)
        if model is None:
            self.fail("mx11 profile should exist")
        self.assertEqual(model.min_density, 100)
        self.assertEqual(model.default_density, 130)
        self.assertEqual(model.max_density, 150)

        capabilities = GenericManifest()._build_capabilities(
            extract_raw_hardware_info(model)
        )
        density = capabilities["density"]
        self.assertEqual(density["min"], 1)
        self.assertEqual(density["max"], 200)
        self.assertEqual(density["default"], 130)
        self.assertEqual(density["recommended_min"], 100)
        self.assertEqual(density["recommended_max"], 150)
        self.assertTrue(density["allow_auto"])

    def test_profile_density_default_is_kept_without_runtime_preset(self) -> None:
        model = self.registry.get("bq02_v5g")
        self.assertIsNotNone(model)
        if model is None:
            self.fail("bq02 V5G profile should exist")
        self.assertIsNone(model.runtime_density)
        self.assertEqual(model.default_density, 150)

    def test_v5g_without_density_profile_keeps_auto_default(self) -> None:
        model = self.registry.get("mx02")
        self.assertIsNotNone(model)
        if model is None:
            self.fail("mx02 profile should exist")
        capabilities = GenericManifest()._build_capabilities(
            extract_raw_hardware_info(model)
        )

        self.assertIsNone(capabilities["density"]["default"])
        self.assertEqual(capabilities["density"]["max"], 200)


if __name__ == "__main__":
    unittest.main()
