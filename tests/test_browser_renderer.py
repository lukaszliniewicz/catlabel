from __future__ import annotations

import asyncio
import base64
import os
import sys
import threading
import types
import unittest
from contextlib import ExitStack
from io import BytesIO
from unittest.mock import AsyncMock, patch

from PIL import Image

from catlabel.core.resource_limits import ResourceLimitError
from catlabel.rendering import template

HEADLESS_URL = "http://127.0.0.1:8765/index.html?mode=headless"


def _png() -> str:
    with Image.new("RGB", (3, 2), "white") as image, BytesIO() as output:
        image.save(output, format="PNG")
        return base64.b64encode(output.getvalue()).decode("ascii")


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class FakeFactory:
    def __init__(
        self,
        *,
        wait_gate: asyncio.Event | None = None,
        identity_gate: asyncio.Event | None = None,
        status: int = 200,
        identity: bool = True,
        outputs: list[object] | None = None,
        launch_error: Exception | None = None,
        launch_gate: asyncio.Event | None = None,
        new_page_error: Exception | None = None,
        encoded_chars_override: int | None = None,
        context_close_gate: asyncio.Event | None = None,
        context_close_error: Exception | None = None,
        browser_close_error: Exception | None = None,
        stop_error: Exception | None = None,
    ) -> None:
        self.wait_gate = wait_gate
        self.identity_gate = identity_gate
        self.status = status
        self.identity = identity
        self.outputs = [_png()] if outputs is None else outputs
        self.launch_error = launch_error
        self.launch_gate = launch_gate
        self.new_page_error = new_page_error
        self.encoded_chars_override = encoded_chars_override
        self.context_close_gate = context_close_gate
        self.context_close_error = context_close_error
        self.browser_close_error = browser_close_error
        self.stop_error = stop_error
        self.playwrights: list[FakePlaywright] = []
        self.browsers: list[FakeBrowser] = []
        self.contexts: list[FakeContext] = []
        self.pages: list[FakePage] = []
        self.started: asyncio.Queue[FakePage] = asyncio.Queue()
        self.loops: list[asyncio.AbstractEventLoop] = []
        self.transferred_outputs = 0
        self.payload_injected = False
        self.identity_wait_started = asyncio.Event()
        self.identity_wait_timeout_ms: int | None = None
        self.launch_calls = 0
        self.launch_started = asyncio.Event()

    def async_playwright(self) -> FakePlaywrightManager:
        return FakePlaywrightManager(self)

    def patch_import(self) -> ExitStack:
        package = types.ModuleType("playwright")
        package.__path__ = []  # type: ignore[attr-defined]
        module = types.ModuleType("playwright.async_api")
        module.async_playwright = self.async_playwright  # type: ignore[attr-defined]
        stack = ExitStack()
        stack.enter_context(
            patch.dict(
                sys.modules,
                {"playwright": package, "playwright.async_api": module},
            )
        )
        stack.enter_context(
            patch.dict(os.environ, {"CATLABEL_HEADLESS_URL": HEADLESS_URL})
        )
        return stack

    def record_loop(self) -> None:
        self.loops.append(asyncio.get_running_loop())


class FakePlaywrightManager:
    def __init__(self, factory: FakeFactory) -> None:
        self.factory = factory

    async def start(self) -> FakePlaywright:
        self.factory.record_loop()
        playwright = FakePlaywright(self.factory)
        self.factory.playwrights.append(playwright)
        return playwright


class FakePlaywright:
    def __init__(self, factory: FakeFactory) -> None:
        self.factory = factory
        self.chromium = FakeChromium(factory)
        self.stop_calls = 0

    async def stop(self) -> None:
        self.factory.record_loop()
        self.stop_calls += 1
        if self.factory.stop_error is not None:
            raise self.factory.stop_error


class FakeChromium:
    def __init__(self, factory: FakeFactory) -> None:
        self.factory = factory

    async def launch(self, *, headless: bool) -> FakeBrowser:
        self.factory.record_loop()
        self.factory.launch_calls += 1
        self.factory.launch_started.set()
        if self.factory.launch_gate is not None:
            await self.factory.launch_gate.wait()
        if self.factory.launch_error is not None:
            raise self.factory.launch_error
        if headless is not True:
            raise AssertionError("renderer must launch Chromium headlessly")
        browser = FakeBrowser(self.factory)
        self.factory.browsers.append(browser)
        return browser


