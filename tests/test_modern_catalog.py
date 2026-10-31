from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from catlabel.vendors.generic import models as catalog
from catlabel.vendors.generic.catalog_snapshot import (
    load_snapshot,
    policy_sha256,
    validate_snapshot,
)
from catlabel.vendors.generic.models import PrinterModelRegistry
from tests.test_catalog_schema_versions import bundle, model
from tests.test_catalog_snapshot import (
    _git,
    _init_repository,
    _snapshot,
    _valid_catalogs,
)
from tools import sync_timiniprint_catalog as publisher


def modern_bundle(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    data = bundle(entries)
    old_catalogs = data["catalogs"]
    policy_models = old_catalogs.pop("catalog_unsupported.json")
    source = copy.deepcopy(data["source"])
    source["files"] = {
        "catalog_unsupported.json": source["files"].pop("catalog_unsupported.json")
    }
    data["source"]["files"].pop("catalog_unsupported.json")
    data["schema_version"] = 2
    data["detection_policy"] = {
        "source": source,
        "models": policy_models,
        "origins": copy.deepcopy(old_catalogs["catalog_origin_apps.json"]),
        "sha256": policy_sha256(
            policy_models, old_catalogs["catalog_origin_apps.json"]
        ),
    }
    return data


def set_policy(data: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    policy = data["detection_policy"]
    policy["models"] = entries
    policy["sha256"] = policy_sha256(entries, policy["origins"])


class ModernCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        PrinterModelRegistry._cache.clear()
        self.addCleanup(PrinterModelRegistry._cache.clear)

    def load(
        self, data: dict[str, Any], *, overlay: bool = False
    ) -> PrinterModelRegistry:
        PrinterModelRegistry._cache.clear()
        (self.root / "catalog_snapshot.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        if overlay:
            (self.root / catalog.LUCK_UPDATE_FILENAME).write_text(
                "{malformed", encoding="utf-8"
            )
        with patch.object(catalog, "DATA_DIR", self.root):
            return PrinterModelRegistry.load()

    def test_v2_preserves_records_and_separate_policy_provenance(self) -> None:
        data = modern_bundle()
        before = copy.deepcopy(data)
        self.assertIs(validate_snapshot(data), data)
        registry = self.load(data, overlay=True)
        self.assertEqual(registry.models[0].model_no, "modern")
        self.assertEqual(data, before)
        self.assertEqual(
            registry.source_metadata["detection_policy"],
            {
                "source": data["detection_policy"]["source"],
                "sha256": data["detection_policy"]["sha256"],
            },
        )
        updates = registry.source_metadata["selected_updates"]
        assert isinstance(updates, list)
        self.assertFalse(any(item["scope"] == "Luck A4" for item in updates))

    def test_v1_still_validates_luck_overlay_strictly(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            self.load(bundle(), overlay=True)

    def test_known_alternate_raster_formats_keep_their_model_available(self) -> None:
        data = modern_bundle()
        profile = data["catalogs"]["catalog_profiles.json"][0]
        profile["protocol_default"] = {"type": "v5x"}
        profile["default_image_pipeline"] = {
            "encoding": "v5x_dot",
            "formats": ["bw1", "gray4", "gray8"],
        }
        registry = self.load(data)
        parsed = registry.get("modern")
        assert parsed is not None
        self.assertEqual(
            tuple(fmt.value for fmt in parsed.image_pipeline.formats),
            ("bw1", "gray4", "gray8"),
        )
        profile["default_image_pipeline"]["formats"] = ["gray8", "bw1"]
        self.assertIsNone(self.load(data).get("modern"))

    def test_policy_overlap_defers_model_by_key_before_protocol_parse(self) -> None:
        data = modern_bundle([model("same")])
        set_policy(data, [model("same")])
        # Invalid protocol would fail parsing if policy deferral happened too late.
        data["catalogs"]["catalog_profiles.json"][0]["protocol_default"] = None
        registry = self.load(data)
        self.assertEqual(registry.deferred_model_count, 1)
        self.assertIsNone(registry.get("same"))
        self.assertIsNone(registry.detect_with_origin("same"))

    def test_policy_equal_score_vetoes_v2_and_preserves_v1_precedence(self) -> None:
        supported = model("first", detections=[{"exact_names": ["Shared"]}])
        veto = model("veto", detections=[{"exact_names": ["Shared"]}])
        old = bundle([supported])
        old["catalogs"]["catalog_unsupported.json"] = [veto]
        self.assertIsNotNone(self.load(old).detect_with_origin("Shared"))
        new = modern_bundle([supported])
        set_policy(new, [veto])
        self.assertIsNone(self.load(new).detect_with_origin("Shared"))

    def test_manufacturer_suffix_and_length_must_match_the_same_payload(self) -> None:
        data = modern_bundle(
            [
                model(
                    "special",
                    detections=[
                        {
                            "exact_names": ["BQ17"],
                            "manufacturer_data_suffixes": ["59"],
                            "manufacturer_data_lengths": [5, 7],
                        }
                    ],
                ),
                model("fallback", detections=[{"prefixes": ["BQ"]}]),
            ]
        )
        registry = self.load(data)
        parsed = registry.get("special")
        assert parsed is not None
        rule = parsed.detection_rules[0]
        self.assertEqual(rule.manufacturer_data_lengths, (5, 7))
        self.assertEqual(rule.manufacturer_data_suffixes, ("59",))
        for evidence in (
            None,
            {},
            {1: b"\x59"},
            {1: b"1234\x58"},
            {1: b"1234\x58", 2: b"\x59"},
        ):
            with self.subTest(evidence=evidence):
                # A MAC suffix can never supply manufacturer evidence.
                self.assertIsNone(
                    registry.detect_with_origin(
                        "BQ17", "00:11:22:33:44:59", manufacturer_data=evidence
                    )
                )
        for payload in (b"1234\x59", b"123456\x59"):
            evidence = {0x1234: payload}
            match = registry.detect_with_origin("BQ17", manufacturer_data=evidence)
            assert match is not None
            self.assertEqual(match.model.model_no, "special")
            self.assertIs(
                registry.detect_from_device_name("BQ17", manufacturer_data=evidence),
                parsed,
            )
            self.assertIsNotNone(
                rule.match_score(
                    "BQ17", None, casefold=False, manufacturer_data=evidence
                )
            )
        self.assertIsNotNone(registry.detect_with_origin("BQother"))

    def test_deferred_manufacturer_rule_prevents_missing_evidence_fallback(
        self,
    ) -> None:
        data = modern_bundle(
            [
                model(
                    "unimplemented",
                    protocol_override={"type": "future"},
                    detections=[
                        {
                            "exact_names": ["MX01"],
                            "manufacturer_data_suffixes": ["59"],
                            "manufacturer_data_lengths": [5],
                        }
                    ],
                ),
                model("fallback", detections=[{"prefixes": ["MX"]}]),
            ]
        )
        registry = self.load(data)
        self.assertIsNone(registry.detect_with_origin("MX01"))
        self.assertIsNone(
            registry.detect_with_origin("MX01", manufacturer_data={1: b"1234\x59"})
        )

    def test_substrings_require_original_case_fullmatch_regex(self) -> None:
        pattern = r"(?s:(?-i:(?!.*(?:LE|P11|P2|P3|P5|YHK)).*(?:P1).*))"
        data = modern_bundle(
            [
                model(
                    "toprint",
                    detections=[{"substrings": ["P1"], "name_pattern": pattern}],
                )
            ]
        )
        registry = self.load(data)
        for name in ("P1", "xxP1xyz", " x x P1 "):
            self.assertIsNotNone(registry.detect_with_origin(name), name)
        for name in ("p1", "LEP1", "P11", "P1P2", "P3P1", "YHKP1", "x" * 513 + "P1"):
            self.assertIsNone(registry.detect_with_origin(name), name)
        rule = registry.models[0].detection_rules[0]
        self.assertEqual(rule.substrings, ("P1",))
        self.assertEqual(rule.name_pattern, pattern)

    def test_unknown_variant_encoding_format_or_geometry_is_deferred(self) -> None:
        for change in (
            "variant",
            "encoding",
            "wrong_encoding",
            "format",
            "unknown_pipeline_field",
            "unknown_protocol_field",
            "top_padding",
            "raster_height",
            "missing_required_variant",
        ):
            with self.subTest(change=change):
                data = modern_bundle()
                profile = data["catalogs"]["catalog_profiles.json"][0]
                preset = data["catalogs"]["catalog_paper_presets.json"]["plain"]
                if change == "variant":
                    profile["protocol_default"]["packets_type"] = "future"
                elif change in (
                    "encoding",
                    "wrong_encoding",
                    "format",
                    "unknown_pipeline_field",
                ):
                    profile["default_image_pipeline"] = {
                        "formats": ["bw1"],
                        "encoding": "tiny_raw",
                    }
                    if change == "encoding":
                        profile["default_image_pipeline"]["encoding"] = "future"
                    elif change == "wrong_encoding":
                        profile["default_image_pipeline"]["encoding"] = "v5x_dot"
                    elif change == "format":
                        profile["default_image_pipeline"]["formats"] = ["gray8"]
                    else:
                        profile["default_image_pipeline"]["future_option"] = True
                elif change == "unknown_protocol_field":
                    profile["protocol_default"]["future_option"] = True
                elif change == "top_padding":
                    preset.update(top_padding_px=20, raster_height_px=100)
                elif change == "raster_height":
                    preset["raster_height_px"] = 100
                else:
                    profile["protocol_default"] = {"type": "yk_astra_p1"}
                registry = self.load(data)
                self.assertEqual(registry.deferred_model_count, 1)
                self.assertIsNone(registry.get("modern"))
                self.assertIsNone(registry.detect_with_origin("modern"))

    def test_new_geometry_is_retained_by_parser(self) -> None:
        preset = PrinterModelRegistry._parse_paper_preset(
            "fixed",
            {
                "paper_width_px": 384,
                "render_width_px": 360,
                "render_height_px": 80,
                "raster_height_px": 100,
                "top_padding_px": 20,
            },
        )
        self.assertEqual(
            (preset.render_height_px, preset.raster_height_px, preset.top_padding_px),
            (80, 100, 20),
        )

    def test_new_detection_and_geometry_constraints_are_validated(self) -> None:
        invalid_rules = [
            {"substrings": ["P1"]},
            {"substrings": "P1", "name_pattern": ".*"},
            {"prefixes": ["P"], "name_pattern": "("},
            {"prefixes": ["P"], "name_pattern": 1},
            {"prefixes": ["P"], "name_pattern": None},
            {
                "prefixes": ["P"],
                "manufacturer_data_suffixes": [],
                "manufacturer_data_lengths": [],
            },
            {"name": "P", "detection": {}, "future_constraint": True},
            {
                "prefixes": ["P"],
                "manufacturer_data_suffixes": ["5"],
                "manufacturer_data_lengths": [5],
            },
            {
                "prefixes": ["P"],
                "manufacturer_data_suffixes": ["ZZ"],
                "manufacturer_data_lengths": [5],
            },
            {
                "prefixes": ["P"],
                "manufacturer_data_suffixes": ["59"],
                "manufacturer_data_lengths": [True],
            },
            {
                "prefixes": ["P"],
                "manufacturer_data_suffixes": ["59"],
                "manufacturer_data_lengths": [0],
            },
            {"prefixes": ["P"], "manufacturer_data_suffixes": ["59"]},
            {"prefixes": ["P"], "manufacturer_data_lengths": [5]},
            {"prefixes": ["P"], "future_constraint": True},
        ]
        for rule in invalid_rules:
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                validate_snapshot(modern_bundle([model(detections=[rule])]))
        for geometry in (
            {"top_padding_px": -1},
            {"top_padding_px": True},
            {"raster_height_px": 0},
            {"raster_height_px": None},
            {"top_padding_px": 1},
            {"render_height_px": 80, "top_padding_px": 21, "raster_height_px": 100},
            {"raster_height_px": 100, "max_height_px": 99},
            {"render_height_px": 100, "max_height_px": 99},
            {"render_width_px": 384},
            {"future_padding_px": 1},
        ):
            data = modern_bundle()
            data["catalogs"]["catalog_paper_presets.json"]["plain"].update(geometry)
            with self.subTest(geometry=geometry), self.assertRaises(ValueError):
                validate_snapshot(data)

    def test_policy_origins_remain_independent_of_current_upstream_origins(
        self,
    ) -> None:
        data = modern_bundle()
        data["catalogs"]["catalog_origin_apps.json"] = {}
        set_policy(data, [model("veto", origin_ids=["org.vendor.one"])])
        registry = self.load(data)
        self.assertIsNone(registry.detect_with_origin("veto"))
        self.assertIsNotNone(registry.detect_with_origin("modern"))

    def test_policy_validation_covers_provenance_records_and_hash(self) -> None:
        for invalidation in (
            "hash",
            "repository",
            "files",
            "models",
            "origins",
            "extra",
            "missing_policy",
        ):
            data = modern_bundle()
            policy = data["detection_policy"]
            if invalidation == "hash":
                policy["sha256"] = "0" * 64
            elif invalidation == "repository":
                policy["source"]["repository"] = "https://example.invalid"
            elif invalidation == "files":
                policy["source"]["files"]["catalog_models.json"] = "fake.json"
            elif invalidation == "models":
                set_policy(data, [model("unsupported", origin_ids=["missing-origin"])])
            elif invalidation == "origins":
                policy["origins"] = []
            elif invalidation == "extra":
                policy["extra"] = True
            else:
                data.pop("detection_policy")
            with self.subTest(invalidation=invalidation), self.assertRaises(ValueError):
                validate_snapshot(data)

    def test_sync_four_files_requires_valid_policy_and_preserves_output_on_failures(
        self,
    ) -> None:
        repo = self.root / "upstream"
        _init_repository(repo, _valid_catalogs())
        _git(repo, "rm", publisher.SOURCE_PATHS["catalog_unsupported.json"])
        _git(repo, "commit", "--quiet", "-m", "four-file catalog")
        output = self.root / "candidate.json"
        policy_path = self.root / "policy.json"
        prior = _snapshot(_valid_catalogs())
        policy_path.write_text(json.dumps(prior), encoding="utf-8")
        publisher.sync(
            "HEAD", repo, output_path=output, policy_snapshot_path=policy_path
        )
        candidate = load_snapshot(output)
        self.assertEqual(candidate["schema_version"], 2)
        self.assertEqual(set(candidate["source"]["files"]), set(candidate["catalogs"]))
        self.assertNotIn("catalog_unsupported.json", candidate["catalogs"])
        self.assertEqual(
            candidate["detection_policy"]["models"],
            prior["catalogs"]["catalog_unsupported.json"],
        )
        # An existing v2 policy is retained independently and byte-for-byte in value.
        v2_prior = output.read_bytes()
        publisher.sync("HEAD", repo, output_path=output, policy_snapshot_path=output)
        self.assertEqual(output.read_bytes(), v2_prior)
        for failure in (
            "missing_policy",
            "invalid_json",
            "bad_hash",
            "missing_upstream_file",
        ):
            output.write_bytes(v2_prior)
            policy_path.write_text(json.dumps(candidate), encoding="utf-8")
            selected_policy = policy_path
            if failure == "missing_policy":
                selected_policy = self.root / "missing.json"
            elif failure == "invalid_json":
                policy_path.write_text("{broken", encoding="utf-8")
            elif failure == "bad_hash":
                broken = copy.deepcopy(candidate)
                broken["detection_policy"]["sha256"] = "bad"
                policy_path.write_text(json.dumps(broken), encoding="utf-8")
            else:
                _git(repo, "rm", publisher.SOURCE_PATHS["catalog_profiles.json"])
                _git(repo, "commit", "--quiet", "-m", "missing profile file")
            expected_error = (
                FileNotFoundError
                if failure == "missing_policy"
                else subprocess.CalledProcessError
                if failure == "missing_upstream_file"
                else ValueError
            )
            with self.subTest(failure=failure), self.assertRaises(expected_error):
                publisher.sync(
                    "HEAD",
                    repo,
                    output_path=output,
                    policy_snapshot_path=selected_policy,
                )
            self.assertEqual(output.read_bytes(), v2_prior)
            self.assertEqual(list(self.root.glob(".candidate.json.*.tmp")), [])

    def test_actual_pinned_four_file_catalog_when_available(self) -> None:
        source_root = Path("/tmp/catlabel-upstream-port-2026-10-31/catalogs")
        if not source_root.is_dir():
            self.skipTest(
                "parent-acquired pinned v0.9.1 source artifact is unavailable"
            )
        data = modern_bundle()
        filenames = {
            "catalog_models.json": "printer_models.json",
            "catalog_profiles.json": "printer_profiles.json",
            "catalog_paper_presets.json": "printer_paper_presets.json",
            "catalog_origin_apps.json": "origins.json",
        }
        active = load_snapshot(catalog.DATA_DIR / "catalog_snapshot.json")
        policy = data["detection_policy"]
        policy["source"] = {
            **active["source"],
            "files": {
                "catalog_unsupported.json": active["source"]["files"][
                    "catalog_unsupported.json"
                ]
            },
        }
        policy["models"] = active["catalogs"]["catalog_unsupported.json"]
        policy["origins"] = active["catalogs"]["catalog_origin_apps.json"]
        policy["sha256"] = policy_sha256(policy["models"], policy["origins"])
        data["source"].update(
            revision="v0.9.1",
            commit="6a71ecf7742e36be05bed7f4e52c4822cccced68",
            files={
                dest: "timiniprint/data/" + source for dest, source in filenames.items()
            },
        )
        data["catalogs"] = {
            dest: json.loads((source_root / source).read_text(encoding="utf-8"))
            for dest, source in filenames.items()
        }
        registry = self.load(data)
        self.assertEqual(
            len(registry.models) + registry.deferred_model_count,
            len(data["catalogs"]["catalog_models.json"]),
        )
        self.assertGreater(len(registry.models), 100)
        self.assertIsNone(registry.get("xeasylabel_hp6_c"))
        self.assertIsNone(registry.detect_with_origin("BQ17"))
        self.assertIsNotNone(registry.detect_with_origin("XXP1"))
        self.assertIsNone(registry.detect_with_origin("LEP1"))
