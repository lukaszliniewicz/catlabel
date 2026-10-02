from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from catlabel.vendors.generic.catalog_snapshot import load_snapshot, validate_snapshot
from tools import sync_timiniprint_catalog as publisher


def _valid_catalogs() -> dict[str, Any]:
    return {
        "catalog_models.json": [
            {
                "model_key": "model-a",
                "profile_key": "profile-a",
                "profile_runtime_preset_key": "runtime-a",
                "protocol_override": {"type": "future-protocol"},
                "detections": [{"exact_names": ["MODEL-A"]}],
                "origin_ids": ["app.a"],
            }
        ],
        "catalog_unsupported.json": [
            {
                "model_key": "unsupported-a",
                "profile_key_prediction": "not-a-profile-foreign-key",
                "detections": [{"prefixes": ["UNSUPPORTED"]}],
                "origin_ids": ["app.a"],
            }
        ],
        "catalog_profiles.json": [
            {
                "profile_key": "profile-a",
                "size": 1,
                "dev_dpi": 203,
                "protocol_default": {"type": "another-future-protocol"},
                "paper_presets": ["paper-a"],
                "runtime_presets": [{"key": "runtime-a"}],
            }
        ],
        "catalog_paper_presets.json": {
            "paper-a": {
                "paper_width_px": 320,
                "render_width_px": 300,
                "render_height_px": 400,
                "rotation_degrees": 90,
            }
        },
        "catalog_origin_apps.json": {"app.a": "Example printer app"},
    }


