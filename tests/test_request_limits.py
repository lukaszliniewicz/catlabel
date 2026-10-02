from __future__ import annotations

import unittest
from collections import deque

from starlette.types import Message, Scope

from catlabel.api.request_limits import RequestLimitsMiddleware


def _http_scope(
    path: str = "/api/test", headers: list[tuple[bytes, bytes]] | None = None
) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }


class RequestLimitsMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def _invoke(
        self,
        messages: list[Message],
        *,
        headers: list[tuple[bytes, bytes]] | None = None,
        path: str = "/api/test",
        max_bytes: int = 10,
    ) -> tuple[list[Message], list[Message], int, int]:
        pending = deque(messages)
        received_by_app: list[Message] = []
        sent: list[Message] = []
        receive_calls = 0
        app_calls = 0

        async def receive() -> Message:
            nonlocal receive_calls
            receive_calls += 1
            if pending:
                return pending.popleft()
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            sent.append(message)

        async def app(scope: Scope, app_receive, app_send) -> None:
            nonlocal app_calls
            app_calls += 1
            while True:
                message = await app_receive()
                received_by_app.append(message)
                if message["type"] == "http.disconnect":
                    break
                if message["type"] == "http.request" and not message.get(
                    "more_body", False
                ):
                    break
            await app_send(
                {"type": "http.response.start", "status": 204, "headers": []}
            )
            await app_send({"type": "http.response.body", "body": b""})

        middleware = RequestLimitsMiddleware(app, max_bytes=max_bytes)
        await middleware(_http_scope(path, headers), receive, send)
        return sent, received_by_app, receive_calls, app_calls

    async def test_multipart_and_arbitrary_chunks_replay_original_messages(
        self,
    ) -> None:
        messages: list[Message] = [
            {
                "type": "http.request",
                "body": b"--example\r\nContent-Disposition: form-data;",
                "more_body": True,
            },
            {
                "type": "http.request",
                "body": b"\r\nvalue=x\r\n--example--",
                "more_body": False,
            },
        ]
        body_length = sum(len(message["body"]) for message in messages)
        headers = [
            (b"content-type", b"multipart/form-data; boundary=example"),
            (b"content-length", str(body_length).encode("ascii")),
        ]
        sent, replayed, calls, app_calls = await self._invoke(
            messages, headers=headers, max_bytes=body_length
        )
        self.assertEqual(app_calls, 1)
        self.assertEqual(calls, len(messages))
        self.assertEqual(replayed, messages)
        self.assertTrue(
            all(
                actual is expected
                for actual, expected in zip(replayed, messages, strict=True)
            )
        )
        self.assertEqual(sent[0]["status"], 204)

    async def test_exact_body_limit_is_accepted_across_multiple_chunks(self) -> None:
        messages: list[Message] = [
            {"type": "http.request", "body": b"1234", "more_body": True},
            {"type": "http.request", "body": b"567890", "more_body": False},
        ]
        sent, replayed, calls, app_calls = await self._invoke(
            messages, headers=[(b"content-length", b"10")]
        )
        self.assertEqual((app_calls, calls), (1, 2))
        self.assertEqual(replayed, messages)
        self.assertEqual(sent[0]["status"], 204)

    async def test_declared_over_limit_rejects_without_reading_or_calling_handler(
        self,
    ) -> None:
        sent, replayed, calls, app_calls = await self._invoke(
            [], headers=[(b"content-length", b"11")]
        )
        self.assertEqual((calls, app_calls, replayed), (0, 0, []))
        self.assertEqual(sent[0]["status"], 413)

    async def test_malformed_negative_and_duplicate_lengths_reject_without_reading(
        self,
    ) -> None:
        bad_headers = (
            [(b"content-length", b"")],
            [(b"content-length", b"abc")],
            [(b"content-length", b"-1")],
            [(b"content-length", b"+1")],
            [(b"content-length", b"1 ")],
            [(b"content-length", b"1"), (b"content-length", b"1")],
        )
        for headers in bad_headers:
            with self.subTest(headers=headers):
                sent, _, calls, app_calls = await self._invoke([], headers=headers)
                self.assertEqual((calls, app_calls), (0, 0))
                self.assertEqual(sent[0]["status"], 400)

    async def test_long_decimal_length_is_classified_without_integer_overflow(
        self,
    ) -> None:
        sent, _, calls, app_calls = await self._invoke(
            [], headers=[(b"content-length", b"9" * 5000)]
        )
        self.assertEqual((calls, app_calls), (0, 0))
        self.assertEqual(sent[0]["status"], 413)

    async def test_actual_overflow_rejects_lies_and_chunked_bodies_before_handler(
        self,
    ) -> None:
        messages: list[Message] = [
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"78901", "more_body": True},
            {"type": "http.request", "body": b"ignored", "more_body": False},
        ]
        for headers in ([], [(b"content-length", b"1")]):
            with self.subTest(headers=headers):
                sent, replayed, calls, app_calls = await self._invoke(
                    messages.copy(), headers=headers
                )
                self.assertEqual((calls, app_calls, replayed), (2, 0, []))
                self.assertEqual(sent[0]["status"], 413)
                error_body = sent[1]["body"]
                self.assertNotIn(b"123456", error_body)
                self.assertNotIn(b"78901", error_body)

    async def test_disconnect_during_buffering_never_calls_handler_or_sends_response(
        self,
    ) -> None:
        messages: list[Message] = [
            {"type": "http.request", "body": b"part", "more_body": True},
            {"type": "http.disconnect"},
        ]
        sent, replayed, calls, app_calls = await self._invoke(messages)
        self.assertEqual((calls, app_calls, replayed, sent), (2, 0, [], []))

    async def test_non_api_static_paths_pass_through_without_body_gate(self) -> None:
        messages: list[Message] = [
            {"type": "http.request", "body": b"01234567890", "more_body": False}
        ]
        sent, replayed, calls, app_calls = await self._invoke(
            messages,
            headers=[(b"content-length", b"11"), (b"content-length", b"11")],
            path="/static/image.bin",
            max_bytes=10,
        )
        self.assertEqual((calls, app_calls), (1, 1))
        self.assertEqual(replayed, messages)
        self.assertEqual(sent[0]["status"], 204)

    async def test_lifespan_scope_passes_through(self) -> None:
        seen: list[Message] = []
        sent: list[Message] = []

        async def receive() -> Message:
            return {"type": "lifespan.startup"}

        async def send(message: Message) -> None:
            sent.append(message)

        async def app(scope: Scope, app_receive, app_send) -> None:
            seen.append(await app_receive())
            await app_send({"type": "lifespan.startup.complete"})

        middleware = RequestLimitsMiddleware(app, max_bytes=1)
        await middleware({"type": "lifespan"}, receive, send)
        self.assertEqual(seen, [{"type": "lifespan.startup"}])
        self.assertEqual(sent, [{"type": "lifespan.startup.complete"}])


if __name__ == "__main__":
    unittest.main()
