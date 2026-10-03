from __future__ import annotations

import asyncio
import logging
import math
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from ..core.resource_limits import ResourceLimitError, validate_render_budget
from .browser_stream import MAX_ENCODED_OUTPUT_CHARS, collect_streamed_images
from .image_payload import decode_image_payloads
from .owned_decode import decode_owned

logger = logging.getLogger(__name__)

MAX_ADMITTED_RENDER_JOBS = 4
MAX_ACTIVE_RENDER_JOBS = 2
MAX_RENDER_DEADLINE_SECONDS = 120.0
RENDER_BASE_TIMEOUT_SECONDS = 30.0
RENDER_PER_JOB_TIMEOUT_SECONDS = 0.25


class RenderBusyError(RuntimeError):
    """Raised when the browser renderer has no admission capacity."""


class RendererStoppedError(RuntimeError):
    """Raised when the browser renderer has begun shutting down."""


class _RenderAborted(Exception):
    """Internal signal used after a context is closed to stop an owned job."""


@dataclass(eq=False)
class _RenderJob:
    expected_jobs: int
    deadline: float
    timeout_seconds: float
    url: str
    abort_event: asyncio.Event
    task: asyncio.Task[list[Image.Image]] | None = None
    context: Any = None
    context_close_task: asyncio.Task[None] | None = None
    slot_acquired: bool = False
    aborted: bool = False


