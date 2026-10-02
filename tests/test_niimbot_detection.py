from __future__ import annotations

import unittest
from unittest.mock import patch

from catlabel.vendors.niimbot.manifest import NiimbotManifest


class NiimbotDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = NiimbotManifest()

    def test_supported_aliases_keep_their_model_geometry_and_capabilities(self) -> None:
        expected_model_ids = {
            "D11": "D110",
            "D110": "D110",
            "D101": "D101",
            "B18": "B18",
            "B1": "B1",
            "B21": "B1",
            "B3S": "B3S",
            "B24": "B3S",
        }
        expected_geometry = {
            "D110": (120, 15),
            "D101": (200, 25),
            "B18": (112, 14),
            "B1": (384, 48),
            "B3S": (576, 72),
        }
        supported_models = {
            model["model_id"]: model for model in self.manifest.get_supported_models()
        }

        for alias, model_id in expected_model_ids.items():
            with self.subTest(alias=alias):
                detected = self.manifest.identify_device(alias)
                assert detected is not None
                expected = dict(supported_models[model_id])
                if alias == "D11":
                    expected["protocol_variant"] = "d11_auto"
                self.assertEqual(detected, expected)
                self.assertEqual(
                    (detected["width_px"], detected["width_mm"]),
                    expected_geometry[model_id],
                )
                self.assertEqual(
                    detected["capabilities"], self.manifest._build_capabilities()
                )

    def test_serial_suffixes_and_vendor_prefixes_require_delimiters(self) -> None:
        valid_names = {
            " D11-123 ": "D110",
            "D110_serial": "D110",
            "D101 series": "D101",
            "B18-123": "B18",
            "B1_serial": "B1",
            "B21 serial": "B1",
            "B3S-serial": "B3S",
            "B24_serial": "B3S",
            "niimbot D11": "D110",
            "D11S_serial": "D11S",
            "NIIMBOT-D110_serial": "D110",
            "NIIMBOT_B21-serial": "B1",
        }

        for name, expected_model_id in valid_names.items():
            with self.subTest(name=name):
                detected = self.manifest.identify_device(name)
                self.assertIsNotNone(detected)
                assert detected is not None
                self.assertEqual(detected["model_id"], expected_model_id)

    def test_d_protocol_variants_preserve_existing_geometry(self) -> None:
        for name, variant, width in (
            ("D11", "d11_auto", 120),
            ("D110_serial", "d110", 120),
            ("D11S_serial", "d11_v1", 96),
        ):
            with self.subTest(name=name):
                detected = self.manifest.identify_device(name)
                assert detected is not None
                self.assertEqual(detected["protocol_variant"], variant)
                self.assertEqual(detected["width_px"], width)
                self.assertEqual(detected["dpi"], 203)
        models = self.manifest.get_supported_models()
        d110 = next(model for model in models if model["model_id"] == "D110")
        self.assertEqual(d110["protocol_variant"], "d110")
        self.assertNotIn("protocol_variant", self.manifest.identify_device("B21") or {})

    def test_unsupported_similar_model_names_are_not_claimed(self) -> None:
        for name in (
            "D111",
            "D1100",
            "B18PROJECT",
            "B100",
            "B210",
            "NIIMBOTD110",
            "UNKNOWN D11",
        ):
            with self.subTest(name=name):
                self.assertIsNone(self.manifest.identify_device(name))

    def test_longest_alias_wins_independent_of_supported_model_order(self) -> None:
        short_model = {"model_id": "short"}
        long_model = {"model_id": "long"}
        aliases = {"short": ("B1",), "long": ("B1-PRO",)}

        for models in (
            [short_model, long_model],
            [long_model, short_model],
        ):
            with self.subTest(model_order=[model["model_id"] for model in models]):
                with (
                    patch.object(
                        self.manifest, "get_supported_models", return_value=models
                    ),
                    patch.object(
                        self.manifest,
                        "_model_prefixes",
                        side_effect=lambda model_id: aliases[model_id],
                    ),
                ):
                    detected = self.manifest.identify_device("B1-PRO serial")

                self.assertEqual(detected, long_model)

    def test_equal_longest_aliases_for_distinct_models_are_ambiguous(self) -> None:
        models = [{"model_id": "left"}, {"model_id": "right"}]

        with (
            patch.object(self.manifest, "get_supported_models", return_value=models),
            patch.object(
                self.manifest,
                "_model_prefixes",
                side_effect=lambda _model_id: ("SHARED",),
            ),
        ):
            detected = self.manifest.identify_device("SHARED-123")

        self.assertIsNone(detected)

    def test_reversing_real_supported_models_does_not_change_detection(self) -> None:
        supported_models = self.manifest.get_supported_models()
        for models in (supported_models, list(reversed(supported_models))):
            with self.subTest(model_order=[model["model_id"] for model in models]):
                with patch.object(
                    self.manifest,
                    "get_supported_models",
                    return_value=models,
                ):
                    detected = self.manifest.identify_device("B24-label")

                assert detected is not None
                self.assertEqual(detected["model_id"], "B3S")


if __name__ == "__main__":
    unittest.main()
