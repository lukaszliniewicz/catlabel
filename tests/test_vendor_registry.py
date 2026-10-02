from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from catlabel.vendors import VendorRegistry


class VendorRegistryTests(unittest.TestCase):
    def test_real_names_keep_vendor_and_specific_geometry(self) -> None:
        for name, vendor, model in (
            ("D100", "generic", "d100"),
            ("DP_D80_123", "generic", "luck_d80"),
            ("D30", "phomemo", "D30"),
            ("M02PRO", "phomemo", "M02_PRO"),
            ("D110", "niimbot", "D110"),
        ):
            with self.subTest(name=name):
                info = VendorRegistry.identify_device(name)
                self.assertEqual((info["vendor"], info["model_id"]), (vendor, model))
                self.assertEqual(info["detection_status"], "recognized")

    def test_unknown_and_blocked_names_keep_the_unknown_sentinel(self) -> None:
        # v0.8.1 marks D80_ aliases as ambiguous across two wire protocols.
        for name in ("D1", "D2", "D80", "D80_123", "M02H", "unrecognized printer"):
            with self.subTest(name=name):
                info = VendorRegistry.identify_device(name)
                self.assertEqual(
                    (info["vendor"], info["model_id"]), ("generic", "generic")
                )
                self.assertEqual(info["detection_status"], "unknown")

    def test_conflicting_vendors_are_not_chosen_by_registration_order(self) -> None:
        fallback = {"vendor": "generic", "model_id": "generic"}

        def plugin(vendor: str):
            return SimpleNamespace(
                identify_device=lambda *_args: {
                    "vendor": vendor,
                    "model_id": "same-name",
                    "protocol_family": vendor,
                },
                get_fallback_info=lambda: dict(fallback),
            )

        generic = SimpleNamespace(
            identify_device=lambda *_args: None,
            get_fallback_info=lambda: dict(fallback),
        )
        for plugins in (
            {"generic": generic, "one": plugin("one"), "two": plugin("two")},
            {"two": plugin("two"), "one": plugin("one"), "generic": generic},
            {"one": plugin("one"), "generic": plugin("generic")},
        ):
            with (
                self.subTest(order=list(plugins)),
                patch.object(VendorRegistry, "_plugins", plugins),
            ):
                info = VendorRegistry.identify_device("same-name")
                self.assertEqual(info["model_id"], "generic")
                self.assertEqual(info["detection_status"], "ambiguous")
                self.assertEqual(len(info["detection_candidates"]), 2)


if __name__ == "__main__":
    unittest.main()
