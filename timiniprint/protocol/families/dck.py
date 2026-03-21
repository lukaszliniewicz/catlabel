from __future__ import annotations

from .base import PrintJobRequest, ProtocolBehavior


def build_job(_request: PrintJobRequest) -> bytes:
    raise NotImplementedError("Printing is not implemented for the DCK protocol family yet")


BEHAVIOR = ProtocolBehavior(job_builder=build_job)
