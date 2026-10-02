from __future__ import annotations

from .. import reporting
from ..protocol import ProtocolJob, ProtocolStep, ProtocolStepOperation
from .runtime.base import PreparedRuntimeContext
from .runtime.factory import runtime_controller_for_device
from .runtime.session import RuntimeConnectionSession
from .step_execution import bytes_preview, execute_protocol_step, reply_matches_for

_DEFAULT_RUNTIME_CONTEXT = PreparedRuntimeContext()


async def send_prepared_job(
    device,
    connection,
    job: ProtocolJob,
    *,
    timeout: float = 1.0,
    reporter: reporting.Reporter = reporting.DUMMY_REPORTER,
    runtime_context: PreparedRuntimeContext = _DEFAULT_RUNTIME_CONTEXT,
) -> None:
    """Send one job without discarding its ordered protocol operations."""

    session = RuntimeConnectionSession(connection, reporter=reporter)
    controller = runtime_context.runtime_controller
    if controller is None and job.wait_for_completion:
        controller = runtime_controller_for_device(device)
    if controller is not None:
        await session.attach_runtime_controller(controller, timeout=timeout)

    sent = False
    if job.steps:
        if controller is not None:
            sent = await controller.send_protocol_steps(
                session, job.steps, timeout=timeout
            )
        if not sent:
            await _send_protocol_steps(session, job.steps, timeout=timeout)
            sent = True
    elif controller is not None:
        # Compatibility for the currently ported V5 runtimes, whose builders
        # still expose a stream while their runtime performs split transfers.
        sent = await controller.send_payload(session, job.payload, timeout=timeout)

    if not sent:
        await connection.send(job)

    if controller is not None and job.wait_for_completion:
        await controller.wait_for_completion(session, timeout=timeout)


async def _send_protocol_steps(
    session: RuntimeConnectionSession,
    steps: tuple[ProtocolStep, ...],
    *,
    timeout: float,
) -> None:
    if any(step.operation is ProtocolStepOperation.QUERY for step in steps) and not (
        session.can_query_control_packet()
        or session.can_send_control_packet_wait_notification()
    ):
        raise RuntimeError("This printer job requires request/reply protocol support")
    if (
        any(step.operation is ProtocolStepOperation.WAIT for step in steps)
        and not session.can_wait_for_notification()
    ):
        raise RuntimeError("This printer job requires BLE notification support")

    for step in steps:
        reply = await execute_protocol_step(session, step, timeout=timeout)
        if step.operation is ProtocolStepOperation.SEND:
            continue
        if not reply_matches_for(step, reply):
            raise RuntimeError(
                f"Protocol step {step.label!r} received an unexpected reply: "
                f"{bytes_preview(reply)}"
            )
