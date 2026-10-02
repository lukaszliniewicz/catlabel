from __future__ import annotations

import unittest

from catlabel.protocol import ProtocolFamily
from catlabel.vendors.generic.manifest import GenericManifest
from catlabel.vendors.generic.models import PrinterModelRegistry
from catlabel.vendors.utils import extract_raw_hardware_info


class GenericLuckModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = PrinterModelRegistry.load()

    def assertDetected(
        self, name: str, model_no: str, family: ProtocolFamily, variant: str | None
    ) -> None:
        match = self.registry.detect_with_origin(name)
        self.assertIsNotNone(match, name)
        if match is None:
            self.fail(f"{name} should be detected")
        self.assertEqual(match.model.model_no, model_no)
        self.assertEqual(match.protocol_family, family)
        self.assertEqual(match.protocol_variant, variant)

    def test_luck_detection_uses_source_backed_prefixes_only(self) -> None:
        # A2/A2H are marketing names in the Luck source, not advertised-name
        # triggers.  The Tiny source independently advertises A2/A3.
        self.assertDetected("A2", "x16", ProtocolFamily.LEGACY, None)
        self.assertDetected("A2H", "x16", ProtocolFamily.LEGACY, None)
        self.assertDetected("PPA2_1234", "luck_a2", ProtocolFamily.LUCK_NORMAL, None)
        self.assertDetected("PPA2H_1234", "luck_a2h", ProtocolFamily.LUCK_NORMAL, None)

    def test_luck_a4_aliases_resolve_to_protocol_variants(self) -> None:
        expected = {
            "APA49H_1234": ("luck_a49h", "a49h"),
            "DP_ITP05_1234": ("luck_itp05", "a4_tattoo_64"),
            "TPA46Pro_1234": ("luck_itp06", "a4_tattoo_64_endline96"),
            "APL86H_1234": ("luck_apl86h", "apl86"),
            "DP_D80_1234": ("luck_d80", "d80"),
            "DP_D80H_1234": ("luck_d80h", "d80h"),
            "DP_A80H_1234": ("luck_a80h_way1", "a80h_way1"),
            "LuckP_A41_1234": ("luckp_a41", "luckp_a41"),
        }
        for name, (model_no, variant) in expected.items():
            with self.subTest(name=name):
                self.assertDetected(
                    name, model_no, ProtocolFamily.LUCK_NORMAL_A4, variant
                )

    def test_qirui_hardware_info_exposes_only_supported_paper_modes(self) -> None:
        match = self.registry.detect_with_origin("QIRUI_Q2_1234")
        self.assertIsNotNone(match)
        if match is None:
            self.fail("QIRUI_Q2_1234 should be detected")
        raw = extract_raw_hardware_info(match.model)

        self.assertEqual(raw["protocol_family"], "luck_normal")
        self.assertEqual(raw["protocol_variant"], "qirui_q2")
        self.assertEqual(
            [mode["value"] for mode in raw["supported_paper_modes"]], ["plain", "tag"]
        )

    def test_unimplemented_luck_names_are_not_claimed(self) -> None:
        for name in ("A49H", "D80H", "ITP05N"):
            with self.subTest(name=name):
                self.assertIsNone(self.registry.detect_with_origin(name))

    def test_ppa2_variants_are_detected(self) -> None:
        self.assertDetected(
            "PPA2L_1234",
            "luck_ppa2l",
            ProtocolFamily.LUCK_NORMAL,
            "lujiang_normal",
        )
        self.assertDetected(
            "PPA2LH_1234",
            "luck_ppa2lh",
            ProtocolFamily.LUCK_NORMAL,
            "lujiang_normal_h",
        )

    def test_generic_manifest_reports_paper_modes_for_luck_models(self) -> None:
        manifest = GenericManifest()
        info = manifest.identify_device("APA49H_1234")

        self.assertIsNotNone(info)
        if info is None:
            self.fail("APA49H_1234 hardware info should be available")
        self.assertEqual(info["protocol_family"], "luck_normal_a4")
        self.assertEqual(info["protocol_variant"], "a49h")
        self.assertIn({"value": "tag", "label": "Tag"}, info["supported_paper_modes"])


if __name__ == "__main__":
    unittest.main()
