from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlmodel import SQLModel

from catlabel.services.artifacts import ArtifactStore
from catlabel.services.print_jobs import JobError, PrintJobCoordinator
from catlabel.services.printers import ServiceError


class PrintJobCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="catlabel-jobs-")
        self.root = Path(self.temporary.name)
        self.engine = create_engine(
            f"sqlite:///{self.root / 'catlabel.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)
        self.artifacts = ArtifactStore(self.engine, self.root / "artifacts")
        self.coordinators: list[PrintJobCoordinator] = []

    async def asyncTearDown(self) -> None:
        for coordinator in reversed(self.coordinators):
            await coordinator.close()
        self.artifacts.close()
        self.engine.dispose()
        self.temporary.cleanup()

    def coordinator(
        self,
        executor_impl=None,
        *,
        max_active: int = 4,
    ) -> PrintJobCoordinator:
        if executor_impl is None:

            async def default_executor(manifest, before_delivery):
                await before_delivery()
                return {"submission_id": "fixture"}

            executor_impl = default_executor

        coordinator = PrintJobCoordinator(
            self.engine, self.artifacts, executor_impl, max_active=max_active
        )
        self.coordinators.append(coordinator)
        return coordinator

    def source(self, payload: bytes = b"rendered-page") -> str:
        return self.artifacts.put_bytes(
            payload,
            mime_type="image/png",
            kind="rendered_page",
            ttl_seconds=3_600,
        )["id"]

    def plan(
        self,
        coordinator: PrintJobCoordinator,
        *,
        artifact_ids: list[str] | None = None,
        ttl_seconds: int = 900,
        value: str = "label",
    ) -> dict[str, Any]:
        return coordinator.create_plan(
            {"labels": [{"text": value}], "printer_id": "fixture-printer"},
            [self.source()] if artifact_ids is None else artifact_ids,
            ttl_seconds=ttl_seconds,
        )

    async def wait_for_state(
        self,
        coordinator: PrintJobCoordinator,
        job_id: str,
        expected: str,
    ) -> dict[str, Any]:
        for _ in range(200):
            result = coordinator.job_get(job_id, "credential-1")
            if result["state"] == expected:
                return result
            await asyncio.sleep(0.005)
        self.fail(f"job {job_id} did not reach {expected}")

    async def test_same_key_concurrent_start_runs_executor_once(self) -> None:
        calls = 0
        calls_lock = threading.Lock()

        async def executor(manifest, before_delivery):
            nonlocal calls
            with calls_lock:
                calls += 1
            await before_delivery()
            await asyncio.sleep(0.01)
            return {"submission_id": "single"}

        coordinators = [self.coordinator(executor), self.coordinator(executor)]
        plan = self.plan(coordinators[0])
        barrier = threading.Barrier(2)

        def start_concurrently(coordinator: PrintJobCoordinator) -> dict[str, Any]:
            async def start_and_drain() -> dict[str, Any]:
                barrier.wait(timeout=5)
                result = await coordinator.start(
                    plan["id"], plan["plan_hash"], "same-key", "credential-1"
                )
                await asyncio.sleep(0.04)
                return result

            return asyncio.run(start_and_drain())

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(start_concurrently, item) for item in coordinators]
            results = [future.result(timeout=10) for future in futures]

        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(calls, 1)
        self.assertEqual(
            coordinators[0].job_get(results[0]["id"], "credential-1")["state"],
            "submitted",
        )
        with self.engine.connect() as connection:
            stored_manifest = connection.exec_driver_sql(
                "SELECT manifest_json FROM printjobrecord WHERE id = ?",
                (results[0]["id"],),
            ).scalar_one()
        self.assertEqual(stored_manifest, "{}")
        repeated = await coordinators[0].start(
            plan["id"], plan["plan_hash"], "same-key", "credential-1"
        )
        self.assertEqual(repeated["id"], results[0]["id"])

    async def test_same_key_with_different_plan_conflicts(self) -> None:
        coordinator = self.coordinator()
        first = self.plan(coordinator, value="first")
        second = self.plan(coordinator, value="second")
        await coordinator.start(
            first["id"], first["plan_hash"], "stable", "credential-1"
        )

        with self.assertRaises(JobError) as raised:
            await coordinator.start(
                second["id"], second["plan_hash"], "stable", "credential-1"
            )
        self.assertEqual(raised.exception.code, "idempotency_conflict")

    async def test_expired_plan_rejects_new_key_but_same_key_returns_job(self) -> None:
        gate = asyncio.Event()
        executor_started = asyncio.Event()

        async def executor(manifest, before_delivery):
            executor_started.set()
            await gate.wait()
            await before_delivery()
            return {"submission_id": "after-release"}

        coordinator = self.coordinator(executor)
        with patch("catlabel.services.print_jobs.time.time", return_value=1_000.0):
            plan = self.plan(coordinator, ttl_seconds=60)
            started = await coordinator.start(
                plan["id"], plan["plan_hash"], "retry-stable", "credential-1"
            )
            await executor_started.wait()

        with patch("catlabel.services.print_jobs.time.time", return_value=1_061.0):
            repeated = await coordinator.start(
                plan["id"], plan["plan_hash"], "retry-stable", "credential-1"
            )
            self.assertEqual(repeated["id"], started["id"])
            with self.assertRaises(JobError) as raised:
                await coordinator.start(
                    plan["id"], plan["plan_hash"], "new-key", "credential-1"
                )
        self.assertEqual(raised.exception.code, "plan_expired")
        await coordinator.close()
        self.assertEqual(
            coordinator.job_get(started["id"], "credential-1")["state"],
            "cancelled_before_delivery",
        )

    async def test_caller_disconnect_does_not_cancel_owned_executor_task(self) -> None:
        gate = asyncio.Event()
        executor_started = asyncio.Event()
        calls = 0

        async def executor(manifest, before_delivery):
            nonlocal calls
            calls += 1
            executor_started.set()
            await gate.wait()
            await before_delivery()
            return {"submission_id": "owned"}

        coordinator = self.coordinator(executor)
        plan = self.plan(coordinator)
        accepted = await coordinator.start(
            plan["id"], plan["plan_hash"], "disconnect", "credential-1"
        )
        await executor_started.wait()
        self.assertEqual(accepted["state"], "accepted")

        # The caller has returned and has no task handle to cancel.
        gate.set()
        submitted = await self.wait_for_state(coordinator, accepted["id"], "submitted")
        self.assertEqual(submitted["delivery_verification"], "unverified")
        self.assertEqual(calls, 1)

    async def test_startup_recovery_marks_interrupted_sending_uncertain_without_replay(
        self,
    ) -> None:
        entered_executor = asyncio.Event()
        finish_executor = asyncio.Event()
        calls = 0

        async def executor(manifest, before_delivery):
            nonlocal calls
            calls += 1
            await before_delivery()
            entered_executor.set()
            await finish_executor.wait()
            return {"submission_id": "possibly-sent"}

        original = self.coordinator(executor)
        plan = self.plan(original)
        accepted = await original.start(
            plan["id"], plan["plan_hash"], "crash", "credential-1"
        )
        await entered_executor.wait()

        recovered = self.coordinator(executor)
        uncertain = recovered.job_get(accepted["id"], "credential-1")
        self.assertEqual(uncertain["state"], "delivery_uncertain")
        self.assertEqual(calls, 1)

        finish_executor.set()
        await asyncio.sleep(0.02)
        self.assertEqual(
            recovered.job_get(accepted["id"], "credential-1")["state"],
            "delivery_uncertain",
        )
        self.assertEqual(calls, 1)

    async def test_cancel_compare_and_set_wins_before_executor_boundary(self) -> None:
        gate = asyncio.Event()
        executor_started = asyncio.Event()
        device_actions = 0

        async def executor(manifest, before_delivery):
            nonlocal device_actions
            executor_started.set()
            await gate.wait()
            await before_delivery()
            device_actions += 1
            return {"submission_id": "must-not-run"}

        coordinator = self.coordinator(executor)
        plan = self.plan(coordinator)
        accepted = await coordinator.start(
            plan["id"], plan["plan_hash"], "cancel-race", "credential-1"
        )
        await executor_started.wait()
        cancelled = await coordinator.cancel(accepted["id"], "credential-1")
        self.assertEqual(cancelled["state"], "cancelled_before_delivery")

        gate.set()
        await asyncio.sleep(0.02)
        self.assertEqual(device_actions, 0)
        self.assertEqual(
            coordinator.job_get(accepted["id"], "credential-1")["state"],
            "cancelled_before_delivery",
        )

    async def test_active_limit_records_terminal_printer_busy_without_queueing(
        self,
    ) -> None:
        gate = asyncio.Event()
        entered_executor = asyncio.Event()
        calls = 0

        async def executor(manifest, before_delivery):
            nonlocal calls
            calls += 1
            entered_executor.set()
            await gate.wait()
            await before_delivery()
            return {"submission_id": "only-first"}

        coordinator = self.coordinator(executor, max_active=1)
        first = self.plan(coordinator, value="first")
        second = self.plan(coordinator, value="second")
        started = await coordinator.start(
            first["id"], first["plan_hash"], "active-one", "credential-1"
        )
        await entered_executor.wait()
        busy = await coordinator.start(
            second["id"], second["plan_hash"], "active-two", "credential-1"
        )

        self.assertEqual(busy["state"], "failed_before_delivery")
        self.assertEqual(busy["error"]["code"], "printer_busy")
        self.assertEqual(calls, 1)
        gate.set()
        await self.wait_for_state(coordinator, started["id"], "submitted")

    async def test_printer_service_errors_preserve_status_and_delivery_state(
        self,
    ) -> None:
        async def admission_error(manifest, before_delivery):
            raise ServiceError(
                409,
                {
                    "message": "Printer is already in use.",
                    "stage": "admission",
                    "error_id": "device-job",
                    "suggestion": "Wait for the current print.",
                },
            )

        coordinator = self.coordinator(admission_error)
        plan = self.plan(coordinator)
        accepted = await coordinator.start(
            plan["id"], plan["plan_hash"], "printer-admission", "credential-1"
        )
        failed = await self.wait_for_state(
            coordinator, accepted["id"], "failed_before_delivery"
        )
        self.assertEqual(failed["error"]["code"], "printer_busy")
        self.assertEqual(failed["error"]["stage"], "admission")
        self.assertEqual(failed["error"]["details"]["status_code"], 409)
        self.assertEqual(
            failed["error"]["details"]["suggestion"], "Wait for the current print."
        )

        async def post_boundary_error(manifest, before_delivery):
            await before_delivery()
            raise ServiceError(
                503,
                {
                    "code": "printer_connect_failed",
                    "message": "Connection was interrupted.",
                    "stage": "connect",
                    "delivery_uncertain": False,
                },
            )

        post_coordinator = self.coordinator(post_boundary_error)
        post_plan = self.plan(post_coordinator)
        post_accepted = await post_coordinator.start(
            post_plan["id"],
            post_plan["plan_hash"],
            "printer-connect",
            "credential-1",
        )
        uncertain = await self.wait_for_state(
            post_coordinator, post_accepted["id"], "delivery_uncertain"
        )
        self.assertEqual(uncertain["error"]["code"], "printer_connect_failed")
        self.assertEqual(uncertain["error"]["stage"], "connect")
        self.assertEqual(uncertain["error"]["details"]["status_code"], 503)
        self.assertTrue(uncertain["error"]["details"]["delivery_uncertain"])

    async def test_plan_hash_includes_ordered_source_hashes_and_detects_tampering(
        self,
    ) -> None:
        coordinator = self.coordinator()
        first = self.source(b"first")
        second = self.source(b"second")
        plan = self.plan(coordinator, artifact_ids=[second, first])

        sources = plan["manifest"]["source_artifacts"]
        self.assertEqual([source["id"] for source in sources], [second, first])
        self.assertEqual(len({source["sha256"] for source in sources}), 2)
        self.assertEqual(
            coordinator.get_plan(plan["id"], plan["plan_hash"])["plan_hash"],
            plan["plan_hash"],
        )

        (self.root / "artifacts" / f"{first}.blob").write_bytes(b"tampered")
        with self.assertRaises(JobError) as raised:
            coordinator.get_plan(plan["id"])
        self.assertEqual(raised.exception.code, "artifact_hash_mismatch")

    async def test_plan_and_uncertain_job_retention_release_pins_in_order(self) -> None:
        entered_executor = asyncio.Event()
        finish_executor = asyncio.Event()

        async def executor(manifest, before_delivery):
            await before_delivery()
            entered_executor.set()
            await finish_executor.wait()
            return {"submission_id": "possibly-sent"}

        original = self.coordinator(executor)
        with patch("catlabel.services.print_jobs.time.time", return_value=1_000.0):
            artifact_id = self.artifacts.put_bytes(
                b"retained-source",
                mime_type="image/png",
                kind="rendered_page",
                ttl_seconds=1,
            )["id"]
            plan = self.plan(original, artifact_ids=[artifact_id], ttl_seconds=20)
            job = await original.start(
                plan["id"], plan["plan_hash"], "retention", "credential-1"
            )
            await entered_executor.wait()

            recovered = self.coordinator(executor)
            self.assertEqual(
                recovered.job_get(job["id"], "credential-1")["state"],
                "delivery_uncertain",
            )

        with patch("catlabel.services.print_jobs.time.time", return_value=1_020.0):
            self.assertEqual(recovered.reap()["expired_plans"], 1)
            self.assertEqual(self.artifacts.reap(), 0)

        uncertain_expiry = 1_000.0 + 7 * 24 * 60 * 60
        with patch(
            "catlabel.services.print_jobs.time.time", return_value=uncertain_expiry
        ):
            self.assertEqual(recovered.reap()["compacted_uncertain_jobs"], 1)
            self.assertEqual(self.artifacts.reap(), 1)
            compacted = recovered.job_get(job["id"], "credential-1")
            self.assertEqual(compacted["state"], "delivery_uncertain")
            self.assertEqual(
                compacted["forensic"]["source_artifacts"][0]["id"], artifact_id
            )

        with patch(
            "catlabel.services.print_jobs.time.time",
            return_value=1_000.0 + 90 * 24 * 60 * 60 + 1,
        ):
            self.assertEqual(recovered.reap()["removed_jobs"], 1)
            with self.assertRaises(JobError) as raised:
                recovered.job_get(job["id"], "credential-1")
        self.assertEqual(raised.exception.code, "job_not_found")
        finish_executor.set()


if __name__ == "__main__":
    unittest.main()
