from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

from catlabel.core.release_artifacts import ReleaseManifest, frontend_digest, hash_file
from catlabel.core.release_slots import (
    InstalledRelease,
    activate_artifact,
    load_active,
    rollback,
)
from catlabel.core.runtime_lease import RuntimeBusyError, RuntimeLease

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


class ProbeAbort(BaseException):
    pass


class ReleaseSlotsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="catlabel-release-slots-")
        self.workspace = Path(self.temporary.name)
        self.root = self.workspace / "slots"
        self.data_directory = self.workspace / "data"

    def tearDown(self) -> None:
        connection = getattr(self, "database_connection", None)
        if connection is not None:
            connection.close()
        self.temporary.cleanup()

    def make_archive(
        self, name: str, *, database_epoch: int = 1
    ) -> tuple[Path, str, dict[str, bytes]]:
        contents = dict(_REQUIRED_CONTENTS)
        marker = name.encode("ascii")
        contents["catlabel/__main__.py"] = b"entry point " + marker
        contents["run.sh"] = b"shell launcher " + marker
        files = {path: _sha256(value) for path, value in contents.items()}
        manifest = {
            "schema_version": 1,
            "release_id": name,
            "source_commit": _sha256(marker)[:40],
            "database_epoch": database_epoch,
            "frontend_sha256": frontend_digest(files),
            "files": files,
        }
        archive = self.workspace / f"{name}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
            output.writestr(
                "release-manifest.json",
                json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            )
            for path, value in contents.items():
                output.writestr(path, value)
        return archive, hash_file(archive), contents

    def activate(
        self,
        archive: Path,
        digest: str,
        *,
        prepare: Callable[[Path], None] | None = None,
        probe: Callable[[Path, ReleaseManifest, Path], None] | None = None,
    ) -> InstalledRelease:
        return activate_artifact(
            self.root,
            self.data_directory,
            archive,
            digest,
            prepare or (lambda _slot: None),
            probe or (lambda _slot, _manifest, _data: None),
        )

    def make_database(self) -> sqlite3.Connection:
        self.data_directory.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.data_directory / "catlabel.db")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE release_test (value TEXT NOT NULL)")
        connection.execute("INSERT INTO release_test VALUES ('kept from WAL')")
        connection.commit()
        self.database_connection = connection
        return connection

    def state_bytes(self) -> bytes | None:
        path = self.root / "active.json"
        return path.read_bytes() if path.exists() else None

    def state_payload(self) -> dict[str, object]:
        payload = json.loads((self.root / "active.json").read_text("utf-8"))
        assert isinstance(payload, dict)
        return cast(dict[str, object], payload)

    def test_first_second_activation_and_rollback_keep_code_slots(self) -> None:
        first_archive, first_digest, first_contents = self.make_archive("release-one")
        second_archive, second_digest, second_contents = self.make_archive(
            "release-two"
        )
        observed_prepare_paths: list[Path] = []

        def prepare(slot: Path) -> None:
            observed_prepare_paths.append(slot)
            self.assertEqual(slot, self.root / ".releases" / slot.name)
            self.assertFalse(slot.name.startswith(".stage-"))

        first = self.activate(first_archive, first_digest, prepare=prepare)
        self.assertEqual(first.archive_sha256, first_digest)
        self.assertEqual(first.path, self.root / ".releases" / first_digest)
        self.assertEqual(load_active(self.root), first)
        self.assertEqual(
            self.state_payload(),
            {
                "schema_version": 1,
                "active": first_digest,
                "previous": None,
            },
        )

        prior_slot_sentinel = first.path / "keep.txt"
        prior_slot_sentinel.write_bytes(b"keep previous code slot")
        second = self.activate(second_archive, second_digest, prepare=prepare)
        self.assertEqual(load_active(self.root), second)
        self.assertEqual(self.state_payload()["previous"], first_digest)
        self.assertEqual(
            (first.path / "catlabel/__main__.py").read_bytes(),
            first_contents["catlabel/__main__.py"],
        )
        self.assertEqual(
            (second.path / "run.sh").read_bytes(), second_contents["run.sh"]
        )
        self.assertEqual(prior_slot_sentinel.read_bytes(), b"keep previous code slot")

        database = self.make_database()
        row_before = database.execute("SELECT value FROM release_test").fetchone()
        rolled_back = rollback(self.root, self.data_directory)
        self.assertEqual(rolled_back.archive_sha256, first_digest)
        self.assertEqual(load_active(self.root), rolled_back)
        self.assertEqual(self.state_payload()["previous"], second_digest)
        self.assertEqual(
            database.execute("SELECT value FROM release_test").fetchone(), row_before
        )
        self.assertEqual(len(observed_prepare_paths), 2)

    def test_database_backup_and_probe_use_online_backup_copy(self) -> None:
        self.make_database()
        self.assertTrue((self.data_directory / "catlabel.db-wal").exists())
        archive, digest, _ = self.make_archive("wal-copy")
        observed: dict[str, Path] = {}

        def probe(_slot: Path, _manifest: ReleaseManifest, probe_data: Path) -> None:
            observed["probe_data"] = probe_data
            database_copy = probe_data / "catlabel.db"
            probe_connection = sqlite3.connect(database_copy)
            try:
                self.assertEqual(
                    probe_connection.execute(
                        "SELECT value FROM release_test"
                    ).fetchone(),
                    ("kept from WAL",),
                )
            finally:
                probe_connection.close()

        self.activate(archive, digest, probe=probe)
        backup_paths = list(
            (self.data_directory / "backups").glob("before-update-*.sqlite")
        )
        self.assertEqual(len(backup_paths), 1)
        backup_connection = sqlite3.connect(backup_paths[0])
        try:
            self.assertEqual(
                backup_connection.execute("SELECT value FROM release_test").fetchone(),
                ("kept from WAL",),
            )
        finally:
            backup_connection.close()
        self.assertFalse(observed["probe_data"].exists())
        self.assertTrue((self.data_directory / "catlabel.db-wal").exists())

    def test_prepare_failure_keeps_pointer_and_durable_backup(self) -> None:
        first_archive, first_digest, _ = self.make_archive("prepare-first")
        self.activate(first_archive, first_digest)
        original_state = self.state_bytes()
        first_slot_contents = {
            path: (self.root / ".releases" / first_digest / path).read_bytes()
            for path in _REQUIRED_CONTENTS
        }
        self.make_database()
        second_archive, second_digest, _ = self.make_archive("prepare-second")

        def fail_prepare(_slot: Path) -> None:
            raise RuntimeError("prepare failed")

        with self.assertRaisesRegex(RuntimeError, "prepare failed"):
            self.activate(second_archive, second_digest, prepare=fail_prepare)

        self.assertEqual(self.state_bytes(), original_state)
        self.assertTrue((self.root / ".releases" / second_digest).is_dir())
        for path, contents in first_slot_contents.items():
            self.assertEqual(
                (self.root / ".releases" / first_digest / path).read_bytes(), contents
            )
        self.assertEqual(
            len(list((self.data_directory / "backups").glob("before-update-*.sqlite"))),
            1,
        )
        self.assertEqual(list(self.data_directory.glob(".probe-*")), [])

    def test_probe_base_exception_cleans_only_owned_probe_and_preserves_backup(
        self,
    ) -> None:
        first_archive, first_digest, _ = self.make_archive("probe-first")
        self.activate(first_archive, first_digest)
        original_state = self.state_bytes()
        database = self.make_database()
        sibling = self.data_directory / ".probe-sentinel"
        sibling.mkdir()
        (sibling / "keep.txt").write_bytes(b"preserve")
        second_archive, second_digest, _ = self.make_archive("probe-second")
        observed_probe_directory: list[Path] = []

        def abort_probe(
            _slot: Path, _manifest: ReleaseManifest, probe_data: Path
        ) -> None:
            observed_probe_directory.append(probe_data)
            raise ProbeAbort("probe stopped")

        with self.assertRaises(ProbeAbort):
            self.activate(second_archive, second_digest, probe=abort_probe)

        self.assertEqual(self.state_bytes(), original_state)
        self.assertFalse(observed_probe_directory[0].exists())
        self.assertEqual((sibling / "keep.txt").read_bytes(), b"preserve")
        self.assertEqual(
            len(list((self.data_directory / "backups").glob("before-update-*.sqlite"))),
            1,
        )
        self.assertEqual(
            database.execute("SELECT value FROM release_test").fetchone(),
            ("kept from WAL",),
        )

    def test_probe_code_tampering_prevents_pointer_publication(self) -> None:
        first_archive, first_digest, _ = self.make_archive("tamper-first")
        self.activate(first_archive, first_digest)
        original_state = self.state_bytes()
        second_archive, second_digest, _ = self.make_archive("tamper-second")

        def tamper_probe(slot: Path, _manifest: ReleaseManifest, _data: Path) -> None:
            (slot / "run.sh").write_bytes(b"modified after verification")

        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.activate(second_archive, second_digest, probe=tamper_probe)

        self.assertEqual(self.state_bytes(), original_state)
        active = load_active(self.root)
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.archive_sha256, first_digest)

    def test_probe_manifest_metadata_tampering_prevents_promotion(self) -> None:
        first_archive, first_digest, _ = self.make_archive("manifest-first")
        self.activate(first_archive, first_digest)
        original_state = self.state_bytes()
        second_archive, second_digest, _ = self.make_archive("manifest-second")

        def tamper_manifest(
            slot: Path, _manifest: ReleaseManifest, _data: Path
        ) -> None:
            manifest_path = slot / "release-manifest.json"
            payload = json.loads(manifest_path.read_text("utf-8"))
            payload["release_id"] = "changed-metadata"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "metadata changed"):
            self.activate(second_archive, second_digest, probe=tamper_manifest)

        self.assertEqual(self.state_bytes(), original_state)

    def test_probe_cannot_mutate_its_manifest_snapshot(self) -> None:
        archive, digest, _ = self.make_archive("manifest-object")
        original_state = self.state_bytes()
        changed_file = b"probe rewrote the listed artifact"

        def tamper_probe(slot: Path, manifest: ReleaseManifest, _data: Path) -> None:
            (slot / "run.sh").write_bytes(changed_file)
            changed_digest = _sha256(changed_file)
            manifest.files["run.sh"] = changed_digest
            manifest_path = slot / "release-manifest.json"
            payload = json.loads(manifest_path.read_text("utf-8"))
            payload["files"]["run.sh"] = changed_digest
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "metadata changed"):
            self.activate(archive, digest, probe=tamper_probe)

        self.assertEqual(self.state_bytes(), original_state)

    def test_callback_state_change_is_preserved_and_rejects_publication(self) -> None:
        archive, digest, _ = self.make_archive("state-race")
        replacement = (
            b'{"schema_version":1,"active":"' + b"a" * 64 + b'","previous":null}\n'
        )

        def change_state(_slot: Path, _manifest: ReleaseManifest, _data: Path) -> None:
            (self.root / "active.json").write_bytes(replacement)

        with self.assertRaisesRegex(RuntimeError, "state changed"):
            self.activate(archive, digest, probe=change_state)

        self.assertEqual(self.state_bytes(), replacement)
        self.assertTrue((self.root / ".releases" / digest).is_dir())

    def test_busy_data_lease_prevents_callbacks(self) -> None:
        archive, digest, _ = self.make_archive("busy")
        callbacks: list[str] = []

        with RuntimeLease(self.data_directory), self.assertRaises(RuntimeBusyError):
            self.activate(
                archive,
                digest,
                prepare=lambda _slot: callbacks.append("prepare"),
                probe=lambda _slot, _manifest, _data: callbacks.append("probe"),
            )

        self.assertEqual(callbacks, [])
        self.assertFalse((self.root / ".releases").exists())

    def test_bad_archive_digest_and_unsupported_epoch_fail_before_callbacks(
        self,
    ) -> None:
        archive, digest, _ = self.make_archive("bad-digest")
        callbacks: list[str] = []
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.activate(
                archive,
                "0" * 64,
                prepare=lambda _slot: callbacks.append("prepare"),
                probe=lambda _slot, _manifest, _data: callbacks.append("probe"),
            )
        self.assertEqual(callbacks, [])

        unsupported_archive, unsupported_digest, _ = self.make_archive(
            "unsupported-epoch", database_epoch=2
        )
        with self.assertRaises(ValueError):
            self.activate(
                unsupported_archive,
                unsupported_digest,
                prepare=lambda _slot: callbacks.append("prepare"),
                probe=lambda _slot, _manifest, _data: callbacks.append("probe"),
            )
        self.assertEqual(callbacks, [])
        self.assertFalse((self.root / "active.json").exists())

    def test_invalid_state_and_corrupt_slot_are_rejected(self) -> None:
        self.root.mkdir()
        (self.root / "active.json").write_bytes(
            b'{"schema_version":1,"schema_version":1,"active":"'
            + b"a" * 64
            + b'","previous":null}'
        )
        with self.assertRaisesRegex(ValueError, "active release state"):
            load_active(self.root)
        (self.root / "active.json").unlink()

        archive, digest, _ = self.make_archive("corrupt-slot")
        self.activate(archive, digest)
        manifest_path = self.root / ".releases" / digest / "release-manifest.json"
        manifest_path.unlink()
        with self.assertRaises((FileNotFoundError, ValueError)):
            load_active(self.root)

    def test_existing_digest_slot_must_match_verified_incoming_archive(self) -> None:
        archive, digest, _ = self.make_archive("slot-match")
        alternate_archive, _alternate_digest, alternate_contents = self.make_archive(
            "alternate-valid-slot"
        )
        installed = self.activate(archive, digest)
        for relative_path, contents in alternate_contents.items():
            target = installed.path / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        with zipfile.ZipFile(alternate_archive, "r") as alternate_zip:
            (installed.path / "release-manifest.json").write_bytes(
                alternate_zip.read("release-manifest.json")
            )

        with self.assertRaises(ValueError):
            self.activate(archive, digest)

        self.assertEqual(self.state_payload()["active"], digest)

    def test_rollback_without_previous_does_not_change_state(self) -> None:
        archive, digest, _ = self.make_archive("no-previous")
        self.activate(archive, digest)
        original_state = self.state_bytes()
        with self.assertRaisesRegex(ValueError, "no previous release"):
            rollback(self.root, self.data_directory)
        self.assertEqual(self.state_bytes(), original_state)

    def test_state_read_limit_and_boolean_version_are_strict(self) -> None:
        self.root.mkdir()
        state_path = self.root / "active.json"
        state_path.write_bytes(b" " * (16 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "size limit"):
            load_active(self.root)

        state_path.write_text(
            json.dumps({"schema_version": True, "active": "a" * 64, "previous": None}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "active release state"):
            load_active(self.root)


if __name__ == "__main__":
    unittest.main()
