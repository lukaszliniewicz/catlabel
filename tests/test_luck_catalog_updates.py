from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from catlabel.protocol.family import ProtocolFamily
from catlabel.raster import PixelFormat
from catlabel.vendors.generic import models as catalog
from catlabel.vendors.generic.catalog_snapshot import load_snapshot
from catlabel.vendors.generic.catalog_updates import (
    ALLOWED_MODEL_KEYS,
    ALLOWED_PRESET_KEYS,
    ALLOWED_PROFILE_KEYS,
    BASE_COMMIT,
    BASE_PROFILE_KEYS,
    LUCK_UPDATE_COMMIT,
    LUCK_UPDATE_FILENAME,
    apply_luck_updates,
)
from catlabel.vendors.generic.models import PrinterModelRegistry
from tools import sync_luck_catalog as publisher

DATA_DIR = Path(__file__).resolve().parents[1] / "catlabel/vendors/generic/data"
SNAPSHOT = DATA_DIR / "catalog_snapshot.json"
UPDATE_PATH = DATA_DIR / LUCK_UPDATE_FILENAME
BASE_SHA256 = "00e9659ab6b7c012cd8a7309a8c4ac736b4b53878ff1b3d915980624075640e8"


class LuckCatalogUpdatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = load_snapshot(SNAPSHOT)
        self.updates: dict[str, Any] = json.loads(
            UPDATE_PATH.read_text(encoding="utf-8")
        )
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        PrinterModelRegistry._cache.clear()
        self.addCleanup(PrinterModelRegistry._cache.clear)
        self.addCleanup(self.temporary.cleanup)

    def write_fixture(self, updates: object | None = None) -> None:
        (self.root / "catalog_snapshot.json").write_bytes(SNAPSHOT.read_bytes())
        if updates is not None:
            (self.root / LUCK_UPDATE_FILENAME).write_text(
                json.dumps(updates), encoding="utf-8"
            )

    def test_pure_merge_is_idempotent_and_does_not_mutate_or_alias_inputs(self) -> None:
        bundle_before = copy.deepcopy(self.bundle)
        updates_before = copy.deepcopy(self.updates)
        merged = apply_luck_updates(self.bundle, self.updates)
        self.assertEqual(self.bundle, bundle_before)
        self.assertEqual(self.updates, updates_before)
        self.assertEqual(apply_luck_updates(merged, self.updates), merged)
        self.assertEqual(merged["source"], self.bundle["source"])
        merged["catalogs"]["catalog_models.json"][0]["model_key"] = "changed"
        merged["catalogs"]["catalog_paper_presets.json"]["luck_a4_roll_216mm"][
            "label"
        ] = "changed"
        self.assertEqual(self.bundle, bundle_before)
        self.assertEqual(self.updates, updates_before)

    def test_exact_selected_record_sets_and_unrelated_catalogs_are_preserved(
        self,
    ) -> None:
        self.assertEqual(
            {x["model_key"] for x in self.updates["models"]}, ALLOWED_MODEL_KEYS
        )
        self.assertEqual(
            {x["profile_key"] for x in self.updates["profiles"]}, ALLOWED_PROFILE_KEYS
        )
        self.assertEqual(set(self.updates["paper_presets"]), ALLOWED_PRESET_KEYS)
        self.assertEqual(
            (
                len(BASE_PROFILE_KEYS),
                len(ALLOWED_PROFILE_KEYS),
                len(ALLOWED_PRESET_KEYS),
            ),
            (15, 16, 29),
        )
        merged = apply_luck_updates(self.bundle, self.updates)
        old = self.bundle["catalogs"]
        new = merged["catalogs"]
        for name in ("catalog_unsupported.json", "catalog_origin_apps.json"):
            self.assertEqual(new[name], old[name])
        for item in old["catalog_models.json"]:
            if item["model_key"] not in ALLOWED_MODEL_KEYS:
                self.assertIn(item, new["catalog_models.json"])
        for item in old["catalog_profiles.json"]:
            if item["profile_key"] not in ALLOWED_PROFILE_KEYS:
                self.assertIn(item, new["catalog_profiles.json"])
        for key, preset in old["catalog_paper_presets.json"].items():
            self.assertEqual(new["catalog_paper_presets.json"][key], preset)
        self.assertEqual(
            len(new["catalog_models.json"]), len(old["catalog_models.json"]) + 1
        )
        self.assertEqual(
            len(new["catalog_profiles.json"]), len(old["catalog_profiles.json"]) + 1
        )

    def test_schema_pins_and_strict_top_level_keys_are_enforced(self) -> None:
        mutations = [
            {"schema_version": True},
            {"schema_version": 2},
            {"base_commit": "0" * 40},
            {"commit": "v0.8.1"},
            {"commit": "0" * 40},
            {"extra": True},
        ]
        for changes in mutations:
            invalid = {**self.updates, **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                apply_luck_updates(self.bundle, invalid)
        invalid = copy.deepcopy(self.updates)
        del invalid["commit"]
        with self.assertRaises(ValueError):
            apply_luck_updates(self.bundle, invalid)
        invalid_base = copy.deepcopy(self.bundle)
        invalid_base["source"]["commit"] = "1" * 40
        with self.assertRaises(ValueError):
            apply_luck_updates(invalid_base, self.updates)

    def test_unapproved_missing_and_duplicate_model_profile_keys_are_rejected(
        self,
    ) -> None:
        for field, key in (("models", "model_key"), ("profiles", "profile_key")):
            for operation in ("missing", "duplicate", "extra"):
                invalid = copy.deepcopy(self.updates)
                if operation == "missing":
                    invalid[field].pop()
                else:
                    item = copy.deepcopy(invalid[field][0])
                    if operation == "extra":
                        item[key] = "unapproved"
                    invalid[field].append(item)
                with (
                    self.subTest(field=field, operation=operation),
                    self.assertRaises(ValueError),
                ):
                    apply_luck_updates(self.bundle, invalid)

    def test_wrong_protocols_gray_formats_and_encodings_are_rejected(self) -> None:
        for changes in (
            {"protocol_default": {"type": "tiny"}},
            {
                "default_image_pipeline": {
                    "formats": ["gray8"],
                    "encoding": "luck_normal_compressed",
                }
            },
            {
                "default_image_pipeline": {
                    "formats": ["bw1", "gray8"],
                    "encoding": "luck_normal_compressed",
                }
            },
            {
                "default_image_pipeline": {
                    "formats": ["bw1"],
                    "encoding": "luck_normal_gray",
                }
            },
        ):
            invalid = copy.deepcopy(self.updates)
            invalid["profiles"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                apply_luck_updates(self.bundle, invalid)
        for changes in (
            {"protocol_override": {"type": "v5g"}},
            {"protocol_override": {"packets_type": "unimplemented_variant"}},
            {"protocol_override": {"type": "luck_normal_a4", "packets_type": "d80"}},
            {
                "image_pipeline_override": {
                    "formats": ["gray8"],
                    "encoding": "luck_normal_compressed",
                }
            },
        ):
            invalid = copy.deepcopy(self.updates)
            invalid["models"][0].update(changes)
            with self.assertRaises(ValueError):
                apply_luck_updates(self.bundle, invalid)

    def test_approved_profile_keys_cannot_carry_changed_packet_variants(self) -> None:
        for key in ("luck_lujiang_a4", "luck_apa41"):
            invalid = copy.deepcopy(self.updates)
            profile = next(
                item for item in invalid["profiles"] if item["profile_key"] == key
            )
            profile["protocol_default"]["packets_type"] = "unimplemented_variant"
            with self.subTest(profile=key), self.assertRaises(ValueError):
                apply_luck_updates(self.bundle, invalid)

    def test_broken_references_extra_presets_and_modified_originals_are_rejected(
        self,
    ) -> None:
        invalid_values = []
        invalid = copy.deepcopy(self.updates)
        invalid["models"][0]["profile_key"] = "nonexistent"
        invalid_values.append(invalid)
        invalid = copy.deepcopy(self.updates)
        invalid["models"][0]["profile_runtime_preset_key"] = "nonexistent"
        invalid_values.append(invalid)
        invalid = copy.deepcopy(self.updates)
        invalid["profiles"][0]["paper_presets"] = ["nonexistent"]
        invalid_values.append(invalid)
        invalid = copy.deepcopy(self.updates)
        invalid["paper_presets"]["extra"] = copy.deepcopy(
            next(iter(invalid["paper_presets"].values()))
        )
        invalid_values.append(invalid)
        invalid = copy.deepcopy(self.updates)
        invalid["paper_presets"].pop("luck_a4_roll_216mm")
        invalid_values.append(invalid)
        invalid = copy.deepcopy(self.updates)
        invalid["paper_presets"]["tag_2496r"]["paper_width_px"] = 999
        invalid_values.append(invalid)
        invalid = copy.deepcopy(self.updates)
        invalid["paper_presets"]["luck_a4_folder_a4"]["render_height_px"] = 0
        invalid_values.append(invalid)
        for invalid in invalid_values:
            with self.assertRaises(ValueError):
                apply_luck_updates(self.bundle, invalid)

    def test_actual_advertised_names_use_selected_profiles_and_preserve_other_models(
        self,
    ) -> None:
        self.write_fixture()
        with patch.object(catalog, "DATA_DIR", self.root):
            base_registry = PrinterModelRegistry.load()
        registry = PrinterModelRegistry.load()
        for name, model_key, profile_key, dpi, density in (
            ("APA41_123", "luck_apa41", "luck_apa41", 203, 2),
            ("E49_123", "luck_apa49", "luck_lujiang_a4_dense", 203, 3),
            ("APA49_123", "luck_apa49", "luck_lujiang_a4_dense", 203, 3),
            ("APA49H_123", "luck_a49h", "luck_a49h", 300, 3),
        ):
            with self.subTest(name=name):
                match = registry.detect_with_origin(name)
                assert match is not None
                parsed = match.model
                self.assertEqual(
                    (parsed.model_no, parsed.profile_key), (model_key, profile_key)
                )
                self.assertEqual(parsed.protocol_family, ProtocolFamily.LUCK_NORMAL_A4)
                self.assertEqual(
                    (parsed.dev_dpi, parsed.default_density), (dpi, density)
                )
                self.assertEqual(parsed.image_pipeline.formats, (PixelFormat.BW1,))
                self.assertEqual(parsed.print_size, 1648 if dpi == 203 else 2496)
                folder = parsed.paper_preset(
                    "luck_a4_folder_a4" if dpi == 203 else "luck_a4_folder_a4_300dpi"
                )
                self.assertEqual(
                    (folder.render_width_px, folder.render_height_px),
                    (1616, 2300) if dpi == 203 else (2400, 3480),
                )
                self.assertEqual(parsed.min_density, 0)
                self.assertEqual(parsed.max_density, 5)
        for parsed in base_registry.models:
            if (
                parsed.profile_key not in BASE_PROFILE_KEYS
                and parsed.model_no != "luck_apa41"
            ):
                self.assertEqual(registry.get(parsed.model_no), parsed)
        self.assertEqual(
            registry.unsupported_model_count, base_registry.unsupported_model_count
        )
        self.assertEqual(
            registry.deferred_model_count, base_registry.deferred_model_count
        )
        self.assertIsNone(registry.detect_with_origin("D80_123"))
        self.assertEqual(registry.source_metadata["commit"], BASE_COMMIT)
        self.assertEqual(
            registry.source_metadata["selected_updates"],
            [
                {
                    "commit": LUCK_UPDATE_COMMIT,
                    "base_commit": BASE_COMMIT,
                    "scope": "Luck A4",
                },
                {
                    "commit": "3bd80bac89f8894e143ee867c63683b6c7f2f02b",
                    "base_commit": BASE_COMMIT,
                    "scope": "PrintMaster ownership",
                },
            ],
        )

    def test_loader_custom_legacy_paths_ignore_overlay_and_invalid_default_overlay_fails_closed(
        self,
    ) -> None:
        for filename, raw in self.bundle["catalogs"].items():
            (self.root / filename).write_text(json.dumps(raw), encoding="utf-8")
        (self.root / "catalog_source.json").write_text(
            json.dumps(self.bundle["source"]), encoding="utf-8"
        )
        paths = (
            self.root / "catalog_models.json",
            self.root / "catalog_profiles.json",
            self.root / "catalog_paper_presets.json",
            self.root / "catalog_unsupported.json",
        )
        with patch.object(catalog, "SOURCE_PATH", self.root / "catalog_source.json"):
            registry = PrinterModelRegistry.load(*paths)
        self.assertIsNone(registry.get("luck_apa49"))
        self.assertNotIn("selected_updates", registry.source_metadata)
        invalid = {**self.updates, "commit": "0" * 40}
        self.write_fixture(invalid)
        with (
            patch.object(catalog, "DATA_DIR", self.root),
            self.assertRaises(ValueError),
        ):
            PrinterModelRegistry.load()

    def test_cache_key_includes_overlay_presence_and_actual_path(self) -> None:
        self.write_fixture()
        with patch.object(catalog, "DATA_DIR", self.root):
            baseline = PrinterModelRegistry.load()
            self.write_fixture(self.updates)
            updated = PrinterModelRegistry.load()
            self.assertIsNot(updated, baseline)
            self.assertIsNotNone(updated.get("luck_apa49"))
            (self.root / "second_updates.json").write_bytes(
                (self.root / LUCK_UPDATE_FILENAME).read_bytes()
            )
            with patch.object(catalog, "LUCK_UPDATE_FILENAME", "second_updates.json"):
                second = PrinterModelRegistry.load()
            self.assertIsNot(updated, second)

    def test_publisher_reads_only_exact_pins_and_selects_literal_records(self) -> None:
        source_calls = []

        def source(_repository: Path, commit: str, filename: str) -> object:
            source_calls.append((commit, filename))
            if commit == BASE_COMMIT:
                return self.bundle["catalogs"]["catalog_profiles.json"]
            if filename == "printer_models.json":
                return [*self.updates["models"], {"model_key": "unrelated"}]
            if filename == "printer_profiles.json":
                return [*self.updates["profiles"], {"profile_key": "unrelated"}]
            return self.updates["paper_presets"]

        with patch.object(publisher, "_read_source", side_effect=source):
            selected = publisher.build_updates(self.root)
        self.assertEqual(selected, self.updates)
        self.assertEqual(
            source_calls,
            [
                (BASE_COMMIT, "printer_profiles.json"),
                (LUCK_UPDATE_COMMIT, "printer_models.json"),
                (LUCK_UPDATE_COMMIT, "printer_profiles.json"),
                (LUCK_UPDATE_COMMIT, "printer_paper_presets.json"),
            ],
        )
        with (
            patch.object(publisher, "build_updates") as build,
            self.assertRaises(ValueError),
        ):
            publisher.sync("HEAD", self.root)
        build.assert_not_called()

    def test_publication_preserves_bundle_hash_and_atomically_writes_overlay(
        self,
    ) -> None:
        self.assertEqual(hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest(), BASE_SHA256)
        witnesses = {
            path: path.read_bytes() for path in DATA_DIR.glob("catalog_*.json")
        }
        destination = self.root / LUCK_UPDATE_FILENAME
        with patch.object(publisher, "build_updates", return_value=self.updates):
            self.assertEqual(
                publisher.sync(
                    repository_path=self.root,
                    output_path=destination,
                    snapshot_path=SNAPSHOT,
                ),
                LUCK_UPDATE_COMMIT,
            )
        self.assertEqual(
            json.loads(destination.read_text(encoding="utf-8")), self.updates
        )
        for path, original in witnesses.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_failed_validation_fsync_or_replace_keeps_previous_overlay_intact(
        self,
    ) -> None:
        destination = self.root / LUCK_UPDATE_FILENAME
        old = b"old preserved overlay\n"
        for stage in ("validation", "fsync", "replace"):
            destination.write_bytes(old)
            updates = (
                {**self.updates, "commit": "bad"}
                if stage == "validation"
                else self.updates
            )
            function = "os.fsync" if stage == "fsync" else "os.replace"
            with patch.object(publisher, "build_updates", return_value=updates):
                if stage == "validation":
                    with self.assertRaises(ValueError):
                        publisher.sync(
                            repository_path=self.root,
                            output_path=destination,
                            snapshot_path=SNAPSHOT,
                        )
                else:
                    with (
                        patch(
                            f"tools.sync_luck_catalog.{function}",
                            side_effect=OSError("publication failed"),
                        ),
                        self.assertRaises(OSError),
                    ):
                        publisher.sync(
                            repository_path=self.root,
                            output_path=destination,
                            snapshot_path=SNAPSHOT,
                        )
            self.assertEqual(destination.read_bytes(), old)
            self.assertEqual(list(self.root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