class FakeBrowser:
    def __init__(self, factory: FakeFactory) -> None:
        self.factory = factory
        self.connected = True
        self.close_calls = 0

    def is_connected(self) -> bool:
        self.factory.record_loop()
        return self.connected

    async def new_context(self) -> FakeContext:
        self.factory.record_loop()
        context = FakeContext(self.factory)
        self.factory.contexts.append(context)
        return context

    async def close(self) -> None:
        self.factory.record_loop()
        self.close_calls += 1
        self.connected = False
        if self.factory.browser_close_error is not None:
            raise self.factory.browser_close_error


class FakeContext:
    def __init__(self, factory: FakeFactory) -> None:
        self.factory = factory
        self.closed = asyncio.Event()
        self.close_calls = 0
        self.page: FakePage | None = None

    async def new_page(self) -> FakePage:
        self.factory.record_loop()
        if self.factory.new_page_error is not None:
            raise self.factory.new_page_error
        self.page = FakePage(self.factory, self)
        self.factory.pages.append(self.page)
        return self.page

    async def close(self) -> None:
        self.factory.record_loop()
        self.close_calls += 1
        self.closed.set()
        if self.factory.context_close_gate is not None:
            await self.factory.context_close_gate.wait()
        if self.factory.context_close_error is not None:
            raise self.factory.context_close_error


class FakePage:
    def __init__(self, factory: FakeFactory, context: FakeContext) -> None:
        self.factory = factory
        self.context = context
        self.navigations: list[tuple[str, str]] = []
        self.default_timeout: int | None = None
        self.wait_started = asyncio.Event()
        self.wait_cancelled = False
        self.close_calls = 0

    def set_default_timeout(self, timeout: int) -> None:
        self.factory.record_loop()
        self.default_timeout = timeout

    async def goto(self, url: str, *, wait_until: str) -> FakeResponse:
        self.factory.record_loop()
        self.navigations.append((url, wait_until))
        return FakeResponse(self.factory.status)

    async def evaluate(self, expression: str, argument: object = None) -> object:
        self.factory.record_loop()
        if expression.startswith("(payload)"):
            self.factory.payload_injected = True
            return None
        if expression == "window.__RENDER_ERROR__ || null":
            return None
        if "encodedChars" in expression and "__RENDERED_IMAGES__" in expression:
            encoded_chars = sum(
                len(value) for value in self.factory.outputs if isinstance(value, str)
            )
            if self.factory.encoded_chars_override is not None:
                encoded_chars = self.factory.encoded_chars_override
            return {
                "isArray": isinstance(self.factory.outputs, list),
                "count": len(self.factory.outputs),
                "encodedChars": encoded_chars,
                "invalidCount": sum(
                    not isinstance(value, str) for value in self.factory.outputs
                ),
            }
        if expression == "window.__CATLABEL_RENDERED_IMAGE_SNAPSHOT__ || []":
            self.factory.transferred_outputs += 1
            return self.factory.outputs
        raise AssertionError(f"Unexpected page.evaluate expression: {expression}")

    async def wait_for_function(self, expression: str, *, timeout: int) -> object:
        self.factory.record_loop()
        if expression != "window.__CATLABEL_HEADLESS_VERSION__ === 1":
            raise AssertionError("renderer must wait for the headless identity marker")
        self.factory.identity_wait_timeout_ms = timeout
        self.factory.identity_wait_started.set()
        if self.factory.identity_gate is None:
            if not self.factory.identity:
                raise TimeoutError("identity marker did not appear")
            return object()

        identity_wait = asyncio.create_task(self.factory.identity_gate.wait())
        close_wait = asyncio.create_task(self.context.closed.wait())
        try:
            done, _ = await asyncio.wait(
                (identity_wait, close_wait), return_when=asyncio.FIRST_COMPLETED
            )
            if close_wait in done:
                raise RuntimeError("context closed")
            if not self.factory.identity:
                raise TimeoutError("identity marker did not appear")
            return object()
        finally:
            for waiter in (identity_wait, close_wait):
                if not waiter.done():
                    waiter.cancel()
            await asyncio.gather(identity_wait, close_wait, return_exceptions=True)

    async def wait_for_selector(self, selector: str, *, state: str) -> object:
        self.factory.record_loop()
        if selector != "#render-done" or state != "attached":
            raise AssertionError("renderer must wait for the render-done contract")
        self.wait_started.set()
        self.factory.started.put_nowait(self)
        if self.factory.wait_gate is None:
            if self.context.closed.is_set():
                raise RuntimeError("context closed")
            return object()

        gate_wait = asyncio.create_task(self.factory.wait_gate.wait())
        close_wait = asyncio.create_task(self.context.closed.wait())
        try:
            done, pending = await asyncio.wait(
                (gate_wait, close_wait), return_when=asyncio.FIRST_COMPLETED
            )
            if close_wait in done:
                raise RuntimeError("context closed")
            return object()
        except asyncio.CancelledError:
            self.wait_cancelled = True
            raise
        finally:
            for waiter in (gate_wait, close_wait):
                if not waiter.done():
                    waiter.cancel()
            await asyncio.gather(gate_wait, close_wait, return_exceptions=True)

    async def close(self) -> None:
        self.factory.record_loop()
        self.close_calls += 1


class BrowserRendererTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_jobs_share_one_loop_and_fifth_is_rejected(self) -> None:
        gate = asyncio.Event()
        factory = FakeFactory(wait_gate=gate)
        renderer = template.BrowserRenderer()
        with factory.patch_import():
            jobs = [asyncio.create_task(renderer.render({}, [{}])) for _ in range(4)]
            first_pages = [
                await asyncio.wait_for(factory.started.get(), 1) for _ in range(2)
            ]
            self.assertEqual(len(factory.contexts), 2)
            self.assertEqual(renderer._admitted, 4)
            with self.assertRaises(template.RenderBusyError):
                await renderer.render({}, [{}])

            gate.set()
            results = await asyncio.gather(*jobs)
            for images in results:
                for image in images:
                    image.close()
            self.assertEqual(len(first_pages), 2)
            self.assertEqual(len(factory.contexts), 4)
            self.assertEqual(renderer._admitted, 0)
            self.assertEqual(set(factory.loops), {asyncio.get_running_loop()})
            self.assertTrue(
                all(
                    page.navigations == [(HEADLESS_URL, "domcontentloaded")]
                    for page in factory.pages
                )
            )
            await renderer.close()

    async def test_page_timeout_uses_job_deadline_and_queue_wait_is_bounded(
        self,
    ) -> None:
        factory = FakeFactory()
        renderer = template.BrowserRenderer()
        with factory.patch_import():
            images = await renderer.render({}, [{}])
            images[0].close()
            self.assertEqual(factory.pages[-1].default_timeout, 30_250)
            await renderer.close()

        gate = asyncio.Event()
        factory = FakeFactory(wait_gate=gate)
        renderer = template.BrowserRenderer()
        with (
            factory.patch_import(),
            patch.object(template, "RENDER_BASE_TIMEOUT_SECONDS", 0.02),
            patch.object(template, "RENDER_PER_JOB_TIMEOUT_SECONDS", 0.05),
        ):
            factory.outputs = [_png(), _png()]
            active = [
                asyncio.create_task(renderer.render({}, [{}], copies=2))
                for _ in range(2)
            ]
            await asyncio.wait_for(factory.started.get(), 1)
            await asyncio.wait_for(factory.started.get(), 1)
            queued = asyncio.create_task(renderer.render({}, [{}]))
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(queued, 1)
            self.assertEqual(len(factory.contexts), 2)
            self.assertEqual(renderer._admitted, 2)
            gate.set()
            images_sets = await asyncio.gather(*active)
            for images in images_sets:
                for image in images:
                    image.close()
            await renderer.close()

    async def test_context_closes_when_new_page_fails_without_page_close(self) -> None:
        factory = FakeFactory(
            new_page_error=RuntimeError("new page failed"),
            context_close_error=RuntimeError("context close failed"),
        )
        renderer = template.BrowserRenderer()
        with (
            factory.patch_import(),
            self.assertRaisesRegex(RuntimeError, "new page failed"),
        ):
            await renderer.render({}, [{}])
        self.assertEqual(len(factory.contexts), 1)
        self.assertEqual(factory.contexts[0].close_calls, 1)
        self.assertEqual(factory.pages, [])
        self.assertTrue(renderer._stopped)
        with self.assertRaises(template.RendererStoppedError):
            await renderer.render({}, [{}])
        await renderer.close()
        self.assertEqual(factory.browsers[0].close_calls, 1)
        self.assertEqual(factory.playwrights[0].stop_calls, 1)

    async def test_launch_failure_stops_created_playwright_instance(self) -> None:
        factory = FakeFactory(launch_error=RuntimeError("launch failed"))
        renderer = template.BrowserRenderer()
        with (
            factory.patch_import(),
            self.assertRaisesRegex(RuntimeError, "launch failed"),
        ):
            await renderer.render({}, [{}])
        self.assertEqual(factory.launch_calls, 1)
        self.assertEqual(len(factory.playwrights), 1)
        self.assertEqual(factory.playwrights[0].stop_calls, 1)
        await renderer.close()

    async def test_disconnected_browser_is_replaced_before_next_request(self) -> None:
        factory = FakeFactory()
        renderer = template.BrowserRenderer()
        with factory.patch_import():
            first = await renderer.render({}, [{}])
            first[0].close()
            factory.browsers[0].connected = False
            second = await renderer.render({}, [{}])
            second[0].close()
            self.assertEqual(factory.launch_calls, 2)
            self.assertEqual(factory.browsers[0].close_calls, 1)
            self.assertEqual(factory.playwrights[0].stop_calls, 1)
            self.assertEqual(len(factory.pages), 2)
            await renderer.close()
        self.assertEqual(factory.browsers[1].close_calls, 1)
        self.assertEqual(factory.playwrights[1].stop_calls, 1)

    async def test_disconnected_cleanup_failure_stops_replacement_and_retains_handles(
        self,
    ) -> None:
        factory = FakeFactory(
            browser_close_error=RuntimeError("disconnected browser close failed"),
            stop_error=RuntimeError("disconnected Playwright stop failed"),
        )
        renderer = template.BrowserRenderer()
        with factory.patch_import():
            images = await renderer.render({}, [{}])
            images[0].close()
            browser = factory.browsers[0]
            playwright = factory.playwrights[0]
            browser.connected = False
            with self.assertRaisesRegex(
                RuntimeError, "disconnected browser close failed"
            ):
                await renderer.render({}, [{}])

            self.assertEqual(factory.launch_calls, 1)
            self.assertTrue(renderer._stopped)
            self.assertIs(renderer._browser, browser)
            self.assertIs(renderer._playwright, playwright)
            with self.assertRaises(template.RendererStoppedError):
                await renderer.render({}, [{}])

            factory.browser_close_error = None
            factory.stop_error = None
            await renderer.close()
            self.assertEqual(browser.close_calls, 2)
            self.assertEqual(playwright.stop_calls, 2)
            self.assertIsNone(renderer._browser)
            self.assertIsNone(renderer._playwright)

    async def test_navigation_status_identity_and_loopback_validation(self) -> None:
        factory = FakeFactory(status=503)
        renderer = template.BrowserRenderer()
        with (
            factory.patch_import(),
            self.assertRaisesRegex(RuntimeError, "expected HTTP 200"),
        ):
            await renderer.render({}, [{}])
        self.assertEqual(len(factory.pages[0].navigations), 1)
        await renderer.close()

        factory = FakeFactory()
        renderer = template.BrowserRenderer()
        with (
            factory.patch_import(),
            patch.dict(
                os.environ,
                {
                    "CATLABEL_HEADLESS_URL": "http://example.com/index.html?mode=headless"
                },
            ),
            self.assertRaisesRegex(RuntimeError, "must use http://127.0.0.1"),
        ):
            await renderer.render({}, [{}])
        self.assertEqual(factory.launch_calls, 0)
        self.assertEqual(factory.pages, [])
        await renderer.close()

    async def test_identity_wait_accepts_delayed_marker_and_rejects_wrong_page(
        self,
    ) -> None:
        identity_gate = asyncio.Event()
        factory = FakeFactory(identity=False, identity_gate=identity_gate)
        renderer = template.BrowserRenderer()
        with factory.patch_import():
            request = asyncio.create_task(renderer.render({}, [{}]))
            await asyncio.wait_for(factory.identity_wait_started.wait(), 1)
            self.assertFalse(factory.payload_injected)
            self.assertEqual(factory.identity_wait_timeout_ms, 5000)
            factory.identity = True
            identity_gate.set()
            images = await request
            self.assertTrue(factory.payload_injected)
            images[0].close()
            await renderer.close()

        factory = FakeFactory(identity=False)
        renderer = template.BrowserRenderer()
        with (
            factory.patch_import(),
            self.assertRaisesRegex(TimeoutError, "identity marker did not appear"),
        ):
            await renderer.render({}, [{}])
        self.assertFalse(factory.payload_injected)
        await renderer.close()

    def test_explicit_loopback_url_variants_are_accepted(self) -> None:
        for url in (
            "http://127.0.0.1:8765/index.html?mode=headless",
            "http://localhost:8765/index.html?mode=headless",
            "http://[::1]:8765/index.html?mode=headless",
        ):
            with (
                self.subTest(url=url),
                patch.dict(os.environ, {"CATLABEL_HEADLESS_URL": url}),
            ):
                self.assertEqual(template._headless_url(), url)

    async def test_output_count_and_aggregate_cap_are_checked_before_transfer(
        self,
    ) -> None:
        factory = FakeFactory(outputs=[])
        renderer = template.BrowserRenderer()
        with factory.patch_import(), self.assertRaises(ResourceLimitError):
            await renderer.render({}, [{}])
        self.assertEqual(factory.transferred_outputs, 0)
        await renderer.close()

        factory = FakeFactory(
            encoded_chars_override=template.MAX_ENCODED_OUTPUT_CHARS + 1
        )
        renderer = template.BrowserRenderer()
        with (
            factory.patch_import(),
            self.assertRaisesRegex(ResourceLimitError, "encoded size"),
        ):
            await renderer.render({}, [{}])
        self.assertEqual(factory.transferred_outputs, 0)
        await renderer.close()

    async def test_request_cancellation_closes_context_without_cancelling_playwright_call(
        self,
    ) -> None:
        factory = FakeFactory(wait_gate=asyncio.Event())
        renderer = template.BrowserRenderer()
        with factory.patch_import():
            request = asyncio.create_task(renderer.render({}, [{}]))
            page = await asyncio.wait_for(factory.started.get(), 1)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
            self.assertFalse(page.wait_cancelled)
            self.assertEqual(factory.contexts[0].close_calls, 1)
            self.assertEqual(renderer._admitted, 0)
            await renderer.close()

    async def test_request_cleanup_error_stops_admission_but_preserves_cancellation(
        self,
    ) -> None:
        factory = FakeFactory(
            wait_gate=asyncio.Event(),
            context_close_error=RuntimeError("context close failed"),
        )
        renderer = template.BrowserRenderer()
        with factory.patch_import():
            request = asyncio.create_task(renderer.render({}, [{}]))
            await asyncio.wait_for(factory.started.get(), 1)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
            self.assertTrue(renderer._stopped)
            with self.assertRaises(template.RendererStoppedError):
                await renderer.render({}, [{}])
            await renderer.close()
        self.assertEqual(factory.browsers[0].close_calls, 1)
        self.assertEqual(factory.playwrights[0].stop_calls, 1)

    async def test_request_cleanup_timeout_is_bounded_and_preserves_original_error(
        self,
    ) -> None:
        for use_timeout in (False, True):
            with self.subTest(use_timeout=use_timeout):
                close_gate = asyncio.Event()
                factory = FakeFactory(
                    wait_gate=asyncio.Event(), context_close_gate=close_gate
                )
                renderer = template.BrowserRenderer(request_cleanup_budget_seconds=0.12)
                constants = (
                    patch.object(template, "RENDER_BASE_TIMEOUT_SECONDS", 0.02),
                    patch.object(template, "RENDER_PER_JOB_TIMEOUT_SECONDS", 0.0),
                )
                with factory.patch_import(), constants[0], constants[1]:
                    request = asyncio.create_task(renderer.render({}, [{}]))
                    await asyncio.wait_for(factory.started.get(), 1)
                    owned_job = next(iter(renderer._jobs)).task
                    self.assertIsNotNone(owned_job)
                    if not use_timeout:
                        request.cancel()
                    start = asyncio.get_running_loop().time()
                    expected_error = (
                        TimeoutError if use_timeout else asyncio.CancelledError
                    )
                    with self.assertRaises(expected_error):
                        await asyncio.wait_for(request, 1)
                    elapsed = asyncio.get_running_loop().time() - start
                    self.assertLess(elapsed, 0.3)
                    self.assertTrue(renderer._stopped)
                    self.assertEqual(renderer._admitted, 1)
                    self.assertGreaterEqual(len(renderer._lingering_tasks), 1)
                    with self.assertRaises(template.RendererStoppedError):
                        await renderer.render({}, [{}])

                    close_gate.set()
                    assert owned_job is not None
                    await asyncio.gather(owned_job, return_exceptions=True)
                    await asyncio.sleep(0)
                    self.assertEqual(renderer._admitted, 0)
                    self.assertEqual(len(renderer._lingering_tasks), 0)
                    await renderer.close()

    async def test_active_slots_remain_held_through_image_decoding(self) -> None:
        factory = FakeFactory()
        renderer = template.BrowserRenderer()
        decode_started = threading.Event()
        decode_gate = threading.Event()
        decode_lock = threading.Lock()
        decode_count = 0
        original_decode = template.decode_image_payloads

        def blocking_decode(
            payloads: object, *, rotate: bool = False
        ) -> list[Image.Image]:
            nonlocal decode_count
            with decode_lock:
                decode_count += 1
                if decode_count == 2:
                    decode_started.set()
            if not decode_gate.wait(timeout=2):
                raise TimeoutError("test decoder gate timed out")
            return original_decode(payloads, rotate=rotate)  # type: ignore[arg-type]

        with (
            factory.patch_import(),
            patch.object(
                template, "decode_image_payloads", side_effect=blocking_decode
            ),
        ):
            first_jobs = [
                asyncio.create_task(renderer.render({}, [{}])) for _ in range(2)
            ]
            self.assertTrue(await asyncio.to_thread(decode_started.wait, 1))
            third_job = asyncio.create_task(renderer.render({}, [{}]))
            try:
                await asyncio.sleep(0.05)
                self.assertEqual(len(factory.contexts), 2)
            finally:
                decode_gate.set()
            image_sets = await asyncio.gather(*first_jobs, third_job)
            for images in image_sets:
                for image in images:
                    image.close()
            await renderer.close()

    async def test_shutdown_closes_owned_context_browser_and_playwright(self) -> None:
        factory = FakeFactory(wait_gate=asyncio.Event())
        renderer = template.BrowserRenderer()
        with factory.patch_import():
            request = asyncio.create_task(renderer.render({}, [{}]))
            page = await asyncio.wait_for(factory.started.get(), 1)
            await renderer.close()
            with self.assertRaises(template._RenderAborted):
                await request
            self.assertFalse(page.wait_cancelled)
        self.assertEqual(factory.contexts[0].close_calls, 1)
        self.assertEqual(factory.browsers[0].close_calls, 1)
        self.assertEqual(factory.playwrights[0].stop_calls, 1)
        with self.assertRaises(template.RendererStoppedError):
            await renderer.render({}, [{}])

    async def test_shutdown_attempts_every_cleanup_and_preserves_first_error(
        self,
    ) -> None:
        factory = FakeFactory(
            wait_gate=asyncio.Event(),
            context_close_error=RuntimeError("context cleanup failed"),
            browser_close_error=RuntimeError("browser cleanup failed"),
            stop_error=RuntimeError("playwright cleanup failed"),
        )
        renderer = template.BrowserRenderer()
        with factory.patch_import():
            request = asyncio.create_task(renderer.render({}, [{}]))
            await asyncio.wait_for(factory.started.get(), 1)
            with self.assertRaisesRegex(RuntimeError, "context cleanup failed"):
                await renderer.close()
            with self.assertRaises(template._RenderAborted):
                await request
        self.assertEqual(factory.contexts[0].close_calls, 1)
        self.assertEqual(factory.browsers[0].close_calls, 1)
        self.assertEqual(factory.playwrights[0].stop_calls, 1)

    async def test_shutdown_timeout_keeps_tasks_owned_until_late_cleanup_finishes(
        self,
    ) -> None:
        close_gate = asyncio.Event()
        factory = FakeFactory(wait_gate=asyncio.Event(), context_close_gate=close_gate)
        renderer = template.BrowserRenderer(shutdown_budget_seconds=0.12)
        with factory.patch_import():
            request = asyncio.create_task(renderer.render({}, [{}]))
            await asyncio.wait_for(factory.started.get(), 1)
            with self.assertRaisesRegex(
                RuntimeError, "context cleanup.*owned render jobs"
            ):
                await renderer.close()
            self.assertGreater(len(renderer._lingering_tasks), 0)
            close_gate.set()
            with self.assertRaises(template._RenderAborted):
                await request
            await asyncio.sleep(0)
            self.assertEqual(len(renderer._lingering_tasks), 0)
        self.assertEqual(factory.browsers[0].close_calls, 1)
        self.assertEqual(factory.playwrights[0].stop_calls, 1)

    async def test_browser_started_after_shutdown_is_closed_late(self) -> None:
        launch_gate = asyncio.Event()
        factory = FakeFactory(launch_gate=launch_gate)
        renderer = template.BrowserRenderer(shutdown_budget_seconds=0.12)
        with factory.patch_import():
            request = asyncio.create_task(renderer.render({}, [{}]))
            await asyncio.wait_for(factory.launch_started.wait(), 1)
            with self.assertRaisesRegex(RuntimeError, "owned render jobs"):
                await renderer.close()
            self.assertEqual(factory.browsers, [])
            launch_gate.set()
            with self.assertRaises(template._RenderAborted):
                await request
        self.assertEqual(factory.browsers[0].close_calls, 1)
        self.assertEqual(factory.playwrights[0].stop_calls, 1)
        self.assertIsNone(renderer._browser)

    async def test_sync_wrapper_rejects_running_loop_with_actionable_message(
        self,
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "await render_via_browser_async"):
            template.render_via_browser({}, [{}])

    async def test_module_renderer_singleton_resets_only_after_successful_close(
        self,
    ) -> None:
        renderer = template.BrowserRenderer()
        with patch.object(template, "_browser_renderer", renderer):
            await template.close_browser_renderer()
            self.assertIsNone(template._browser_renderer)
            replacement = template.get_browser_renderer()
            self.assertIsNot(replacement, renderer)
            await template.close_browser_renderer()

        failed_renderer = template.BrowserRenderer()
        with patch.object(template, "_browser_renderer", failed_renderer):
            with (
                patch.object(
                    failed_renderer,
                    "close",
                    new=AsyncMock(side_effect=RuntimeError("close failed")),
                ),
                self.assertRaisesRegex(RuntimeError, "close failed"),
            ):
                await template.close_browser_renderer()
            self.assertIs(template._browser_renderer, failed_renderer)


class SynchronousRendererCompatibilityTests(unittest.TestCase):
    def test_sync_wrapper_uses_an_isolated_renderer_and_closes_it(self) -> None:
        factory = FakeFactory()
        with factory.patch_import():
            images = template.render_via_browser({}, [{}])
        try:
            self.assertEqual(len(images), 1)
            self.assertEqual(factory.browsers[0].close_calls, 1)
            self.assertEqual(factory.playwrights[0].stop_calls, 1)
            self.assertEqual(factory.contexts[0].close_calls, 1)
        finally:
            for image in images:
                image.close()


if __name__ == "__main__":
    unittest.main()
