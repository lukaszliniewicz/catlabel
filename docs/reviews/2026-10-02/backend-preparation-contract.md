# Printer preparation ownership contract

Status: next implementation contract; these are acceptance requirements, not a
claim that the routes already implement them. Reviewed against backend sources
at f2a4fe9 by the parent and a bounded GPT-6.1 Sol/high specialist. Runtime model
telemetry was unavailable. No hardware call or executable review was performed.

Move process-local printer admission before expensive rendering/decoding, while
preserving existing borrowed-image executor callers and exact route response
contracts. An owned preparation path must dispose every produced image after
validation/connection/transmission cleanup. A cancelled preparation never reaches
physical connection. Whole-job accumulation and encoded spooling are later work;
concurrency rejection alone does not make memory independent of batch size.

Use a thread-safe ownership box for synchronous decoding. Worker results must be
published to this owner rather than entrusted to the asyncio result. Normal
caller cancellation drains a shielded worker wrapper, including repeated caller
cancellation, then closes output. An independently cancelled wrapper or event-loop
shutdown may finish before its worker thread: mark the owner abandoned so late
results are closed. Never repeatedly await an already-cancelled task or interpret
its done flag as proof that the thread exited. The current exact helper packet
covers output ownership; route/device admission integration remains parent-owned.

BrowserRenderer cancellation can return before quarantined work physically exits.
It retains its own bounded renderer admission/slot and late cleanup; stopped
admission follows timed-out/failed cleanup. A cancelled render await cannot return
its late image list to the route. Printer admission therefore spans the awaited
preparation contract, with lingering browser work separately owned by the renderer.
The current renderer also uses a synchronous decoder and needs the owned-result
helper at that boundary.

Disconnect currently awaits the driver directly. Repeated cancellation during
that await can escape its Exception handler and release printer admission before
normal cleanup finishes. The next route packet must shield/drain ordinary caller
cancellation through disconnect and explicitly distinguish independent task
cancellation/shutdown from a verified physical disconnect. No automatic retry.

Compatibility gates: renderer failures retain status503 for busy/stopped,504 for
timeout,422 for limits and500 otherwise, with the existing render detail shape.
Image decoder failures retain422 with the original limit message and400 with
"Invalid image payload supplied." Empty image requests retain the exact empty
receipt and bypass preparation. Direct success additionally includes mac_address;
batch/images success does not. Existing borrowed executor tests use object()
inputs: the executor must not start closing caller-owned inputs.

Evidence: catlabel/api/routes_print.py:269,458,479,504,548;
catlabel/rendering/template.py:214,223,360,418,597,608;
tests/test_browser_renderer.py:582;
tests/test_print_limits.py:72,98,135;
tests/test_print_admission.py:142,282,382.

Primary cancellation references checked by the specialist:
[asyncio shield](https://docs.python.org/3.11/library/asyncio-task.html#shielding-from-cancellation),
[executor cancellation](https://docs.python.org/3.11/library/concurrent.futures.html#concurrent.futures.Future.cancel),
[CPython runner shutdown](https://github.com/python/cpython/blob/3.11/Lib/asyncio/runners.py#L180-L187).
