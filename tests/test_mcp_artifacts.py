from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlmodel import SQLModel

from catlabel.services.artifacts import ArtifactError, ArtifactStore


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="catlabel-artifacts-")
        self.root = Path(self.temporary.name)
        self.engine = create_engine(
            f"sqlite:///{self.root / 'catlabel.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)
        self.artifact_root = self.root / "managed"
        self.store = ArtifactStore(self.engine, self.artifact_root)

    def tearDown(self) -> None:
        self.store.close()
        self.engine.dispose()
        self.temporary.cleanup()

    def test_atomic_storage_returns_metadata_and_verifies_content_hash(self) -> None:
        payload = b"managed-source-bytes"
        metadata = self.store.put_bytes(
            payload,
            mime_type="application/octet-stream",
            kind="preview_source",
        )

        self.assertEqual(
            set(metadata),
            {
                "id",
                "uri",
                "sha256",
                "mime_type",
                "kind",
                "size_bytes",
                "created_at",
                "expires_at",
            },
        )
        self.assertNotIn("path", metadata)
        self.assertEqual(metadata["size_bytes"], len(payload))
        self.assertEqual(self.store.read_bytes(metadata["id"]), payload)
        self.assertEqual(self.store.get(metadata["id"]), metadata)

        blob_path = self.artifact_root / f"{metadata['id']}.blob"
        blob_path.write_bytes(b"tampered-source-byte")
        with self.assertRaises(ArtifactError) as raised:
            self.store.read_bytes(metadata["id"])
        self.assertEqual(raised.exception.code, "artifact_hash_mismatch")

    def test_windows_storage_skips_unavailable_directory_open(self) -> None:
        payload = b"windows-compatible-managed-source"
        real_open = os.open
        real_fsync = os.fsync
        root_path = os.fspath(self.artifact_root)
        directory_open_attempts: list[str] = []
        file_open_calls: list[tuple[str, int, int]] = []

        def guarded_open(path, flags, mode=0o777):
            path_value = os.fspath(path)
            if path_value == root_path:
                directory_open_attempts.append(path_value)
                raise PermissionError("directory opens are unavailable")
            file_open_calls.append((path_value, flags, mode))
            return real_open(path, flags, mode)

        with (
            patch("catlabel.services.artifacts.os.name", "nt"),
            patch("catlabel.services.artifacts.os.open", side_effect=guarded_open),
            patch("catlabel.services.artifacts.os.fsync", wraps=real_fsync) as fsync,
        ):
            metadata = self.store.put_bytes(
                payload,
                mime_type="application/octet-stream",
                kind="windows_fixture",
            )

        self.assertEqual(directory_open_attempts, [])
        self.assertEqual(len(file_open_calls), 1)
        self.assertTrue(file_open_calls[0][1] & os.O_EXCL)
        self.assertEqual(fsync.call_count, 1)
        self.assertEqual(metadata["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(self.store.read_bytes(metadata["id"]), payload)
        self.assertEqual(self.store.get(metadata["id"]), metadata)

    @unittest.skipIf(os.name == "nt", "directory fsync is unavailable on Windows")
    def test_posix_storage_fsyncs_artifact_directory(self) -> None:
        real_open = os.open
        real_fsync = os.fsync
        root_path = os.fspath(self.artifact_root)
        opened_paths: list[str] = []

        def recording_open(path, flags, mode=0o777):
            opened_paths.append(os.fspath(path))
            return real_open(path, flags, mode)

        with (
            patch("catlabel.services.artifacts.os.open", side_effect=recording_open),
            patch("catlabel.services.artifacts.os.fsync", wraps=real_fsync) as fsync,
        ):
            self.store.put_bytes(
                b"posix-directory-fsync",
                mime_type="application/octet-stream",
                kind="posix_fixture",
            )

        self.assertIn(root_path, opened_paths)
        self.assertEqual(fsync.call_count, 2)

    def test_quota_counts_all_records_until_unpinned_expired_content_is_reaped(
        self,
    ) -> None:
        first = self.store.put_bytes(
            b"123456",
            mime_type="application/octet-stream",
            kind="fixture",
            ttl_seconds=0,
        )
        self.store.pin("plan:held", [first["id"]])
        with self.assertRaises(ArtifactError) as raised:
            ArtifactStore(self.engine, self.artifact_root, quota_bytes=6).put_bytes(
                b"x", mime_type="application/octet-stream", kind="fixture"
            )
        self.assertEqual(raised.exception.code, "artifact_quota_exceeded")

        self.store.unpin("plan:held")
        self.assertEqual(self.store.reap(), 1)
        small_store = ArtifactStore(self.engine, self.artifact_root, quota_bytes=6)
        self.addCleanup(small_store.close)
        second = small_store.put_bytes(
            b"123456", mime_type="application/octet-stream", kind="fixture"
        )
        self.assertEqual(second["size_bytes"], 6)

    def test_expiring_owner_pins_are_reaped_before_artifact_expiry(self) -> None:
        with patch("catlabel.services.artifacts.time.time", return_value=100.0):
            metadata = self.store.put_bytes(
                b"source",
                mime_type="application/octet-stream",
                kind="preview",
                ttl_seconds=10,
            )
            self.store.pin("preview:one", [metadata["id"]], expires_at=105.0)

        with patch("catlabel.services.artifacts.time.time", return_value=105.0):
            self.assertEqual(self.store.reap(), 0)
        with patch("catlabel.services.artifacts.time.time", return_value=110.0):
            self.assertEqual(self.store.reap(), 1)
        self.assertFalse((self.artifact_root / f"{metadata['id']}.blob").exists())

    def test_reap_rechecks_pin_atomically_before_deleting_candidate(self) -> None:
        racing_store = ArtifactStore(self.engine, self.artifact_root)
        self.addCleanup(racing_store.close)
        with patch("catlabel.services.artifacts.time.time", return_value=100.0):
            metadata = self.store.put_bytes(
                b"concurrent-source",
                mime_type="application/octet-stream",
                kind="fixture",
                ttl_seconds=0,
            )
            original_delete = self.store._delete_expired_candidates

            def pin_between_selection_and_delete(session, artifact_ids, now):
                racing_store.pin("concurrent-owner", artifact_ids)
                return original_delete(session, artifact_ids, now)

            with patch.object(
                self.store,
                "_delete_expired_candidates",
                side_effect=pin_between_selection_and_delete,
            ):
                self.assertEqual(self.store.reap(), 0)

        self.assertEqual(self.store.read_bytes(metadata["id"]), b"concurrent-source")
        self.assertTrue((self.artifact_root / f"{metadata['id']}.blob").exists())

    def test_startup_cleanup_removes_only_bounded_managed_orphans(self) -> None:
        retained = self.store.put_bytes(
            b"known", mime_type="application/octet-stream", kind="fixture"
        )
        orphan_id = str(uuid.uuid4())
        orphan = self.artifact_root / f"{orphan_id}.blob"
        orphan.write_bytes(b"orphan")
        temporary_id = str(uuid.uuid4())
        temporary = self.artifact_root / f".{temporary_id}.tmp"
        temporary.write_bytes(b"interrupted")
        unrelated = self.artifact_root / "notes.txt"
        unrelated.write_text("leave this alone", encoding="utf-8")

        reopened = ArtifactStore(self.engine, self.artifact_root)
        self.addCleanup(reopened.close)

        self.assertTrue((self.artifact_root / f"{retained['id']}.blob").exists())
        self.assertFalse(orphan.exists())
        self.assertFalse(temporary.exists())
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "leave this alone")

    def test_plan_style_nonexpiring_pin_survives_owner_expiry_reaping(self) -> None:
        with patch("catlabel.services.artifacts.time.time", return_value=200.0):
            metadata = self.store.put_bytes(
                b"source",
                mime_type="application/octet-stream",
                kind="plan_source",
                ttl_seconds=1,
            )
            self.store.pin("plan:stable", [metadata["id"]])

        with patch("catlabel.services.artifacts.time.time", return_value=500.0):
            self.assertEqual(self.store.reap(), 0)
        self.assertEqual(self.store.read_bytes(metadata["id"]), b"source")


if __name__ == "__main__":
    unittest.main()
