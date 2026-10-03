from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeControlRange:
    """Inclusive runtime range and default for one printer control."""

    low: int
    default: int
    high: int

    def __post_init__(self) -> None:
        values = (self.low, self.default, self.high)
        if any(type(value) is not int for value in values):
            raise ValueError("Runtime control range values must be strict integers")
        if any(not 0 <= value <= 255 for value in values):
            raise ValueError("Runtime control range values must be in 0..255")
        if not self.low <= self.default <= self.high:
            raise ValueError(
                "Runtime control range must satisfy low <= default <= high"
            )


@dataclass(frozen=True)
class RuntimePrintControls:
    """Runtime-resolved ranges for print settings."""

    density: RuntimeControlRange
    speed: RuntimeControlRange | None = None


@dataclass(frozen=True)
class RuntimePrintCapabilities:
    """Capabilities learned from a connected printer at runtime."""

    supports_gray: bool | None = None
    gray_level_override: int | None = None
    print_controls: RuntimePrintControls | None = None