def _headless_url() -> str:
    configured = os.environ.get("CATLABEL_HEADLESS_URL")
    if configured is None:
        port_text = os.environ.get("CATLABEL_PORT", "8000")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise RuntimeError("CATLABEL_PORT must be a valid TCP port.") from exc
        if not 1 <= port <= 65535:
            raise RuntimeError("CATLABEL_PORT must be a valid TCP port.")
        configured = f"http://127.0.0.1:{port}/index.html?mode=headless"

    try:
        parsed = urlsplit(configured)
        hostname = parsed.hostname
        port = parsed.port
        query = parse_qs(parsed.query, keep_blank_values=True)
    except ValueError as exc:
        raise RuntimeError(
            "CATLABEL_HEADLESS_URL is not a valid loopback URL."
        ) from exc

    if (
        parsed.scheme != "http"
        or hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/index.html"
        or query.get("mode") != ["headless"]
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise RuntimeError(
            "CATLABEL_HEADLESS_URL must use http://127.0.0.1, localhost, or [::1], "
            "with /index.html?mode=headless."
        )
    return configured


def _decode_browser_image(data_url_or_b64: str) -> Image.Image:
    return decode_image_payloads([data_url_or_b64])[0]


_OUTPUT_METADATA_SCRIPT = """() => {
  const source = window.__RENDERED_IMAGES__ || [];
  if (!Array.isArray(source)) {
    return { isArray: false, count: 0, encodedChars: 0, invalidCount: 0 };
  }
  const images = source.slice();
  window.__CATLABEL_RENDERED_IMAGE_SNAPSHOT__ = images;
  let encodedChars = 0;
  let invalidCount = 0;
  for (const image of images) {
    if (typeof image !== "string") {
      invalidCount += 1;
    } else {
      encodedChars += image.length;
    }
  }
  return { isArray: true, count: images.length, encodedChars, invalidCount };
}"""


class BrowserRenderer:
    """Owns one async Playwright browser on the first calling event loop."""

    def __init__(
        self,
        *,
        shutdown_budget_seconds: float = 12.0,
        request_cleanup_budget_seconds: float = 8.0,
    ) -> None:
        for name, value in (
            ("shutdown_budget_seconds", shutdown_budget_seconds),
            ("request_cleanup_budget_seconds", request_cleanup_budget_seconds),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a finite positive number.")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._startup_lock: asyncio.Lock | None = None
        self._slots: asyncio.Semaphore | None = None
        self._playwright: Any = None
        self._browser: Any = None
        self._stopped = False
        self._admitted = 0
        self._jobs: set[_RenderJob] = set()
        self._close_task: asyncio.Task[None] | None = None
        self._lingering_tasks: set[asyncio.Task[Any]] = set()
        self._request_cleanup_stage_timeouts = (
            request_cleanup_budget_seconds / 2,
            request_cleanup_budget_seconds / 2,
        )
        self._shutdown_stage_timeouts = (
            shutdown_budget_seconds / 3,
            shutdown_budget_seconds / 3,
            shutdown_budget_seconds / 6,
            shutdown_budget_seconds / 6,
        )

    def _bind_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
            self._startup_lock = asyncio.Lock()
            self._slots = asyncio.Semaphore(MAX_ACTIVE_RENDER_JOBS)
        elif self._loop is not loop:
            raise RuntimeError(
                "BrowserRenderer must be used from its owning event loop."
            )
        return loop

    async def render(
        self,
        canvas_state: dict[str, Any],
        variables_collection: list[dict[str, str]],
        copies: int = 1,
    ) -> list[Image.Image]:
        loop = self._bind_loop()
        expected_jobs, _ = validate_render_budget(
            canvas_state or {},
            records=len(variables_collection or [{}]),
            copies=copies,
        )
        if self._stopped:
            raise RendererStoppedError("The browser renderer is shutting down.")
        url = _headless_url()
        if self._admitted >= MAX_ADMITTED_RENDER_JOBS:
            raise RenderBusyError("The browser renderer is busy. Retry shortly.")

        timeout_seconds = min(
            MAX_RENDER_DEADLINE_SECONDS,
            RENDER_BASE_TIMEOUT_SECONDS
            + RENDER_PER_JOB_TIMEOUT_SECONDS * expected_jobs,
        )
        job = _RenderJob(
            expected_jobs=expected_jobs,
            deadline=loop.time() + timeout_seconds,
            timeout_seconds=timeout_seconds,
            url=url,
            abort_event=asyncio.Event(),
        )
        self._admitted += 1
        self._jobs.add(job)
        try:
            job.task = loop.create_task(
                self._render_job(
                    job,
                    canvas_state or {},
                    variables_collection or [{}],
                    copies,
                )
            )
        except BaseException:
            self._jobs.discard(job)
            self._admitted -= 1
            raise

        try:
            remaining = max(0.0, job.deadline - loop.time())
            return await asyncio.wait_for(asyncio.shield(job.task), timeout=remaining)
        except TimeoutError:
            try:
                await asyncio.shield(self._abort_and_wait(job))
            except BaseException:
                logger.exception("Browser render cleanup failed after request timeout")
            raise
        except asyncio.CancelledError:
            try:
                await asyncio.shield(self._abort_and_wait(job))
            except BaseException:
                logger.exception(
                    "Browser render cleanup failed after request cancellation"
                )
            raise

    async def _wait_for_slot(self, job: _RenderJob) -> None:
        assert self._slots is not None
        if job.aborted or self._stopped:
            raise _RenderAborted

        acquire_task = asyncio.create_task(self._slots.acquire())
        abort_task = asyncio.create_task(job.abort_event.wait())
        try:
            remaining = max(0.0, job.deadline - asyncio.get_running_loop().time())
            done, _ = await asyncio.wait(
                (acquire_task, abort_task),
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if acquire_task in done:
                acquire_task.result()
                job.slot_acquired = True
                if job.aborted or self._stopped:
                    raise _RenderAborted
                return
            if abort_task in done or job.aborted or self._stopped:
                raise _RenderAborted
            raise TimeoutError("Headless rendering expired while waiting for capacity.")
        finally:
            for waiter in (acquire_task, abort_task):
                if not waiter.done():
                    waiter.cancel()
            await asyncio.gather(acquire_task, abort_task, return_exceptions=True)

    async def _ensure_browser(self) -> Any:
        assert self._startup_lock is not None
        async with self._startup_lock:
            if self._stopped:
                raise _RenderAborted
            if self._browser is not None:
                try:
                    if self._browser.is_connected():
                        return self._browser
                except Exception:
                    pass
                await self._reset_disconnected_browser()

            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "Playwright is not installed. Headless API printing is disabled. "
                    "To enable it, install the headless extra and run: "
                    "playwright install chromium"
                ) from exc

            playwright_context = await async_playwright().start()
            if self._stopped:
                try:
                    await playwright_context.stop()
                except BaseException:
                    logger.exception(
                        "Stopping Playwright after shutdown raced browser startup failed"
                    )
                raise _RenderAborted
            try:
                browser = await playwright_context.chromium.launch(headless=True)
            except BaseException:
                try:
                    await playwright_context.stop()
                except BaseException:
                    logger.exception(
                        "Playwright stop failed after browser launch failure"
                    )
                raise
            if self._stopped:
                try:
                    await browser.close()
                except BaseException:
                    logger.exception(
                        "Closing a late browser after renderer shutdown failed"
                    )
                try:
                    await playwright_context.stop()
                except BaseException:
                    logger.exception(
                        "Stopping late Playwright after renderer shutdown failed"
                    )
                raise _RenderAborted
            self._playwright = playwright_context
            self._browser = browser
            return browser

    async def _reset_disconnected_browser(self) -> None:
        browser, playwright_context = self._browser, self._playwright
        first_error: tuple[BaseException, Any] | None = None
        if browser is not None:
            try:
                await browser.close()
            except BaseException as exc:
                logger.exception("Closing the disconnected browser failed")
                first_error = (exc, exc.__traceback__)
            else:
                if self._browser is browser:
                    self._browser = None
        if playwright_context is not None:
            try:
                await playwright_context.stop()
            except BaseException as exc:
                logger.exception("Stopping Playwright after disconnect failed")
                if first_error is None:
                    first_error = (exc, exc.__traceback__)
            else:
                if self._playwright is playwright_context:
                    self._playwright = None
        if first_error is not None:
            self._stopped = True
            error, traceback = first_error
            raise error.with_traceback(traceback)

    def _start_context_close(self, job: _RenderJob) -> asyncio.Task[None] | None:
        if job.context is None:
            return None
        if job.context_close_task is None:
            job.context_close_task = asyncio.create_task(job.context.close())
        return job.context_close_task

    async def _close_context(self, job: _RenderJob) -> None:
        close_task = self._start_context_close(job)
        if close_task is None:
            return
        await asyncio.shield(close_task)

    async def _abort_and_wait(self, job: _RenderJob) -> None:
        job.aborted = True
        job.abort_event.set()
        timed_out_stages: list[str] = []
        cleanup_errors: list[tuple[str, BaseException]] = []
        job_errors: list[BaseException] = []
        context_close_task = self._start_context_close(job)
        if context_close_task is not None:
            _, pending = await asyncio.wait(
                (context_close_task,),
                timeout=self._request_cleanup_stage_timeouts[0],
            )
            if pending:
                timed_out_stages.append("context cleanup")
                self._retain_shutdown_task(context_close_task, close_images=False)
            else:
                try:
                    context_close_task.result()
                except _RenderAborted:
                    pass
                except BaseException as exc:
                    cleanup_errors.append(("context cleanup", exc))

        if job.task is not None:
            _, pending = await asyncio.wait(
                (job.task,), timeout=self._request_cleanup_stage_timeouts[1]
            )
            if pending:
                timed_out_stages.append("owned render job")
                self._retain_shutdown_task(job.task, close_images=True)
            else:
                try:
                    result = job.task.result()
                except _RenderAborted:
                    pass
                except BaseException as exc:
                    job_errors.append(exc)
                else:
                    if isinstance(result, list):
                        for image in result:
                            try:
                                image.close()
                            except Exception as exc:
                                cleanup_errors.append(("render image cleanup", exc))

        for stage_name, error in cleanup_errors:
            logger.error(
                "Browser render %s failed during request cleanup: %s",
                stage_name,
                error,
                exc_info=(type(error), error, error.__traceback__),
            )
        for error in job_errors:
            logger.error(
                "Owned browser render job failed while request cleanup completed: %s",
                error,
                exc_info=(type(error), error, error.__traceback__),
            )
        if timed_out_stages or cleanup_errors:
            self._stopped = True
            if timed_out_stages:
                logger.error(
                    "Browser render cleanup exceeded its %.3fs budget during %s; "
                    "renderer admission is stopped and timed-out tasks remain owned.",
                    sum(self._request_cleanup_stage_timeouts),
                    ", ".join(timed_out_stages),
                )
            else:
                logger.error(
                    "Browser render cleanup failed; renderer admission is stopped."
                )

    async def _render_job(
        self,
        job: _RenderJob,
        canvas_state: dict[str, Any],
        variables_collection: list[dict[str, str]],
        copies: int,
    ) -> list[Image.Image]:
        primary_error: tuple[BaseException, Any] | None = None
        image_payloads: object = None
        images: list[Image.Image] | None = None
        stream_output = False
        transfer_success = False

        def check_active() -> None:
            if job.aborted or self._stopped:
                raise _RenderAborted

        try:
            await self._wait_for_slot(job)
            check_active()
            browser = await self._ensure_browser()
            check_active()
            access_token = os.environ.get("CATLABEL_ACCESS_TOKEN", "")
            if canvas_state.get("__secure_network__") is True and access_token:
                context = await browser.new_context(
                    extra_http_headers={"Authorization": "Bearer " + access_token}
                )
            else:
                context = await browser.new_context()
            job.context = context
            check_active()
            if canvas_state.get("__secure_network__") is True:
                allowed = urlsplit(job.url)

                async def filter_network(route: Any) -> None:
                    requested = urlsplit(route.request.url)
                    if requested.scheme in {"data", "blob"} or (
                        requested.scheme == allowed.scheme
                        and requested.hostname == allowed.hostname
                        and requested.port == allowed.port
                    ):
                        await route.continue_()
                    else:
                        await route.abort("blockedbyclient")

                await context.route("**/*", filter_network)
            page = await context.new_page()
            check_active()

            page.set_default_timeout(max(1, int(job.timeout_seconds * 1000)))
            response = await page.goto(job.url, wait_until="domcontentloaded")
            check_active()
            if response is None or response.status != 200:
                status = "no response" if response is None else str(response.status)
                raise RuntimeError(
                    f"Headless frontend returned HTTP {status}; expected HTTP 200."
                )

            identity_timeout_ms = max(
                1,
                int(
                    min(
                        5.0,
                        max(0.0, job.deadline - asyncio.get_running_loop().time()),
                    )
                    * 1000
                ),
            )
            try:
                await page.wait_for_function(
                    "window.__CATLABEL_HEADLESS_VERSION__ === 1",
                    timeout=identity_timeout_ms,
                )
            except Exception as exc:
                if (
                    isinstance(exc, TimeoutError)
                    or type(exc).__name__ == "TimeoutError"
                ):
                    raise TimeoutError(
                        "The CatLabel headless renderer identity marker did not appear "
                        "before the render deadline."
                    ) from exc
                raise
            check_active()

            stream_output = (
                await page.evaluate("window.__CATLABEL_RENDER_STREAM_VERSION__ === 1")
            ) is True
            check_active()

            payload = {
                "canvas_state": canvas_state,
                "variables_collection": variables_collection,
                "copies": copies,
            }
            if stream_output:
                payload["stream_output"] = True
            await page.evaluate(
                "(payload) => { window.__INJECTED_PAYLOAD__ = payload; }", payload
            )
            check_active()

            if stream_output:
                images = await collect_streamed_images(
                    page,
                    expected_jobs=job.expected_jobs,
                    rotate=bool(canvas_state.get("isRotated")),
                    check_active=check_active,
                )
                check_active()
            else:
                await page.wait_for_selector("#render-done", state="attached")
                check_active()
                render_error = await page.evaluate("window.__RENDER_ERROR__ || null")
                check_active()
                if render_error:
                    raise RuntimeError(f"Frontend renderer failed: {render_error}")

                metadata = await page.evaluate(_OUTPUT_METADATA_SCRIPT)
                check_active()
                if (
                    not isinstance(metadata, dict)
                    or metadata.get("isArray") is not True
                ):
                    raise ResourceLimitError(
                        "The renderer returned an invalid image list."
                    )
                count = metadata.get("count")
                if (
                    isinstance(count, bool)
                    or not isinstance(count, int)
                    or count != job.expected_jobs
                ):
                    raise ResourceLimitError(
                        "The renderer returned an unexpected label count."
                    )
                invalid_count = metadata.get("invalidCount")
                if (
                    isinstance(invalid_count, bool)
                    or not isinstance(invalid_count, int)
                    or invalid_count != 0
                ):
                    raise ResourceLimitError(
                        "The renderer returned invalid image payloads."
                    )
                encoded_chars = metadata.get("encodedChars")
                if (
                    isinstance(encoded_chars, bool)
                    or not isinstance(encoded_chars, int)
                    or encoded_chars < 0
                ):
                    raise ResourceLimitError(
                        "The renderer returned invalid image metadata."
                    )
                if encoded_chars > MAX_ENCODED_OUTPUT_CHARS:
                    raise ResourceLimitError(
                        "The renderer output exceeds the encoded size limit."
                    )

                image_payloads = await page.evaluate(
                    "window.__CATLABEL_RENDERED_IMAGE_SNAPSHOT__ || []"
                )
                check_active()
                if (
                    not isinstance(image_payloads, list)
                    or len(image_payloads) != job.expected_jobs
                ):
                    raise ResourceLimitError(
                        "The renderer returned an unexpected label count."
                    )
                if (
                    sum(
                        len(value) for value in image_payloads if isinstance(value, str)
                    )
                    > MAX_ENCODED_OUTPUT_CHARS
                ):
                    raise ResourceLimitError(
                        "The renderer output exceeds the encoded size limit."
                    )
                if any(not isinstance(value, str) for value in image_payloads):
                    raise ResourceLimitError(
                        "The renderer returned invalid image payloads."
                    )
        except BaseException as exc:
            if job.aborted and self._stopped:
                primary_error = (_RenderAborted(), None)
            else:
                primary_error = (exc, exc.__traceback__)

        try:
            try:
                await self._close_context(job)
            except BaseException as exc:
                self._stopped = True
                logger.error(
                    "Closing the render context failed; renderer admission is stopped.",
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                if primary_error is None:
                    primary_error = (exc, exc.__traceback__)
            if primary_error is not None:
                error, traceback = primary_error
                raise error.with_traceback(traceback)
            check_active()
            if not stream_output:
                assert isinstance(image_payloads, list)
                images = await decode_owned(
                    lambda: decode_image_payloads(
                        image_payloads,
                        rotate=bool(canvas_state.get("isRotated")),
                    )
                )
                check_active()
            assert images is not None
            check_active()
            transfer_success = True
            return images
        finally:
            if images is not None and not transfer_success:
                for image in images:
                    try:
                        image.close()
                    except Exception:
                        logger.exception(
                            "Closing an untransferred browser render image failed"
                        )
            if job.slot_acquired:
                assert self._slots is not None
                self._slots.release()
                job.slot_acquired = False
            self._admitted -= 1
            self._jobs.discard(job)

    def _retain_shutdown_task(
        self, task: asyncio.Task[Any], *, close_images: bool
    ) -> None:
        self._lingering_tasks.add(task)

        def consume_late_result(completed: asyncio.Task[Any]) -> None:
            self._lingering_tasks.discard(completed)
            try:
                result = completed.result()
            except _RenderAborted:
                return
            except BaseException:
                logger.exception("A timed-out browser cleanup task failed later")
                return
            if close_images and isinstance(result, list):
                for image in result:
                    if isinstance(image, Image.Image):
                        try:
                            image.close()
                        except Exception:
                            logger.exception(
                                "Closing a late browser render image failed"
                            )

        task.add_done_callback(consume_late_result)

    async def _wait_for_shutdown_stage(
        self,
        tasks: list[asyncio.Task[Any]],
        *,
        timeout: float,
        stage_name: str,
        timed_out_stages: list[str],
        first_error: list[tuple[BaseException, Any] | None],
        close_images: bool = False,
    ) -> None:
        if not tasks:
            return
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in done:
            try:
                result = task.result()
            except _RenderAborted:
                continue
            except BaseException as exc:
                if first_error[0] is None:
                    first_error[0] = (exc, exc.__traceback__)
            else:
                if close_images and isinstance(result, list):
                    for image in result:
                        if isinstance(image, Image.Image):
                            try:
                                image.close()
                            except Exception as exc:
                                if first_error[0] is None:
                                    first_error[0] = (exc, exc.__traceback__)
        if pending:
            timed_out_stages.append(stage_name)
            for task in pending:
                self._retain_shutdown_task(task, close_images=close_images)

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("BrowserRenderer must close on its owning event loop.")
        if self._close_task is None:
            self._stopped = True
            self._close_task = loop.create_task(self._close_resources())
        await asyncio.shield(self._close_task)

    async def _close_resources(self) -> None:
        jobs = tuple(self._jobs)
        first_error: list[tuple[BaseException, Any] | None] = [None]
        timed_out_stages: list[str] = []

        for job in jobs:
            job.aborted = True
            job.abort_event.set()
        context_tasks = [
            task for job in jobs if (task := self._start_context_close(job)) is not None
        ]
        await self._wait_for_shutdown_stage(
            context_tasks,
            timeout=self._shutdown_stage_timeouts[0],
            stage_name="context cleanup",
            timed_out_stages=timed_out_stages,
            first_error=first_error,
        )

        job_tasks = [job.task for job in jobs if job.task is not None]
        await self._wait_for_shutdown_stage(
            job_tasks,
            timeout=self._shutdown_stage_timeouts[1],
            stage_name="owned render jobs",
            timed_out_stages=timed_out_stages,
            first_error=first_error,
            close_images=True,
        )

        browser, playwright_context = self._browser, self._playwright
        self._browser = None
        self._playwright = None
        if browser is not None:
            browser_close_task = asyncio.create_task(browser.close())
            await self._wait_for_shutdown_stage(
                [browser_close_task],
                timeout=self._shutdown_stage_timeouts[2],
                stage_name="browser close",
                timed_out_stages=timed_out_stages,
                first_error=first_error,
            )
        if playwright_context is not None:
            playwright_stop_task = asyncio.create_task(playwright_context.stop())
            await self._wait_for_shutdown_stage(
                [playwright_stop_task],
                timeout=self._shutdown_stage_timeouts[3],
                stage_name="Playwright stop",
                timed_out_stages=timed_out_stages,
                first_error=first_error,
            )

        if timed_out_stages:
            message = (
                "Browser renderer shutdown timed out during "
                f"{', '.join(timed_out_stages)}. A nonresponsive Playwright process "
                "may survive this API cleanup and require process-level termination."
            )
            raise RuntimeError(message) from (
                first_error[0][0] if first_error[0] is not None else None
            )
        if first_error[0] is not None:
            error, traceback = first_error[0]
            raise error.with_traceback(traceback)


_browser_renderer: BrowserRenderer | None = None


def get_browser_renderer() -> BrowserRenderer:
    """Return the lazy module-owned renderer used by API routes."""
    global _browser_renderer
    if _browser_renderer is None:
        _browser_renderer = BrowserRenderer()
    return _browser_renderer


async def render_via_browser_async(
    canvas_state: dict[str, Any],
    variables_collection: list[dict[str, str]],
    copies: int = 1,
) -> list[Image.Image]:
    return await get_browser_renderer().render(
        canvas_state, variables_collection, copies
    )


async def close_browser_renderer() -> None:
    global _browser_renderer
    renderer = _browser_renderer
    if renderer is not None:
        await renderer.close()
        if _browser_renderer is renderer:
            _browser_renderer = None


async def _render_with_isolated_renderer(
    canvas_state: dict[str, Any],
    variables_collection: list[dict[str, str]],
    copies: int,
) -> list[Image.Image]:
    renderer = BrowserRenderer()
    primary_error: tuple[BaseException, Any] | None = None
    images: list[Image.Image] | None = None
    try:
        images = await renderer.render(canvas_state, variables_collection, copies)
    except BaseException as exc:
        primary_error = (exc, exc.__traceback__)
    try:
        await renderer.close()
    except BaseException as exc:
        if primary_error is None:
            primary_error = (exc, exc.__traceback__)
    if primary_error is not None:
        if images:
            for image in images:
                image.close()
        error, traceback = primary_error
        raise error.with_traceback(traceback)
    assert images is not None
    return images


def render_via_browser(
    canvas_state: dict[str, Any],
    variables_collection: list[dict[str, str]],
    copies: int = 1,
) -> list[Image.Image]:
    """Synchronous compatibility wrapper using an isolated renderer per call."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            _render_with_isolated_renderer(canvas_state, variables_collection, copies)
        )
    raise RuntimeError(
        "render_via_browser() cannot run inside an event loop; "
        "await render_via_browser_async() instead."
    )


def render_template(
    template_data: dict, variables: dict, default_font: str = "RobotoCondensed.ttf"
) -> Image.Image:
    """Backwards-compatible wrapper for a single rendered PIL image."""
    images = render_via_browser(template_data or {}, [variables or {}], 1)
    if images:
        return images[0]

    width = max(1, int((template_data or {}).get("width", 384) or 384))
    height = max(1, int((template_data or {}).get("height", 384) or 384))
    return Image.new("RGB", (width, height), "white")
