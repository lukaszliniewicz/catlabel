from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from catlabel.protocol.family import ProtocolFamily
from catlabel.vendors.generic import models as catalog
from catlabel.vendors.generic.catalog_snapshot import CATALOG_FILENAMES
from catlabel.vendors.generic.models import (
    DetectionRule,
    PrinterModelRegistry,
    WhitespaceMode,
)


def model(key: str = "modern", **changes: Any) -> dict[str, Any]:
    return {
        "model_key": key,
        "profile_key": "basic",
        "detections": [{"exact_names": [key]}],
        **changes,
    }


def bundle(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": {
            "repository": "https://github.com/Dejniel/TiMini-Print",
            "revision": "v0.8.1",
            "commit": "f676917257b5d1f869e0f13beff03785258e2a2e",
            "license": "Apache-2.0",
            "files": {name: f"timiniprint/data/{name}" for name in CATALOG_FILENAMES},
        },
        "catalogs": {
            "catalog_models.json": [model()] if entries is None else entries,
            "catalog_unsupported.json": [],
            "catalog_profiles.json": [
                {
                    "profile_key": "basic",
                    "size": 1,
                    "dev_dpi": 203,
                    "protocol_default": {"type": "tiny"},
                    "paper_presets": ["plain"],
                    "stream": {"chunk_size": 180, "delay_ms": 4},
                    "print_defaults": {
                        "speed": {"image": 10, "text": 12},
                        "energy": {
                            "image": {"low": 5000, "middle": 6000, "high": 7000}
                        },
                    },
                }
            ],
            "catalog_paper_presets.json": {
                "plain": {
                    "paper_width_px": 384,
                    "render_width_px": 360,
                    "left_padding_px": 24,
                }
            },
            "catalog_origin_apps.json": {
                "org.vendor.one": "Source app",
                "org.vendor.two": "Second app",
            },
        },
    }


class CatalogSchemaVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        PrinterModelRegistry._cache.clear()
        self.addCleanup(PrinterModelRegistry._cache.clear)
        self.addCleanup(self.temporary.cleanup)

    def write_bundle(self, data: dict[str, Any], root: Path | None = None) -> Path:
        root = self.root if root is None else root
        root.mkdir(parents=True, exist_ok=True)
        (root / "catalog_snapshot.json").write_text(json.dumps(data), encoding="utf-8")
        return root

    def load_bundle(self, data: dict[str, Any]) -> PrinterModelRegistry:
        self.write_bundle(data)
        with patch.object(catalog, "DATA_DIR", self.root):
            return PrinterModelRegistry.load()

    def write_legacy(self, data: dict[str, Any]) -> tuple[Path, Path, Path, Path]:
        for name, value in data["catalogs"].items():
            (self.root / name).write_text(json.dumps(value), encoding="utf-8")
        (self.root / "catalog_source.json").write_text(
            json.dumps(data["source"]), encoding="utf-8"
        )
        return (
            self.root / "catalog_models.json",
            self.root / "catalog_profiles.json",
            self.root / "catalog_paper_presets.json",
            self.root / "catalog_unsupported.json",
        )

    def test_legacy_nested_fixture_preserves_names_profile_and_preset_defaults(
        self,
    ) -> None:
        data = bundle(
            [
                model(
                    "legacy",
                    marketing_name="Old name",
                    origin_app_packages=["org.vendor.one"],
                    detections=[
                        {
                            "name": "BT Name",
                            "detection": {
                                "exact_names": ["BT Name"],
                                "prefixes": ["BT_"],
                            },
                        },
                    ],
                )
            ]
        )
        paths = self.write_legacy(data)
        with patch.object(catalog, "SOURCE_PATH", self.root / "catalog_source.json"):
            registry = PrinterModelRegistry.load(*paths)
        match = registry.detect_with_origin(" B T Name ")
        assert match is not None
        parsed = match.model
        self.assertEqual(parsed.head_name, "BT Name")
        self.assertEqual(parsed.marketing_name, "Old name")
        self.assertEqual(parsed.origin_app_packages, ("org.vendor.one",))
        self.assertEqual(
            (parsed.profile_key, parsed.img_mtu, parsed.interval_ms), ("basic", 180, 4)
        )
        self.assertEqual(
            (parsed.img_print_speed, parsed.text_print_speed, parsed.moderation_energy),
            (10, 12, 6000),
        )
        self.assertEqual(
            parsed.detection_rules[0].whitespace_mode, WhitespaceMode.REMOVE
        )
        preset = parsed.paper_preset()
        self.assertEqual(
            (preset.paper_width_px, preset.render_width_px, preset.left_padding_px),
            (384, 360, 24),
        )
        self.assertIsNone(preset.render_height_px)
        self.assertEqual(preset.rotation_degrees, 0)

    def test_flat_detection_keeps_every_alias_prefix_and_mac_constraint(self) -> None:
        registry = self.load_bundle(
            bundle(
                [
                    model(
                        "internal",
                        detections=[
                            {
                                "exact_names": ["First", "Second"],
                                "prefixes": ["P_", "Q-"],
                                "mac_suffixes": ["59", "AB"],
                            }
                        ],
                    )
                ]
            )
        )
        parsed = registry.get("internal")
        assert parsed is not None
        self.assertEqual(parsed.head_name, "First")
        self.assertEqual(parsed.detection_rules[0].exact_names, ("First", "Second"))
        for name in ("First", "Second", "P_1234", "Q-1234"):
            for address in ("00:11:22:33:44:59", "00-11-22-33-44-AB"):
                with self.subTest(name=name, address=address):
                    self.assertIsNotNone(registry.detect_with_origin(name, address))
        for address in (
            None,
            "00:11:22:33:44:60",
            "F4B3C8E3-C284-9C3A-C549-D786345CB559",
        ):
            with self.subTest(address=address):
                self.assertIsNone(registry.detect_with_origin("Second", address))
        self.assertIsNone(registry.detect_with_origin("internal", "00:11:22:33:44:59"))

    def test_flat_display_uses_marketing_then_public_exact_or_prefix(self) -> None:
        registry = self.load_bundle(
            bundle(
                [
                    model(
                        "marketing",
                        detections=[
                            {
                                "exact_names": ["Advert"],
                                "marketing_names": ["Shop name", "Other name"],
                            }
                        ],
                    ),
                    model("exact", detections=[{"exact_names": ["Exact_"]}]),
                    model("prefix", detections=[{"prefixes": ["Prefix-"]}]),
                ]
            )
        )
        self.assertEqual(
            [item.head_name for item in registry.models],
            ["Shop name", "Exact", "Prefix"],
        )
        self.assertIsNone(registry.detect_with_origin("Shop name"))

    def test_modern_metadata_and_paper_geometry_are_retained(self) -> None:
        data = bundle(
            [
                model(
                    marketing_names=["Main", "Secondary"],
                    origin_ids=["org.vendor.one", "org.vendor.two"],
                    detections=[
                        {"exact_names": ["BT"], "marketing_names": ["Detector market"]},
                    ],
                )
            ]
        )
        data["catalogs"]["catalog_paper_presets.json"]["plain"].update(
            render_height_px=240, rotation_degrees=90
        )
        parsed = self.load_bundle(data).models[0]
        self.assertEqual(
            parsed.marketing_names, ("Main", "Secondary", "Detector market")
        )
        self.assertEqual(parsed.marketing_name, "Main")
        self.assertEqual(parsed.origin_ids, ("org.vendor.one", "org.vendor.two"))
        self.assertEqual(parsed.origin_app_packages, parsed.origin_ids)
        self.assertEqual(parsed.paper_preset().render_height_px, 240)
        self.assertEqual(parsed.paper_preset().rotation_degrees, 90)

    def test_modern_runtime_profile_and_pipeline_values_keep_existing_behavior(
        self,
    ) -> None:
        data = bundle([model(profile_runtime_preset_key="tuned")])
        profile = data["catalogs"]["catalog_profiles.json"][0]
        profile["protocol_default"] = {"type": "v5g", "variant": "variant-name"}
        profile["default_image_pipeline"] = {"formats": ["bw1"], "encoding": "v5g_dot"}
        profile["print_defaults"]["density"] = {
            "image": {"low": 80, "middle": 90, "high": 100}
        }
        profile["runtime_presets"] = [
            {
                "key": "tuned",
                "control_algorithm": "algorithm",
                "capabilities": {"speed": True},
                "density": {"image": {"low": 100, "middle": 130, "high": 150}},
            }
        ]
        parsed = self.load_bundle(data).models[0]
        self.assertEqual(parsed.protocol_variant, "variant-name")
        self.assertEqual(parsed.runtime_variant, "algorithm")
        self.assertEqual(parsed.runtime_density_profile_key, "tuned")
        self.assertEqual(
            parsed.runtime_density, profile["runtime_presets"][0]["density"]
        )
        self.assertEqual(parsed.profile_density, profile["print_defaults"]["density"])
        self.assertEqual(parsed.runtime_capabilities, {"speed": True})
        self.assertEqual(
            (parsed.min_density, parsed.default_density, parsed.max_density),
            (100, 130, 150),
        )
        self.assertEqual(parsed.image_pipeline.encoding.value, "v5g_dot")

    def test_whitespace_modes_match_and_display_consistently(self) -> None:
        for mode, accepted, rejected in (
            ("remove", ["AB", " A\t B ", "a b"], ["AC"]),
            ("trim", ["A B", " A B ", "a b"], ["AB", "A  B", "A\tB"]),
            ("preserve", [" A B ", " a b "], ["A B", "AB", " A  B "]),
        ):
            with self.subTest(mode=mode):
                PrinterModelRegistry._cache.clear()
                registry = self.load_bundle(
                    bundle(
                        [
                            model(
                                detections=[{"exact_names": [" A B "]}],
                                whitespace_mode=mode,
                            )
                        ]
                    )
                )
                rule = registry.models[0].detection_rules[0]
                # Flat public names trim their outer whitespace. Matching itself
                # uses the exact trigger and each model's normalization policy.
                for name in accepted:
                    self.assertIsNotNone(registry.detect_with_origin(name), name)
                for name in rejected:
                    self.assertIsNone(registry.detect_with_origin(name), name)
                display_query = " A B " if mode != "preserve" else "A B"
                self.assertIsNotNone(registry.get_by_head_name(display_query))
                if mode == "preserve":
                    self.assertIsNone(registry.get_by_head_name(" A B "))
                self.assertEqual(rule.whitespace_mode.value, mode)

    def test_whitespace_mode_applies_to_prefixes_and_specificity(self) -> None:
        remove = DetectionRule(
            "remove", prefixes=(" A B_",), whitespace_mode=WhitespaceMode.REMOVE
        )
        trim = DetectionRule(
            "trim", prefixes=(" A B_",), whitespace_mode=WhitespaceMode.TRIM
        )
        preserve = DetectionRule(
            "preserve", prefixes=(" A B_",), whitespace_mode=WhitespaceMode.PRESERVE
        )
        self.assertIsNotNone(remove.match_score("AB_12", None, casefold=False))
        self.assertIsNone(trim.match_score("AB_12", None, casefold=False))
        self.assertIsNotNone(trim.match_score(" A B_12 ", None, casefold=False))
        self.assertIsNone(preserve.match_score("A B_12", None, casefold=False))
        for rule, name, expected_length in (
            (remove, "AB_12", 2),
            (trim, "A B_12", 3),
            (preserve, " A B_12", 4),
        ):
            score = rule.match_score(name, None, casefold=False)
            assert score is not None
            self.assertEqual(score[0], expected_length)

    def test_shared_group_vetoes_supported_unsupported_and_deferred_matches(
        self,
    ) -> None:
        for category in ("supported", "unsupported", "deferred"):
            with self.subTest(category=category):
                PrinterModelRegistry._cache.clear()
                first = model(
                    "first",
                    detection_ambiguity_group="family",
                    detections=[{"exact_names": ["SharedLong", "Unique"]}],
                )
                second = model(
                    "second",
                    detection_ambiguity_group="family",
                    detections=[{"prefixes": ["Shared"]}],
                )
                data = bundle([first])
                if category == "unsupported":
                    data["catalogs"]["catalog_unsupported.json"] = [second]
                else:
                    if category == "deferred":
                        second["protocol_override"] = {"type": "future_family"}
                    data["catalogs"]["catalog_models.json"].append(second)
                registry = self.load_bundle(data)
                self.assertEqual(registry.models[0].detection_ambiguity_group, "family")
                self.assertIsNone(registry.detect_with_origin("SharedLong"))
                self.assertIsNotNone(registry.detect_with_origin("Unique"))

    def test_shared_group_cannot_be_bypassed_by_case_or_registration_order(
        self,
    ) -> None:
        entries = [
            model(
                "first",
                detection_ambiguity_group="family",
                detections=[{"exact_names": ["Name"]}],
            ),
            model(
                "second",
                detection_ambiguity_group="family",
                detections=[{"exact_names": ["NAME"]}],
            ),
        ]
        for order in (entries, list(reversed(entries))):
            PrinterModelRegistry._cache.clear()
            registry = self.load_bundle(bundle(order))
            self.assertIsNone(registry.detect_with_origin("Name"))
            self.assertIsNone(registry.detect_with_origin("NAME"))

    def test_distinct_or_empty_groups_keep_existing_specificity_selection(self) -> None:
        for group in (None, "", "different"):
            PrinterModelRegistry._cache.clear()
            registry = self.load_bundle(
                bundle(
                    [
                        model(
                            "first",
                            detection_ambiguity_group="one",
                            detections=[{"exact_names": ["LongName"]}],
                        ),
                        model(
                            "second",
                            detection_ambiguity_group=group,
                            detections=[{"prefixes": ["Long"]}],
                        ),
                    ]
                )
            )
            match = registry.detect_with_origin("LongName")
            assert match is not None
            self.assertEqual(match.model.model_no, "first")

    def test_existing_ties_deferred_and_unsupported_vetoes_still_apply(self) -> None:
        cases = []
        tied = bundle(
            [
                model("first", detections=[{"exact_names": ["Name"]}]),
                model("second", detections=[{"exact_names": ["Name"]}]),
            ]
        )
        cases.append((tied, "Name"))
        unsupported = bundle([model("first", detections=[{"prefixes": ["N"]}])])
        unsupported["catalogs"]["catalog_unsupported.json"] = [
            model("unsupported", detections=[{"exact_names": ["Name"]}])
        ]
        cases.append((unsupported, "Name"))
        deferred = bundle(
            [
                model("first", detections=[{"exact_names": ["Name"]}]),
                model(
                    "second",
                    protocol_override={"type": "future_family"},
                    detections=[{"exact_names": ["Name"]}],
                ),
            ]
        )
        cases.append((deferred, "Name"))
        for data, name in cases:
            PrinterModelRegistry._cache.clear()
            self.assertIsNone(self.load_bundle(data).detect_with_origin(name))

    def test_default_paths_prefer_bundle_and_bundle_source(self) -> None:
        data = bundle()
        self.write_bundle(data)
        with (
            patch.object(catalog, "DATA_DIR", self.root),
            patch.object(catalog, "SOURCE_PATH", self.root / "missing-source.json"),
        ):
            registry = PrinterModelRegistry.load()
        self.assertEqual(
            registry.source_metadata,
            {
                **data["source"],
                "selected_updates": [
                    {
                        "commit": "3bd80bac89f8894e143ee867c63683b6c7f2f02b",
                        "base_commit": data["source"]["commit"],
                        "scope": "PrintMaster ownership",
                    }
                ],
            },
        )
        self.assertEqual([item.model_no for item in registry.models], ["modern"])

    def test_explicit_custom_paths_keep_legacy_reads_even_with_bundle_present(
        self,
    ) -> None:
        paths = self.write_legacy(bundle([model("legacy")]))
        self.write_bundle(bundle([model("bundle")]))
        with (
            patch.object(catalog, "DATA_DIR", self.root),
            patch.object(catalog, "SOURCE_PATH", self.root / "catalog_source.json"),
        ):
            registry = PrinterModelRegistry.load(*paths)
        self.assertEqual([item.model_no for item in registry.models], ["legacy"])

    def test_bundle_cache_key_tracks_actual_bundle_path(self) -> None:
        self.write_bundle(bundle([model("one")]), self.root / "one")
        self.write_bundle(bundle([model("two")]), self.root / "two")
        with patch.object(catalog, "DATA_DIR", self.root / "one"):
            first = PrinterModelRegistry.load()
            self.assertIs(first, PrinterModelRegistry.load())
        with patch.object(catalog, "DATA_DIR", self.root / "two"):
            second = PrinterModelRegistry.load()
        self.assertIsNot(first, second)
        self.assertEqual(second.models[0].model_no, "two")
        PrinterModelRegistry._cache.clear()
        with patch.object(catalog, "DATA_DIR", self.root / "one"):
            self.assertIsNot(first, PrinterModelRegistry.load())

    def test_invalid_bundle_fails_closed_instead_of_using_legacy_files(self) -> None:
        for invalid in ({"schema_version": 9}, {**bundle(), "schema_version": 9}):
            PrinterModelRegistry._cache.clear()
            self.write_bundle(invalid)
            with (
                patch.object(catalog, "DATA_DIR", self.root),
                self.assertRaises(ValueError),
            ):
                PrinterModelRegistry.load()
        (self.root / "catalog_snapshot.json").write_text("{broken", encoding="utf-8")
        with (
            patch.object(catalog, "DATA_DIR", self.root),
            self.assertRaises(ValueError),
        ):
            PrinterModelRegistry.load()

    def test_modern_unknown_and_dedicated_families_remain_deferred(self) -> None:
        entries = [model("active")]
        for family in ("future_protocol", "dck", "niimbot", "phomemo_esc"):
            entries.append(model(family, protocol_override={"type": family}))
        registry = self.load_bundle(bundle(entries))
        self.assertEqual([item.model_no for item in registry.models], ["active"])
        self.assertEqual(registry.models[0].protocol_family, ProtocolFamily.LEGACY)
        self.assertEqual(registry.deferred_model_count, 4)
        for family in ("future_protocol", "dck", "niimbot", "phomemo_esc"):
            self.assertIsNone(registry.get(family))
            self.assertIsNone(registry.detect_with_origin(family))

    def test_parser_rejects_malformed_nested_shapes_without_typing_suppression(
        self,
    ) -> None:
        for changed in (
            model(detections="bad"),
            model(detections=[{"exact_names": "bad"}]),
            model(protocol_override=[]),
        ):
            PrinterModelRegistry._cache.clear()
            paths = self.write_legacy(bundle([changed]))
            with (
                patch.object(catalog, "SOURCE_PATH", self.root / "catalog_source.json"),
                self.assertRaises(ValueError),
            ):
                PrinterModelRegistry.load(*paths)
        data = copy.deepcopy(bundle())
        data["catalogs"]["catalog_profiles.json"][0]["stream"] = []
        paths = self.write_legacy(data)
        with (
            patch.object(catalog, "SOURCE_PATH", self.root / "catalog_source.json"),
            self.assertRaises(ValueError),
        ):
            PrinterModelRegistry.load(*paths)


if __name__ == "__main__":
    unittest.main()
