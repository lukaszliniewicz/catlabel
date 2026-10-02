from __future__ import annotations

import unittest
from unittest.mock import patch

from catlabel.vendors import VendorRegistry
from catlabel.vendors.phomemo.manifest import PhomemoManifest


class PhomemoDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = PhomemoManifest()

    def test_explicit_aliases_and_delimited_suffixes(self) -> None:
        cases = (
            ("p12pro", "P12"),
            ("P12 Pro", "P12"),
            (" M02PRO ", "M02_PRO"),
            ("M02 PRO", "M02_PRO"),
            ("M02_PRO", "M02_PRO"),
            ("M02 PRO Label", "M02_PRO"),
            ("M02", "M02"),
            ("M02S", "M02"),
            ("M02X", "M02"),
            ("PM241BT", "PM241"),
            ("PM-241-BT", "PM241"),
            ("D30", "D30"),
            ("D35", "D30"),
            ("D50", "D30"),
            ("D30_123", "D30"),
            ("D35-ROLL", "D30"),
            ("D50 label", "D30"),
            ("PHOMEMO-D30_123", "D30"),
            ("PHOMEMO D35 Label", "D30"),
            ("MR.IN-D50 Roll", "D30"),
            (" mr.in d30_123 ", "D30"),
        )
        for name, expected_model_id in cases:
            with self.subTest(name=name):
                info = self.manifest.identify_device(name)
                self.assertIsNotNone(info)
                assert info is not None
                self.assertEqual(info["model_id"], expected_model_id)

    def test_m02_pro_and_plain_models_keep_their_geometry(self) -> None:
        pro = self.manifest.identify_device("M02Pro")
        self.assertIsNotNone(pro)
        assert pro is not None
        self.assertEqual((pro["width_px"], pro["dpi"]), (624, 300))

        for name in ("M02", "M02S", "M02X"):
            with self.subTest(name=name):
                info = self.manifest.identify_device(name)
                self.assertIsNotNone(info)
                assert info is not None
                self.assertEqual(info["model_id"], "M02")
                self.assertEqual((info["width_px"], info["dpi"]), (384, 203))

    def test_vendor_names_and_unbounded_prefixes_do_not_claim_models(self) -> None:
        for name in (
            "PHOMEMO",
            "MR.IN",
            "PHOMEMO Printer",
            "D1",
            "D2",
            "D80",
            "D100",
            "D300",
            "M02PROJECT",
            "M02H",
        ):
            with self.subTest(name=name):
                self.assertIsNone(self.manifest.identify_device(name))

    def test_longest_alias_wins_independently_of_model_list_order(self) -> None:
        models = self.manifest.get_supported_models()
        with patch.object(self.manifest, "get_supported_models", return_value=models):
            forward = self.manifest.identify_device("M02 PRO")
        with patch.object(
            self.manifest,
            "get_supported_models",
            return_value=list(reversed(models)),
        ):
            reversed_order = self.manifest.identify_device("M02 PRO")

        self.assertIsNotNone(forward)
        self.assertIsNotNone(reversed_order)
        assert forward is not None
        assert reversed_order is not None
        self.assertEqual(forward["model_id"], "M02_PRO")
        self.assertEqual(reversed_order["model_id"], forward["model_id"])

    def test_equal_longest_aliases_for_distinct_models_return_none(self) -> None:
        models = [{"model_id": "TEST_A"}, {"model_id": "TEST_B"}]
        aliases = {"TEST_A": ("COLLISION",), "TEST_B": ("COLLISION",)}
        with (
            patch.object(self.manifest, "get_supported_models", return_value=models),
            patch.object(
                self.manifest, "_model_aliases", side_effect=aliases.__getitem__
            ),
        ):
            self.assertIsNone(self.manifest.identify_device("COLLISION"))

    def test_public_registry_preserves_mx10_and_unsupported_model_behavior(
        self,
    ) -> None:
        ordinary_mx10 = VendorRegistry.identify_device("MX10")
        constrained_mx10 = VendorRegistry.identify_device(
            "MX10", mac="00:11:22:33:44:59"
        )
        unsupported_m02h = VendorRegistry.identify_device("M02H")

        self.assertEqual(ordinary_mx10["protocol_family"], "v5g")
        self.assertEqual(constrained_mx10["protocol_family"], "v5x")
        self.assertEqual(unsupported_m02h["vendor"], "generic")
        self.assertEqual(unsupported_m02h["model_id"], "generic")


if __name__ == "__main__":
    unittest.main()
