from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Protocol, Sequence

from projectos.errors import ValidationError


_SECRET = re.compile(r"(?i)(password|access[_-]?token)\s*[:=]\s*[^\s]+")
_OUTPUT_LIMIT = 2048


def _bounded(value: str | bytes | None) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    text = _SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return text[:_OUTPUT_LIMIT]


@dataclass(frozen=True)
class NativeProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class NativeProcessExecutor(Protocol):
    def run(self, argv: tuple[str, ...], timeout_seconds: int) -> NativeProcessResult: ...


class SubprocessNativeExecutor:
    def run(self, argv: tuple[str, ...], timeout_seconds: int) -> NativeProcessResult:
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise ValidationError("native process arguments are invalid")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
            raise ValidationError("native process timeout is invalid")
        try:
            completed = subprocess.run(
                list(argv),
                shell=False,
                env=None,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return NativeProcessResult(-1, _bounded(exc.stdout), _bounded(exc.stderr), True)
        return NativeProcessResult(
            int(completed.returncode), _bounded(completed.stdout), _bounded(completed.stderr), False
        )


class RecordingProcessExecutor:
    def __init__(self, responses: Sequence[NativeProcessResult] = ()) -> None:
        self._responses = list(responses)
        self.history: list[tuple[str, ...]] = []
        self.timeouts: list[int] = []

    def run(self, argv: tuple[str, ...], timeout_seconds: int) -> NativeProcessResult:
        self.history.append(tuple(argv))
        self.timeouts.append(timeout_seconds)
        if not self._responses:
            raise AssertionError(f"no recorded native response for {argv!r}")
        return self._responses.pop(0)