def _git(repository_path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _write_git_file(repository_path: Path, relative_path: str, content: str) -> None:
    path = repository_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_repository(
    repository_path: Path,
    catalogs: dict[str, Any],
    *,
    modern_origins: bool = True,
    legacy_origins: bool = False,
    raw_overrides: dict[str, str] | None = None,
) -> str:
    repository_path.mkdir(parents=True)
    _git(repository_path, "init", "--quiet")
    _git(repository_path, "config", "user.name", "Catalog Test")
    _git(repository_path, "config", "user.email", "catalog-test@example.invalid")

    for destination, source_path in publisher.SOURCE_PATHS.items():
        value = catalogs[destination]
        _write_git_file(
            repository_path,
            source_path,
            (raw_overrides or {}).get(
                destination,
                json.dumps(value, ensure_ascii=False),
            ),
        )

    if modern_origins:
        _write_git_file(
            repository_path,
            publisher.MODERN_ORIGIN_SOURCE,
            (raw_overrides or {}).get(
                publisher.ORIGIN_DESTINATION,
                json.dumps(catalogs[publisher.ORIGIN_DESTINATION], ensure_ascii=False),
            ),
        )
    if legacy_origins:
        _write_git_file(
            repository_path,
            publisher.LEGACY_ORIGIN_SOURCE,
            (raw_overrides or {}).get(
                "legacy_origins.json",
                json.dumps({"app.a": "Legacy printer app"}, ensure_ascii=False),
            ),
        )

    _git(repository_path, "add", ".")
    _git(repository_path, "commit", "--quiet", "-m", "catalog fixture")
    return _git(repository_path, "rev-parse", "HEAD")


def _snapshot(catalogs: dict[str, Any], *, commit: str = "a" * 40) -> dict[str, Any]:
    files = {
        **publisher.SOURCE_PATHS,
        publisher.ORIGIN_DESTINATION: publisher.MODERN_ORIGIN_SOURCE,
    }
    return {
        "schema_version": 1,
        "source": {
            "repository": publisher.UPSTREAM_REPOSITORY,
            "revision": "test-revision",
            "commit": commit,
            "license": "Apache-2.0",
            "files": files,
        },
        "catalogs": catalogs,
    }


def _seed_existing_destination(directory: Path) -> dict[str, bytes]:
    directory.mkdir(parents=True, exist_ok=True)
    filenames = [
        *publisher.SOURCE_PATHS,
        publisher.ORIGIN_DESTINATION,
        "catalog_source.json",
    ]
    filenames.append(publisher.SNAPSHOT_FILENAME)
    existing: dict[str, bytes] = {}
    for filename in filenames:
        content = f"preserve {filename}\n".encode()
        (directory / filename).write_bytes(content)
        existing[filename] = content
    return existing


def _assert_destination_unchanged(directory: Path, previous: dict[str, bytes]) -> None:
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == previous


class CatalogSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.temp_path = Path(self._temporary_directory.name)

    def test_invalid_sources_leave_existing_catalog_files_unchanged(self) -> None:
        failures = (
            "invalid_json",
            "profile_foreign_key",
            "duplicate_model_id",
            "duplicate_profile_id",
            "supported_unsupported_overlap",
            "empty_detection",
            "unknown_origin",
            "runtime_preset_foreign_key",
        )
        for failure in failures:
            with self.subTest(failure=failure):
                case_path = self.temp_path / failure
                case_path.mkdir()
                catalogs = _valid_catalogs()
                raw_overrides: dict[str, str] = {}
                if failure == "invalid_json":
                    raw_overrides["catalog_models.json"] = "{invalid json"
                elif failure == "profile_foreign_key":
                    catalogs["catalog_models.json"][0]["profile_key"] = (
                        "missing-profile"
                    )
                elif failure == "duplicate_model_id":
                    catalogs["catalog_models.json"].append(
                        dict(catalogs["catalog_models.json"][0]),
                    )
                elif failure == "duplicate_profile_id":
                    catalogs["catalog_profiles.json"].append(
                        dict(catalogs["catalog_profiles.json"][0]),
                    )
                elif failure == "supported_unsupported_overlap":
                    catalogs["catalog_unsupported.json"][0]["model_key"] = "model-a"
                elif failure == "empty_detection":
                    catalogs["catalog_models.json"][0]["detections"] = [{}]
                elif failure == "unknown_origin":
                    catalogs["catalog_models.json"][0]["origin_ids"] = ["missing-app"]
                elif failure == "runtime_preset_foreign_key":
                    catalogs["catalog_models.json"][0]["profile_runtime_preset_key"] = (
                        "missing-runtime"
                    )

                repository_path = case_path / "upstream"
                _init_repository(repository_path, catalogs, raw_overrides=raw_overrides)
                destination = case_path / "destination"
                previous = _seed_existing_destination(destination)

                with (
                    mock.patch.object(publisher, "DATA_DIR", destination),
                    self.assertRaises(ValueError),
                ):
                    publisher.sync("HEAD", repository_path=repository_path)

                _assert_destination_unchanged(destination, previous)

    def test_all_sources_are_acquired_before_json_parse_failure(self) -> None:
        repository_path = self.temp_path / "upstream"
        _init_repository(
            repository_path,
            _valid_catalogs(),
            raw_overrides={"catalog_models.json": "{invalid json"},
        )
        destination = self.temp_path / "destination"
        previous = _seed_existing_destination(destination)
        real_run = subprocess.run
        shown_sources: list[str] = []

        def recording_run(*args: Any, **kwargs: Any) -> Any:
            command = args[0] if args else kwargs.get("args")
            if isinstance(command, list):
                command_args = cast(list[str], command)
                if (
                    len(command_args) >= 3
                    and command_args[0] == "git"
                    and command_args[1] == "show"
                ):
                    shown_sources.append(command_args[-1])
            return cast(subprocess.CompletedProcess[str], real_run(*args, **kwargs))

        with (
            mock.patch.object(publisher, "DATA_DIR", destination),
            mock.patch.object(subprocess, "run", side_effect=recording_run),
            self.assertRaises(json.JSONDecodeError),
        ):
            publisher.sync("HEAD", repository_path=repository_path)

        self.assertEqual(len(shown_sources), 5)
        _assert_destination_unchanged(destination, previous)

    def test_missing_origin_sources_fail_after_attempting_all_five_and_preserve_destination(
        self,
    ) -> None:
        repository_path = self.temp_path / "upstream"
        commit = _init_repository(
            repository_path, _valid_catalogs(), modern_origins=False
        )
        destination = self.temp_path / "destination"
        previous = _seed_existing_destination(destination)
        real_run = subprocess.run
        shown_sources: list[str] = []

        def recording_run(*args: Any, **kwargs: Any) -> Any:
            command = args[0] if args else kwargs.get("args")
            if isinstance(command, list):
                command_args = cast(list[str], command)
                if (
                    len(command_args) >= 3
                    and command_args[0] == "git"
                    and command_args[1] == "show"
                ):
                    shown_sources.append(command_args[-1])
            return cast(subprocess.CompletedProcess[str], real_run(*args, **kwargs))

        with (
            mock.patch.object(publisher, "DATA_DIR", destination),
            mock.patch.object(subprocess, "run", side_effect=recording_run),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            publisher.sync("HEAD", repository_path=repository_path)

        self.assertEqual(
            shown_sources,
            [
                f"{commit}:{source}"
                for source in [
                    *publisher.SOURCE_PATHS.values(),
                    publisher.LEGACY_ORIGIN_SOURCE,
                ]
            ],
        )
        _assert_destination_unchanged(destination, previous)

    def test_successful_sync_publishes_one_bundle_and_prefers_modern_origins(
        self,
    ) -> None:
        catalogs = _valid_catalogs()
        repository_path = self.temp_path / "upstream"
        commit = _init_repository(
            repository_path,
            catalogs,
            modern_origins=True,
            legacy_origins=True,
        )
        destination = self.temp_path / "destination"
        previous = _seed_existing_destination(destination)

        with mock.patch.object(publisher, "DATA_DIR", destination):
            self.assertEqual(
                publisher.sync("HEAD", repository_path=repository_path), commit
            )

        snapshot_path = destination / publisher.SNAPSHOT_FILENAME
        snapshot = load_snapshot(snapshot_path)
        self.assertEqual(snapshot["source"]["commit"], commit)
        self.assertEqual(
            snapshot["source"]["files"][publisher.ORIGIN_DESTINATION],
            publisher.MODERN_ORIGIN_SOURCE,
        )
        self.assertEqual(snapshot["catalogs"], catalogs)
        for filename, content in previous.items():
            if filename != publisher.SNAPSHOT_FILENAME:
                self.assertEqual((destination / filename).read_bytes(), content)

    def test_legacy_origins_are_used_only_when_modern_path_is_missing(self) -> None:
        catalogs = _valid_catalogs()
        repository_path = self.temp_path / "upstream"
        _init_repository(
            repository_path,
            catalogs,
            modern_origins=False,
            legacy_origins=True,
        )
        destination = self.temp_path / "destination"

        with mock.patch.object(publisher, "DATA_DIR", destination):
            publisher.sync("HEAD", repository_path=repository_path)

        snapshot = load_snapshot(destination / publisher.SNAPSHOT_FILENAME)
        self.assertEqual(
            snapshot["source"]["files"][publisher.ORIGIN_DESTINATION],
            publisher.LEGACY_ORIGIN_SOURCE,
        )
        self.assertEqual(
            snapshot["catalogs"][publisher.ORIGIN_DESTINATION],
            {"app.a": "Legacy printer app"},
        )

    def test_malformed_modern_origins_do_not_fall_back_to_legacy(self) -> None:
        repository_path = self.temp_path / "upstream"
        _init_repository(
            repository_path,
            _valid_catalogs(),
            modern_origins=True,
            legacy_origins=True,
            raw_overrides={publisher.ORIGIN_DESTINATION: "{broken"},
        )
        destination = self.temp_path / "destination"
        previous = _seed_existing_destination(destination)

        with (
            mock.patch.object(publisher, "DATA_DIR", destination),
            self.assertRaises(json.JSONDecodeError),
        ):
            publisher.sync("HEAD", repository_path=repository_path)

        _assert_destination_unchanged(destination, previous)

    def test_failed_replace_preserves_bundle_and_cleans_its_temporary_file(
        self,
    ) -> None:
        repository_path = self.temp_path / "upstream"
        _init_repository(repository_path, _valid_catalogs())
        destination = self.temp_path / "destination"
        previous = _seed_existing_destination(destination)

        with (
            mock.patch.object(publisher, "DATA_DIR", destination),
            mock.patch.object(
                publisher.os, "replace", side_effect=OSError("replace failed")
            ),
            self.assertRaisesRegex(OSError, "replace failed"),
        ):
            publisher.sync("HEAD", repository_path=repository_path)

        _assert_destination_unchanged(destination, previous)

    def test_failed_temporary_file_fsync_preserves_bundle_and_cleans_temporary_file(
        self,
    ) -> None:
        repository_path = self.temp_path / "upstream"
        _init_repository(repository_path, _valid_catalogs())
        destination = self.temp_path / "destination"
        previous = _seed_existing_destination(destination)

        with (
            mock.patch.object(publisher, "DATA_DIR", destination),
            mock.patch.object(
                publisher.os, "fsync", side_effect=OSError("write failed")
            ),
            self.assertRaisesRegex(OSError, "write failed"),
        ):
            publisher.sync("HEAD", repository_path=repository_path)

        _assert_destination_unchanged(destination, previous)

    def test_duplicate_detector_aliases_future_protocols_and_predictions_are_allowed(
        self,
    ) -> None:
        catalogs = _valid_catalogs()
        catalogs["catalog_models.json"][0]["detections"].append(
            {"exact_names": ["MODEL-A"]},
        )

        self.assertEqual(validate_snapshot(_snapshot(catalogs))["catalogs"], catalogs)

    def test_legacy_name_fallback_is_limited_to_nested_detection_rules(self) -> None:
        legacy_catalogs = _valid_catalogs()
        legacy_catalogs["catalog_models.json"][0]["detections"] = [
            {"name": "DISPLAY NAME", "detection": {"mac_suffixes": ["59"]}}
        ]
        validate_snapshot(_snapshot(legacy_catalogs))

        modern_catalogs = _valid_catalogs()
        modern_catalogs["catalog_models.json"][0]["detections"] = [
            {"mac_suffixes": ["59"]}
        ]
        with self.assertRaises(ValueError):
            validate_snapshot(_snapshot(modern_catalogs))

    def test_whitespace_modes_are_validated_without_changing_legacy_defaults(
        self,
    ) -> None:
        for whitespace_mode in ("remove", "trim", "preserve"):
            with self.subTest(whitespace_mode=whitespace_mode):
                catalogs = _valid_catalogs()
                catalogs["catalog_models.json"][0]["whitespace_mode"] = whitespace_mode
                validate_snapshot(_snapshot(catalogs))

        catalogs = _valid_catalogs()
        catalogs["catalog_models.json"][0]["whitespace_mode"] = "strip"
        with self.assertRaises(ValueError):
            validate_snapshot(_snapshot(catalogs))

    def test_bundle_and_source_metadata_require_exact_keys_and_known_values(
        self,
    ) -> None:
        invalidations = (
            "extra_bundle_key",
            "extra_source_key",
            "schema_version",
            "repository",
            "commit",
            "license",
            "missing_source_file_key",
            "empty_source_path",
            "wrong_catalog_type",
        )
        for invalidation in invalidations:
            with self.subTest(invalidation=invalidation):
                snapshot = _snapshot(_valid_catalogs())
                source = snapshot["source"]
                if invalidation == "extra_bundle_key":
                    snapshot["extra"] = True
                elif invalidation == "extra_source_key":
                    source["extra"] = True
                elif invalidation == "schema_version":
                    snapshot["schema_version"] = True
                elif invalidation == "repository":
                    source["repository"] = "https://example.com/other"
                elif invalidation == "commit":
                    source["commit"] = "short"
                elif invalidation == "license":
                    source["license"] = "MIT"
                elif invalidation == "missing_source_file_key":
                    source["files"].pop(publisher.ORIGIN_DESTINATION)
                elif invalidation == "empty_source_path":
                    source["files"]["catalog_models.json"] = " "
                elif invalidation == "wrong_catalog_type":
                    snapshot["catalogs"]["catalog_models.json"] = {}

                with self.assertRaises(ValueError):
                    validate_snapshot(snapshot)

    def test_geometry_requires_positive_integer_dimensions_and_supported_rotation(
        self,
    ) -> None:
        invalid_values = (
            ("profile", "size", 0),
            ("profile", "dev_dpi", True),
            ("paper", "paper_width_px", 0),
            ("paper", "render_height_px", 0),
            ("paper", "max_height_px", -1),
            ("paper", "rotation_degrees", 45),
        )
        for target, field, value in invalid_values:
            with self.subTest(target=target, field=field, value=value):
                catalogs = _valid_catalogs()
                if target == "profile":
                    catalogs["catalog_profiles.json"][0][field] = value
                else:
                    catalogs["catalog_paper_presets.json"]["paper-a"][field] = value

                with self.assertRaises(ValueError):
                    validate_snapshot(_snapshot(catalogs))

    def test_checked_in_legacy_catalog_data_validates_without_writing(self) -> None:
        data_directory = (
            Path(__file__).resolve().parents[1]
            / "catlabel"
            / "vendors"
            / "generic"
            / "data"
        )
        catalog_filenames = [*publisher.SOURCE_PATHS, publisher.ORIGIN_DESTINATION]
        legacy_catalogs = {
            filename: json.loads(
                (data_directory / filename).read_text(encoding="utf-8")
            )
            for filename in catalog_filenames
        }
        source_metadata = json.loads(
            (data_directory / "catalog_source.json").read_text(encoding="utf-8")
        )
        snapshot = {
            "schema_version": 1,
            "source": source_metadata,
            "catalogs": legacy_catalogs,
        }

        self.assertEqual(validate_snapshot(snapshot), snapshot)


if __name__ == "__main__":
    unittest.main()
