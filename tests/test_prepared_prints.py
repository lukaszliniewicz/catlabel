from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from io import BytesIO
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from PIL import Image

from catlabel.core import resource_limits
from catlabel.services import prepared_prints
from catlabel.services.prepared_prints import (
    PreparedPrintCapacityError,
    PreparedPrintConflict,
    PreparedPrintInvalidImage,
    PreparedPrintLease,
    PreparedPrintNotFound,
    PreparedPrintStore,
    PreparedPrintStoreStopped,
    PreparedPrintTooLarge,
)


def _png(width: int = 2, height: int = 1) -> bytes:
    with Image.new("RGB", (width, height), "white") as image, BytesIO() as output:
        image.save(output, format="PNG")
        return output.getvalue()


class _Clock:
    def __init__(self, value: float = 0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class PreparedPrintStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="catlabel-prepared-test-")
        self.root = Path(self.temporary.name)
        self.store = PreparedPrintStore(temp_root=self.root)
        self.addCleanup(self.store.close)
        self.addCleanup(self.temporary.cleanup)

    def test_expected_count_is_strict_and_capacity_is_bounded(self) -> None:
        for value in (True, False, 0, -1, 1.5, "1", 501):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.start(value)  # type: ignore[arg-type]

        sessions = [self.store.start(1) for _ in range(4)]
        with self.assertRaises(PreparedPrintCapacityError):
            self.store.start(1)
        self.assertEqual(len(list(self.root.iterdir())), 4)

        self.store.close()
        self.assertEqual(list(self.root.iterdir()), [])
        with self.assertRaises(PreparedPrintStoreStopped):
            self.store.start(1)
        self.assertEqual(len(sessions), 4)

    def test_invalid_png_is_rejected_before_file_creation_or_progress_change(
        self,
    ) -> None:
        progress = self.store.start(1)
        session_directory = next(self.root.iterdir())
        with self.assertRaises(PreparedPrintInvalidImage):
            self.store.append(progress.prepared_id, 0, b"not a PNG")
        self.assertEqual(list(session_directory.iterdir()), [])

        appended = self.store.append(progress.prepared_id, 0, _png())
        self.assertEqual(appended.next_index, 1)
        self.assertEqual(len(list(session_directory.iterdir())), 1)

    def test_pages_are_strictly_ordered_and_successful_append_touches_session(
        self,
    ) -> None:
        clock = _Clock(100)
        store = PreparedPrintStore(clock=clock, ttl_seconds=10, temp_root=self.root)
        self.addCleanup(store.close)
        progress = store.start(2)
        with self.assertRaises(PreparedPrintConflict):
            store.append(progress.prepared_id, 1, _png())
        with self.assertRaises(PreparedPrintConflict):
            store.append(progress.prepared_id, True, _png())  # type: ignore[arg-type]

        clock.value = 109
        first = store.append(progress.prepared_id, 0, _png())
        self.assertEqual(first.next_index, 1)
        clock.value = 118
        self.assertEqual(store.reap(), 0)
        second = store.append(progress.prepared_id, 1, _png())
        self.assertEqual(second.next_index, 2)
        clock.value = 127
        self.assertEqual(store.reap(), 0)
        clock.value = 128
        self.assertEqual(store.reap(), 1)
        with self.assertRaises(PreparedPrintNotFound):
            store.take_for_commit(progress.prepared_id)

    def test_exact_ttl_boundary_expires_and_removes_session_files(self) -> None:
        clock = _Clock(50)
        store = PreparedPrintStore(clock=clock, ttl_seconds=5, temp_root=self.root)
        self.addCleanup(store.close)
        progress = store.start(1)
        store.append(progress.prepared_id, 0, _png())
        session_directory = next(self.root.iterdir())

        clock.value = 54.999
        self.assertEqual(store.reap(), 0)
        self.assertTrue(session_directory.exists())
        clock.value = 55
        self.assertEqual(store.reap(), 1)
        self.assertFalse(session_directory.exists())
        with self.assertRaises(PreparedPrintNotFound):
            store.cancel(progress.prepared_id)

    def test_failed_operation_does_not_extend_ttl(self) -> None:
        clock = _Clock(10)
        store = PreparedPrintStore(clock=clock, ttl_seconds=5, temp_root=self.root)
        self.addCleanup(store.close)
        progress = store.start(1)
        clock.value = 14
        with self.assertRaises(PreparedPrintConflict):
            store.append(progress.prepared_id, 1, _png())
        clock.value = 15
        self.assertEqual(store.reap(), 1)
        with self.assertRaises(PreparedPrintNotFound):
            store.append(progress.prepared_id, 0, _png())

    def test_byte_caps_fail_without_advancing_or_creating_candidate(self) -> None:
        payload = _png()
        progress = self.store.start(2)
        with (
            patch.object(prepared_prints, "MAX_IMAGE_BYTES", len(payload)),
            patch.object(prepared_prints, "MAX_REQUEST_BYTES", len(payload)),
        ):
            self.store.append(progress.prepared_id, 0, payload)
            with self.assertRaises(PreparedPrintTooLarge):
                self.store.append(progress.prepared_id, 1, payload)

            session = self.store._sessions[progress.prepared_id]
            self.assertEqual(session.next_index, 1)
            self.assertEqual(len(session.page_paths), 1)
            with patch.object(prepared_prints, "MAX_REQUEST_BYTES", len(payload) * 2):
                completed = self.store.append(progress.prepared_id, 1, payload)
            self.assertEqual(completed.next_index, 2)

        oversized = payload + b"x"
        other = self.store.start(1)
        with (
            patch.object(prepared_prints, "MAX_IMAGE_BYTES", len(payload)),
            self.assertRaises(PreparedPrintTooLarge),
        ):
            self.store.append(other.prepared_id, 0, oversized)
        self.assertEqual(self.store._sessions[other.prepared_id].next_index, 0)

    def test_pixel_budget_rejects_before_write_without_advancing(self) -> None:
        progress = self.store.start(1)
        with (
            patch.object(resource_limits, "MAX_RENDER_PIXELS", 1),
            self.assertRaises(resource_limits.ResourceLimitError),
        ):
            self.store.append(progress.prepared_id, 0, _png(2, 1))
        session_directory = next(self.root.iterdir())
        self.assertEqual(list(session_directory.iterdir()), [])
        self.assertEqual(self.store._sessions[progress.prepared_id].next_index, 0)
        self.assertEqual(
            self.store.append(progress.prepared_id, 0, _png(1, 1)).next_index, 1
        )

    def test_pixel_budget_is_cumulative_across_pages(self) -> None:
        progress = self.store.start(2)
        with patch.object(resource_limits, "MAX_RENDER_PIXELS", 2):
            self.store.append(progress.prepared_id, 0, _png(2, 1))
            with self.assertRaises(resource_limits.ResourceLimitError):
                self.store.append(progress.prepared_id, 1, _png(1, 1))

        session = self.store._sessions[progress.prepared_id]
        self.assertEqual(session.next_index, 1)
        self.assertEqual(session.total_pixels, 2)
        self.assertEqual(len(session.page_paths), 1)
        with patch.object(resource_limits, "MAX_RENDER_PIXELS", 3):
            self.assertEqual(
                self.store.append(progress.prepared_id, 1, _png(1, 1)).next_index,
                2,
            )

    def test_partial_write_failure_removes_only_candidate_and_preserves_progress(
        self,
    ) -> None:
        progress = self.store.start(2)
        first = self.store.append(progress.prepared_id, 0, _png())
        session = self.store._sessions[progress.prepared_id]
        existing = session.page_paths[0]

        def partial_write(path: Path, payload: bytes) -> None:
            path.write_bytes(payload[:10])
            raise OSError("fixture short write")

        with (
            patch.object(self.store, "_write_page", side_effect=partial_write),
            self.assertRaises(OSError),
        ):
            self.store.append(progress.prepared_id, 1, _png())

        self.assertEqual(session.next_index, 1)
        self.assertEqual(session.page_paths, [existing])
        self.assertEqual(existing.read_bytes(), _png())
        self.assertEqual(
            sorted(path.name for path in existing.parent.iterdir()), [existing.name]
        )
        self.assertEqual(
            self.store.append(progress.prepared_id, 1, _png()).next_index, 2
        )
        self.assertEqual(first.next_index, 1)

    def test_commit_requires_complete_pages_and_transfers_cleanup_ownership(
        self,
    ) -> None:
        progress = self.store.start(2)
        self.store.append(progress.prepared_id, 0, _png())
        with self.assertRaises(PreparedPrintConflict):
            self.store.take_for_commit(progress.prepared_id)
        self.assertEqual(self.store._sessions[progress.prepared_id].next_index, 1)

        self.store.append(progress.prepared_id, 1, _png())
        lease = self.store.take_for_commit(progress.prepared_id)
        self.assertEqual(lease.total, 2)
        self.assertEqual(len(lease.page_paths), 2)
        with self.assertRaises(FrozenInstanceError):
            lease.total = 3  # type: ignore[misc]
        with self.assertRaises(PreparedPrintConflict):
            self.store.take_for_commit(progress.prepared_id)
        with self.assertRaises(PreparedPrintConflict):
            self.store.cancel(progress.prepared_id)

        clock_before = self.store._sessions[progress.prepared_id].last_touch
        self.store.close()
        self.assertTrue(all(path.exists() for path in lease.page_paths))
        self.assertGreaterEqual(
            self.store._sessions[progress.prepared_id].last_touch, clock_before
        )
        self.assertTrue(self.store.finish(lease))
        self.assertTrue(all(not path.exists() for path in lease.page_paths))
        self.assertFalse(self.store.finish(lease))

    def test_concurrent_commits_transfer_one_lease(self) -> None:
        progress = self.store.start(1)
        self.store.append(progress.prepared_id, 0, _png())
        barrier = Barrier(3)

        def commit() -> PreparedPrintLease | None:
            barrier.wait()
            try:
                return self.store.take_for_commit(progress.prepared_id)
            except PreparedPrintConflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(commit) for _ in range(2)]
            barrier.wait()
            results = [future.result(timeout=2) for future in futures]
        leases = [result for result in results if result is not None]
        self.assertEqual(len(leases), 1)
        self.assertTrue(self.store.finish(leases[0]))

    def test_cancel_removes_preparing_session_and_files(self) -> None:
        progress = self.store.start(1)
        self.store.append(progress.prepared_id, 0, _png())
        session_directory = next(self.root.iterdir())
        self.store.cancel(progress.prepared_id)
        self.assertFalse(session_directory.exists())
        with self.assertRaises(PreparedPrintNotFound):
            self.store.cancel(progress.prepared_id)


if __name__ == "__main__":
    unittest.main()
