from __future__ import annotations

import asyncio
import tempfile
import unittest
from collections.abc import Callable
from io import BytesIO
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image

from catlabel.api import routes_prepared_print, routes_print
from catlabel.services.prepared_prints import PreparedPrintNotFound, PreparedPrintStore


def _png(
    width: int = 2, height: int = 1, color: tuple[int, int, int] = (8, 9, 10)
) -> bytes:
    with Image.new("RGB", (width, height), color) as image, BytesIO() as output:
        image.save(output, format="PNG")
        return output.getvalue()


class _TrackingUpload(UploadFile):
    def __init__(self, payload: bytes) -> None:
        self.read_limits: list[int] = []
        self.close_calls = 0
        super().__init__(filename="page.png", file=BytesIO(payload))

    async def read(self, size: int = -1) -> bytes:
        self.read_limits.append(size)
        return await super().read(size)

    async def close(self) -> None:
        self.close_calls += 1
        await super().close()


class PreparedPrintRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="catlabel-prepared-route-")
        self.store = PreparedPrintStore(temp_root=self.temporary.name)
        self.app = FastAPI()
        self.app.state.prepared_print_store = self.store
        self.app.include_router(routes_prepared_print.router)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.addCleanup(self.store.close)
        self.addCleanup(self.temporary.cleanup)

    def _request(self) -> Request:
        return Request(
            {
                "type": "http",
                "app": self.app,
                "headers": [],
                "method": "POST",
                "path": "/api/print/prepared/test",
                "query_string": b"",
            }
        )

    def _start(self, expected_jobs: int = 1) -> str:
        response = self.client.post(
            "/api/print/prepared", json={"expected_jobs": expected_jobs}
        )
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertEqual(payload["total"], expected_jobs)
        self.assertEqual(payload["next_index"], 0)
        return payload["prepared_id"]

    def _append(self, prepared_id: str, index: int, payload: bytes) -> Response:
        return self.client.post(
            f"/api/print/prepared/{prepared_id}/pages/{index}",
            files={"file": ("ignored-client-name.png", payload, "image/png")},
        )

    def test_start_and_append_report_strict_progress_and_http_conflicts(self) -> None:
        for value in (True, 0, 501, "2"):
            with self.subTest(value=value):
                response = self.client.post(
                    "/api/print/prepared", json={"expected_jobs": value}
                )
                self.assertEqual(response.status_code, 422)

        prepared_id = self._start(2)
        self.assertEqual(self._append(prepared_id, 1, _png()).status_code, 409)
        self.assertEqual(self._append(prepared_id, 0, b"not png").status_code, 422)
        first = self._append(prepared_id, 0, _png())
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["next_index"], 1)
        self.assertEqual(self._append(prepared_id, 0, _png()).status_code, 409)
        self.assertEqual(
            self.client.post(
                f"/api/print/prepared/{prepared_id}/commit",
                json={"mac_address": "AA:BB:CC:DD:EE:FF"},
            ).status_code,
            409,
        )
        second = self._append(prepared_id, 1, _png(1, 2))
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["next_index"], 2)

    def test_api_returns_503_when_all_preparation_slots_are_occupied(self) -> None:
        prepared_ids = [self._start() for _ in range(4)]
        full = self.client.post("/api/print/prepared", json={"expected_jobs": 1})
        self.assertEqual(full.status_code, 503)
        self.assertEqual(
            self.client.delete(f"/api/print/prepared/{prepared_ids[0]}").status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/print/prepared", json={"expected_jobs": 1}
            ).status_code,
            201,
        )

    def test_unavailable_storage_preserves_service_unavailable_status(self) -> None:
        self.app.state.prepared_print_store = None
        responses = [
            self.client.post("/api/print/prepared", json={"expected_jobs": 1}),
            self.client.delete("/api/print/prepared/missing"),
            self._append("missing", 0, _png()),
            self.client.post(
                "/api/print/prepared/missing/commit",
                json={"mac_address": "AA:BB:CC:DD:EE:FF"},
            ),
        ]
        self.assertEqual([response.status_code for response in responses], [503] * 4)

    def test_upload_reads_only_one_byte_past_cap_and_closes_on_size_failure(
        self,
    ) -> None:
        prepared_id = self._start()
        upload = _TrackingUpload(b"12345678")
        with (
            patch.object(routes_prepared_print, "MAX_IMAGE_BYTES", 7),
            self.assertRaises(HTTPException) as raised,
        ):
            asyncio.run(
                routes_prepared_print.append_prepared_print_page(
                    self._request(), prepared_id, 0, upload
                )
            )
        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(upload.read_limits, [8])
        self.assertEqual(upload.close_calls, 1)
        self.assertTrue(upload.file.closed)
        self.assertEqual(self.store._sessions[prepared_id].next_index, 0)

        invalid = _TrackingUpload(b"not a PNG")
        with self.assertRaises(HTTPException) as invalid_raised:
            asyncio.run(
                routes_prepared_print.append_prepared_print_page(
                    self._request(), prepared_id, 0, invalid
                )
            )
        self.assertEqual(invalid_raised.exception.status_code, 422)
        self.assertEqual(invalid.close_calls, 1)
        self.assertTrue(invalid.file.closed)

    def test_discard_removes_pages_and_unknown_session_returns_not_found(self) -> None:
        prepared_id = self._start()
        self.assertEqual(self._append(prepared_id, 0, _png()).status_code, 200)
        session = self.store._sessions[prepared_id]
        page_path = session.page_paths[0]
        self.assertTrue(page_path.exists())

        response = self.client.delete(f"/api/print/prepared/{prepared_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"status": "discarded"})
        self.assertFalse(page_path.exists())
        missing = self.client.delete(f"/api/print/prepared/{prepared_id}")
        self.assertEqual(missing.status_code, 404)

    def test_commit_decodes_all_pages_before_claimed_print_and_cleans_lease(
        self,
    ) -> None:
        prepared_id = self._start(2)
        self.assertEqual(
            self._append(prepared_id, 0, _png(color=(1, 2, 3))).status_code, 200
        )
        self.assertEqual(
            self._append(prepared_id, 1, _png(1, 2, color=(4, 5, 6))).status_code, 200
        )
        lease_paths = tuple(self.store._sessions[prepared_id].page_paths)
        claimed: list[
            tuple[str, list[tuple[tuple[int, int], tuple[int, int, int]]], bool, bool]
        ] = []

        async def fake_claimed(
            mac_address: str,
            images: list[Image.Image],
            split_mode: bool,
            dither: bool,
            _job_id: str,
        ) -> dict[str, object]:
            claimed.append(
                (
                    mac_address,
                    [
                        (
                            image.size,
                            cast(tuple[int, int, int], image.getpixel((0, 0))),
                        )
                        for image in images
                    ],
                    split_mode,
                    dither,
                )
            )
            return {"status": "submitted", "submitted": len(images)}

        with patch.object(
            routes_print, "_execute_claimed_print_jobs", new=fake_claimed
        ):
            response = self.client.post(
                f"/api/print/prepared/{prepared_id}/commit",
                json={
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "split_mode": True,
                    "is_rotated": True,
                    "dither": False,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"status": "submitted", "submitted": 2})
        self.assertEqual(
            claimed,
            [
                (
                    "AA:BB:CC:DD:EE:FF",
                    [((1, 2), (1, 2, 3)), ((2, 1), (4, 5, 6))],
                    True,
                    False,
                )
            ],
        )
        self.assertTrue(all(not path.exists() for path in lease_paths))
        self.assertEqual(
            self.client.post(
                f"/api/print/prepared/{prepared_id}/commit",
                json={"mac_address": "AA:BB:CC:DD:EE:FF"},
            ).status_code,
            404,
        )
        self.assertEqual(len(claimed), 1)

    def test_corrupt_png_fails_decode_before_claim_and_releases_storage(self) -> None:
        prepared_id = self._start()
        corrupt = bytearray(_png())
        data_offset = corrupt.index(b"IDAT") + 4
        corrupt[data_offset] ^= 0xFF
        staged = self._append(prepared_id, 0, bytes(corrupt))
        self.assertEqual(staged.status_code, 200, staged.text)
        page_path = self.store._sessions[prepared_id].page_paths[0]

        with patch.object(
            routes_print, "_execute_claimed_print_jobs", new=AsyncMock()
        ) as claimed:
            response = self.client.post(
                f"/api/print/prepared/{prepared_id}/commit",
                json={"mac_address": "AA:BB:CC:DD:EE:FF"},
            )

        self.assertEqual(response.status_code, 422, response.text)
        claimed.assert_not_awaited()
        self.assertFalse(page_path.exists())
        self.assertEqual(
            self.client.post(
                f"/api/print/prepared/{prepared_id}/commit",
                json={"mac_address": "AA:BB:CC:DD:EE:FF"},
            ).status_code,
            404,
        )

    def test_commit_exception_and_cancellation_always_finish_lease(self) -> None:
        prepared_id = self._start()
        self.assertEqual(self._append(prepared_id, 0, _png()).status_code, 200)
        page_path = self.store._sessions[prepared_id].page_paths[0]
        with (
            patch.object(
                routes_prepared_print,
                "execute_owned_print_jobs",
                new=AsyncMock(side_effect=RuntimeError("fixture failure")),
            ),
            self.assertRaises(RuntimeError),
        ):
            asyncio.run(
                routes_prepared_print.commit_prepared_print(
                    self._request(),
                    prepared_id,
                    routes_prepared_print.PreparedPrintCommitRequest(
                        mac_address="AA:BB:CC:DD:EE:FF"
                    ),
                )
            )
        self.assertFalse(page_path.exists())
        with self.assertRaises(PreparedPrintNotFound):
            self.store.take_for_commit(prepared_id)

        cancelled_id = self._start()
        self.assertEqual(self._append(cancelled_id, 0, _png()).status_code, 200)
        cancelled_path = self.store._sessions[cancelled_id].page_paths[0]
        with (
            patch.object(
                routes_prepared_print,
                "execute_owned_print_jobs",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            asyncio.run(
                routes_prepared_print.commit_prepared_print(
                    self._request(),
                    cancelled_id,
                    routes_prepared_print.PreparedPrintCommitRequest(
                        mac_address="AA:BB:CC:DD:EE:FF"
                    ),
                )
            )
        self.assertFalse(cancelled_path.exists())
        with self.assertRaises(PreparedPrintNotFound):
            self.store.take_for_commit(cancelled_id)

    def test_decoder_closes_partial_image_on_non_exception_baseexception(self) -> None:
        class _DecodeAbort(BaseException):
            pass

        converted: list[Image.Image] = []
        convert = cast(Callable[..., Image.Image], Image.Image.convert)

        def capture_convert(
            image: Image.Image, *args: Any, **kwargs: Any
        ) -> Image.Image:
            decoded = convert(image, *args, **kwargs)
            converted.append(decoded)
            return decoded

        with (
            patch.object(Image.Image, "convert", new=capture_convert),
            patch.object(Image.Image, "rotate", side_effect=_DecodeAbort),
            self.assertRaises(_DecodeAbort),
        ):
            routes_prepared_print._decode_prepared_png(
                _png(), rotate=True, pixels_so_far=0
            )

        self.assertEqual(len(converted), 1)
        with self.assertRaises(ValueError):
            converted[0].getpixel((0, 0))


if __name__ == "__main__":
    unittest.main()
