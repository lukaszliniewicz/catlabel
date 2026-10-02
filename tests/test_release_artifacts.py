from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock

from catlabel.core import release_artifacts
from catlabel.core.release_artifacts import (
    ReleaseManifest,
    backup_database,
    extract_artifact,
    frontend_digest,
    hash_file,
    verify_artifact_directory,
)

_REQUIRED_CONTENTS = {
    "catlabel/__main__.py": b"entry point",
    "catlabel/api/main.py": b"api entry point",
    "tools/bootstrap_runtime.py": b"bootstrap tool",
    "run.sh": b"shell launcher",
    "run.bat": b"batch launcher",
    "run.ps1": b"powershell launcher",
    "pixi.toml": b"runtime config",
    "pixi.lock": b"runtime lock",
    "frontend/dist/index.html": b"opaque frontend fixture",
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class ReleaseManifestTests(unittest.TestCase):
    def manifest_payload(self) -> dict[str, object]:
        files = {
            path: _sha256(contents) for path, contents in _REQUIRED_CONTENTS.items()
        }
        return {
            "schema_version": 1,
            "release_id": "release-2026.10.03",
            "source_commit": "a" * 40,
            "database_epoch": 1,
            "frontend_sha256": frontend_digest(files),
            "files": files,
        }

    def test_round_trip_has_exact_manifest_fields(self) -> None:
        payload = self.manifest_payload()
        manifest = ReleaseManifest.from_dict(payload)

        self.assertEqual(manifest.to_dict(), payload)
        self.assertEqual(set(manifest.to_dict()), set(payload))

    def test_frontend_digest_sorts_only_frontend_files(self) -> None:
        files = {
            "run.sh": "0" * 64,
            "frontend/dist/z.js": "b" * 64,
            "frontend/dist/index.html": "a" * 64,
            "frontend/dist/a.css": "c" * 64,
        }
        records = b"frontend/dist/a.css\0" + b"c" * 64 + b"\n"
        records += b"frontend/dist/index.html\0" + b"a" * 64 + b"\n"
        records += b"frontend/dist/z.js\0" + b"b" * 64 + b"\n"
        self.assertEqual(frontend_digest(files), _sha256(records))

    def test_frontend_digest_requires_index(self) -> None:
        with self.assertRaises(ValueError):
            frontend_digest({"frontend/dist/app.js": "a" * 64})

    def test_manifest_rejects_wrong_fields_types_and_values(self) -> None:
        mutations = [
            lambda payload: payload.pop("release_id"),
            lambda payload: payload.update(extra="value"),
            lambda payload: payload.update(schema_version=True),
            lambda payload: payload.update(database_epoch=True),
            lambda payload: payload.update(database_epoch=2),
            lambda payload: payload.update(release_id="_starts-with-punctuation"),
            lambda payload: payload.update(source_commit="A" * 40),
            lambda payload: payload.update(frontend_sha256="A" * 64),
            lambda payload: payload["files"].update({"run.sh": "A" * 64}),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                payload = copy.deepcopy(self.manifest_payload())
                mutate(payload)
                with self.assertRaises(ValueError):
                    ReleaseManifest.from_dict(payload)

    def test_manifest_rejects_invalid_paths(self) -> None:
        invalid_paths = [
            "../escape",
            "/absolute",
            "C:/drive",
            "nested\\file",
            "bin",
            "DATA",
            ".pixi",
            ".git",
            ".bootstrap-state",
            ".bootstrap-state/.ai-enabled",
            "bin/program",
            "DATA/file",
            ".GIT/config",
            ".pixi/env",
            "release-manifest.json",
            "bad<>|?*.txt",
            "name.",
            "name ",
            "CON.txt",
            "NUL .txt",
            "com9.anything",
            "LPT1",
            "folder//file",
            "folder/./file",
            "folder/../file",
            "cafe\u0301.txt",
        ]
        for path in invalid_paths:
            with self.subTest(path=path):
                payload = self.manifest_payload()
                files = payload["files"]
                assert isinstance(files, dict)
                files[path] = "0" * 64
                payload["frontend_sha256"] = frontend_digest(files)
                with self.assertRaises(ValueError):
                    ReleaseManifest.from_dict(payload)

    def test_manifest_rejects_casefold_and_file_parent_collisions(self) -> None:
        collision_sets = [
            {"CATLABEL/__MAIN__.PY": "0" * 64},
            {"tools": "0" * 64},
            {"Tools/bootstrap_runtime.py": "0" * 64},
        ]
        for extra in collision_sets:
            with self.subTest(extra=extra):
                payload = self.manifest_payload()
                files = payload["files"]
                assert isinstance(files, dict)
                files.update(extra)
                payload["frontend_sha256"] = frontend_digest(files)
                with self.assertRaises(ValueError):
                    ReleaseManifest.from_dict(payload)


class ReleaseArtifactArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="catlabel-release-test-")
        self.root = Path(self.temporary.name)
        self.staging_parent = self.root / "staging"
        self.staging_parent.mkdir()
        self.sentinel = self.staging_parent / "sentinel.txt"
        self.sentinel.write_bytes(b"preserve me")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def manifest_payload(
        self, contents: dict[str, bytes] | None = None
    ) -> dict[str, object]:
        selected = contents or _REQUIRED_CONTENTS
        files = {path: _sha256(value) for path, value in selected.items()}
        return {
            "schema_version": 1,
            "release_id": "release-2026.10.03",
            "source_commit": "b" * 40,
            "database_epoch": 1,
            "frontend_sha256": frontend_digest(files),
            "files": files,
        }

    def write_archive(
        self,
        entries: list[tuple[str, bytes, int | None]],
    ) -> tuple[Path, str]:
        archive = self.root / "release.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
            for name, contents, unix_mode in entries:
                info = zipfile.ZipInfo(name)
                if unix_mode is not None:
                    info.create_system = 3
                    info.external_attr = unix_mode << 16
                output.writestr(info, contents)
        return archive, hash_file(archive)

    def valid_entries(
        self,
        contents: dict[str, bytes] | None = None,
        *,
        payload: dict[str, object] | None = None,
    ) -> list[tuple[str, bytes, int | None]]:
        selected = contents or _REQUIRED_CONTENTS
        manifest = payload if payload is not None else self.manifest_payload(selected)
        encoded_manifest = json.dumps(
            manifest, sort_keys=True, separators=(",", ":")
        ).encode()
        entries: list[tuple[str, bytes, int | None]] = []
        entries.append(("release-manifest.json", encoded_manifest, None))
        for path, value in selected.items():
            entries.append((path, value, None))
        return entries

    def assert_only_sentinel_remains(self) -> None:
        self.assertEqual(list(self.staging_parent.iterdir()), [self.sentinel])
        self.assertEqual(self.sentinel.read_bytes(), b"preserve me")

    def test_extracts_files_and_preserves_exact_manifest_bytes(self) -> None:
        entries = self.valid_entries()
        archive, archive_digest = self.write_archive(entries)
        expected_manifest_bytes = entries[0][1]

        stage, manifest = extract_artifact(archive, archive_digest, self.staging_parent)

        self.assertEqual(stage.parent, self.staging_parent)
        self.assertTrue(stage.name.startswith(".stage-"))
        self.assertEqual(
            (stage / "release-manifest.json").read_bytes(), expected_manifest_bytes
        )
        self.assertEqual(manifest.to_dict(), self.manifest_payload())
        for relative_path, contents in _REQUIRED_CONTENTS.items():
            self.assertEqual((stage / relative_path).read_bytes(), contents)
        self.assertEqual(self.sentinel.read_bytes(), b"preserve me")
        verify_artifact_directory(stage, manifest)

    def test_archive_digest_is_checked_before_opening_zip(self) -> None:
        archive, _ = self.write_archive(self.valid_entries())
        with (
            mock.patch.object(release_artifacts.zipfile, "ZipFile") as zip_open,
            self.assertRaises(ValueError),
        ):
            extract_artifact(archive, "0" * 64, self.staging_parent)
        zip_open.assert_not_called()
        self.assert_only_sentinel_remains()

    def test_path_replacement_keeps_the_verified_descriptor(self) -> None:
        archive, digest = self.write_archive(self.valid_entries())
        original = archive.read_bytes()
        alternate_payload = self.manifest_payload()
        alternate_payload["release_id"] = "replacement-release"
        self.write_archive(self.valid_entries(payload=alternate_payload))
        replacement = self.root / "replacement.zip"
        archive.rename(replacement)
        archive.write_bytes(original)
        hash_stream = release_artifacts._hash_archive_stream
        swapped = False

        def replace_after_hash(stream):
            nonlocal swapped
            result = hash_stream(stream)
            if not swapped:
                swapped = True
                replacement.replace(archive)
            return result

        with mock.patch.object(
            release_artifacts, "_hash_archive_stream", side_effect=replace_after_hash
        ):
            stage, manifest = extract_artifact(archive, digest, self.staging_parent)
        self.assertEqual(manifest.release_id, "release-2026.10.03")
        self.assertNotEqual(hash_file(archive), digest)
        verify_artifact_directory(stage, manifest)

    def test_in_place_archive_change_is_rejected_and_cleans_stage(self) -> None:
        archive, digest = self.write_archive(self.valid_entries())
        original = archive.read_bytes()
        alternate_payload = self.manifest_payload()
        alternate_payload["release_id"] = "replacement-release"
        self.write_archive(self.valid_entries(payload=alternate_payload))
        alternate = archive.read_bytes()
        archive.write_bytes(original)
        hash_stream = release_artifacts._hash_archive_stream
        changed = False

        def rewrite_after_hash(stream):
            nonlocal changed
            result = hash_stream(stream)
            if not changed:
                changed = True
                archive.write_bytes(alternate)
            return result

        with (
            mock.patch.object(
                release_artifacts,
                "_hash_archive_stream",
                side_effect=rewrite_after_hash,
            ),
            self.assertRaisesRegex(ValueError, "digest changed"),
        ):
            extract_artifact(archive, digest, self.staging_parent)
        self.assert_only_sentinel_remains()

    def test_rejects_invalid_archive_paths_and_preserves_sentinel(self) -> None:
        entries = self.valid_entries()
        entries.append(("../escape", b"escape", None))
        archive, archive_digest = self.write_archive(entries)

        with self.assertRaises(ValueError):
            extract_artifact(archive, archive_digest, self.staging_parent)

        self.assertFalse((self.root / "escape").exists())
        self.assert_only_sentinel_remains()

    def test_rejects_duplicate_and_casecolliding_entries(self) -> None:
        base = self.valid_entries()
        duplicate_entries = base + [base[1]]
        case_entries = base + [("CATLABEL/__MAIN__.PY", b"alias", None)]
        for entries in (duplicate_entries, case_entries):
            with self.subTest(entry_count=len(entries)):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive, archive_digest = self.write_archive(entries)
                with self.assertRaises(ValueError):
                    extract_artifact(archive, archive_digest, self.staging_parent)
                self.assert_only_sentinel_remains()

    def test_rejects_symlink_and_nonregular_unix_modes(self) -> None:
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600):
            with self.subTest(mode=oct(mode)):
                entries = self.valid_entries()
                entries[1] = (entries[1][0], entries[1][1], mode)
                archive, archive_digest = self.write_archive(entries)
                with self.assertRaises(ValueError):
                    extract_artifact(archive, archive_digest, self.staging_parent)
                self.assert_only_sentinel_remains()

    def test_rejects_missing_and_extra_archive_entries(self) -> None:
        entries = self.valid_entries()
        for altered in (entries[:-1], entries + [("unexpected.bin", b"extra", None)]):
            with self.subTest(entry_count=len(altered)):
                archive, archive_digest = self.write_archive(altered)
                with self.assertRaises(ValueError):
                    extract_artifact(archive, archive_digest, self.staging_parent)
                self.assert_only_sentinel_remains()

    def test_file_hash_mismatch_cleans_only_created_stage(self) -> None:
        expected = dict(_REQUIRED_CONTENTS)
        changed = dict(expected)
        changed["frontend/dist/index.html"] = b"changed after manifest"
        entries = self.valid_entries(expected)
        entries = [
            (name, changed.get(name, contents), mode)
            if name != "release-manifest.json"
            else (name, contents, mode)
            for name, contents, mode in entries
        ]
        archive, archive_digest = self.write_archive(entries)

        with self.assertRaises(ValueError):
            extract_artifact(archive, archive_digest, self.staging_parent)

        self.assert_only_sentinel_remains()

    def test_frontend_digest_mismatch_fails_before_stage_creation(self) -> None:
        payload = self.manifest_payload()
        payload["frontend_sha256"] = "0" * 64
        archive, archive_digest = self.write_archive(
            self.valid_entries(payload=payload)
        )

        with self.assertRaises(ValueError):
            extract_artifact(archive, archive_digest, self.staging_parent)

        self.assert_only_sentinel_remains()

    def test_archive_preflight_limits_fail_before_stage_creation(self) -> None:
        archive, archive_digest = self.write_archive(self.valid_entries())
        limit_cases = (
            ("MAX_ARCHIVE_BYTES", 0),
            ("MAX_MANIFEST_BYTES", 1),
            ("MAX_INFLATED_FILE_BYTES", 1),
            ("MAX_INFLATED_TOTAL_BYTES", 1),
            ("MAX_ARCHIVE_ENTRIES", 1),
        )
        for name, value in limit_cases:
            with self.subTest(limit=name):
                with (
                    mock.patch.object(release_artifacts, name, value),
                    self.assertRaises(ValueError),
                ):
                    extract_artifact(archive, archive_digest, self.staging_parent)
                self.assert_only_sentinel_remains()

    def test_verification_allows_runtime_created_root_entries(self) -> None:
        archive, archive_digest = self.write_archive(self.valid_entries())
        stage, manifest = extract_artifact(archive, archive_digest, self.staging_parent)
        runtime_directory = stage / ".pixi"
        runtime_directory.mkdir()
        (runtime_directory / "runtime-marker").write_text("created after extraction")
        (stage / "bin").mkdir()

        verify_artifact_directory(stage, manifest)

    def test_verification_rejects_symlinked_artifact_file(self) -> None:
        archive, archive_digest = self.write_archive(self.valid_entries())
        stage, manifest = extract_artifact(archive, archive_digest, self.staging_parent)
        target = self.root / "external.txt"
        target.write_bytes(_REQUIRED_CONTENTS["run.sh"])
        artifact_path = stage / "run.sh"
        artifact_path.unlink()
        artifact_path.symlink_to(target)

        with self.assertRaises(ValueError):
            verify_artifact_directory(stage, manifest)


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="catlabel-db-backup-test-")
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_backup_includes_committed_wal_contents(self) -> None:
        source = self.root / "source.sqlite"
        destination = self.root / "nested" / "backup.sqlite"
        writer = sqlite3.connect(source)
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE records (value TEXT NOT NULL)")
            writer.execute("INSERT INTO records(value) VALUES ('visible through WAL')")
            writer.commit()
            self.assertTrue(Path(f"{source}-wal").exists())

            self.assertTrue(backup_database(source, destination))
            with sqlite3.connect(destination) as backup:
                rows = backup.execute("SELECT value FROM records").fetchall()
            self.assertEqual(rows, [("visible through WAL",)])
        finally:
            writer.close()

    def test_missing_source_does_not_create_destination_parent_or_replace_old_file(
        self,
    ) -> None:
        missing = self.root / "missing.sqlite"
        absent_destination = self.root / "not-created" / "backup.sqlite"
        self.assertFalse(backup_database(missing, absent_destination))
        self.assertFalse(absent_destination.parent.exists())

        existing_destination = self.root / "old" / "backup.sqlite"
        existing_destination.parent.mkdir()
        existing_destination.write_bytes(b"previous backup")
        self.assertFalse(backup_database(missing, existing_destination))
        self.assertEqual(existing_destination.read_bytes(), b"previous backup")

    def test_corrupt_source_preserves_existing_backup_and_cleans_temporary_file(
        self,
    ) -> None:
        source = self.root / "corrupt.sqlite"
        destination = self.root / "backup.sqlite"
        source.write_bytes(b"not a database")
        destination.write_bytes(b"previous backup")

        with self.assertRaises(sqlite3.DatabaseError):
            backup_database(source, destination)

        self.assertEqual(destination.read_bytes(), b"previous backup")
        self.assertEqual(set(self.root.iterdir()), {source, destination})

    def test_source_and_destination_must_not_resolve_to_same_path(self) -> None:
        source = self.root / "source.sqlite"
        with sqlite3.connect(source) as connection:
            connection.execute("CREATE TABLE records (value TEXT)")
        before = source.read_bytes()

        with self.assertRaises(ValueError):
            backup_database(source, source)

        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
