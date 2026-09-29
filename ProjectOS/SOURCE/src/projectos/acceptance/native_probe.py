from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from projectos.acceptance.probe import ProbeResult
from projectos.acceptance.profile import AcceptanceProfile
from projectos.adoption.scheduler import SchedulerDefinition, SchedulerInspection, SchedulerState
from projectos.errors import ValidationError


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SPOOL_BYTES = 64 * 1024


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class NativeTriggerRunner(Protocol):
    def trigger(self, definition: SchedulerDefinition) -> SchedulerInspection: ...


@dataclass(frozen=True)
class NativeTriggerWindow:
    window_id: str
    run_id: str
    sequence: int
    case_id: str
    receipt_id: str
    release_sha256: str
    definition_sha256: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "definition_sha256": self.definition_sha256,
            "format": "projectos-native-trigger-window-v1",
            "receipt_id": self.receipt_id,
            "release_sha256": self.release_sha256,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "window_id": self.window_id,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> NativeTriggerWindow:
        expected = {
            "case_id", "definition_sha256", "format", "receipt_id", "release_sha256",
            "run_id", "sequence", "window_id",
        }
        if set(value) != expected or value.get("format") != "projectos-native-trigger-window-v1":
            raise ValidationError("native trigger window fields are invalid")
        strings = ("case_id", "receipt_id", "run_id", "window_id")
        if any(
            not isinstance(value.get(field), str)
            or _SAFE_ID.fullmatch(str(value[field])) is None
            for field in strings
        ):
            raise ValidationError("native trigger window identifier is invalid")
        if any(
            not isinstance(value.get(field), str)
            or _SHA256.fullmatch(str(value[field])) is None
            for field in ("release_sha256", "definition_sha256")
        ):
            raise ValidationError("native trigger window hash is invalid")
        sequence = value.get("sequence")
        if type(sequence) is not int or not 1 <= sequence <= 1_000_000:
            raise ValidationError("native trigger window sequence is invalid")
        return cls(
            str(value["window_id"]), str(value["run_id"]), sequence,
            str(value["case_id"]), str(value["receipt_id"]),
            str(value["release_sha256"]), str(value["definition_sha256"]),
        )


class NativeProbeController:
    def __init__(
        self,
        profile: AcceptanceProfile,
        definition: SchedulerDefinition,
        runner: NativeTriggerRunner,
        run_id: str,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if _SAFE_ID.fullmatch(run_id) is None:
            raise ValidationError("native probe run id is invalid")
        self.profile = profile
        self.definition = definition
        self.runner = runner
        self.run_id = run_id
        self.monotonic = monotonic
        self.sleep = sleep
        self._sequence = 0
        self.runtime_root = Path(str(profile.target.runtime_root))
        self.active_path = self.runtime_root / "acceptance/active-case.json"
        self.windows_root = self.runtime_root / "acceptance/trigger-windows"
        self.event_path = Path(str(profile.evidence_spool)) / "probe-events.jsonl"

    def bind_run_id(self, run_id: str) -> None:
        if _SAFE_ID.fullmatch(run_id) is None:
            raise ValidationError("native probe run id is invalid")
        if self._sequence and self.run_id != run_id:
            raise ValidationError("native probe run id cannot change after a trigger")
        self.run_id = run_id

    def _open_window(self, case_id: str) -> tuple[NativeTriggerWindow, int]:
        if case_id not in {"immediate_trigger", "native_non_overlap"}:
            raise ValidationError("native probe case is invalid")
        if self.active_path.exists() or self.active_path.is_symlink():
            raise ValidationError("native trigger window is already active")
        if self.event_path.is_symlink():
            raise ValidationError("native probe event spool cannot be a symlink")
        size = self.event_path.stat().st_size if self.event_path.exists() else 0
        if size > _MAX_SPOOL_BYTES:
            raise ValidationError("native probe event spool exceeds its bound")
        self._sequence += 1
        window = NativeTriggerWindow(
            str(uuid4()), self.run_id, self._sequence, case_id,
            self.profile.target.receipt_id, self.profile.release_sha256,
            self.definition.sha256,
        )
        stored = NativeTriggerWindow.from_mapping(window.to_mapping())
        self.windows_root.mkdir(parents=True, exist_ok=True)
        record = self.windows_root / f"{stored.window_id}.json"
        if record.exists() or record.is_symlink():
            raise ValidationError("native trigger window already exists")
        _atomic_write(record, stored.canonical_bytes())
        _atomic_write(self.active_path, stored.canonical_bytes())
        return stored, size

    def _events(self, window: NativeTriggerWindow, offset: int) -> list[dict[str, object]]:
        if not self.event_path.exists():
            return []
        if self.event_path.is_symlink() or self.event_path.stat().st_size > _MAX_SPOOL_BYTES:
            raise ValidationError("native probe event spool is invalid")
        with self.event_path.open("rb") as stream:
            stream.seek(offset)
            content = stream.read(_MAX_SPOOL_BYTES + 1)
        if len(content) > _MAX_SPOOL_BYTES:
            raise ValidationError("native probe event spool exceeds its bound")
        if content and not content.endswith(b"\n"):
            raise ValidationError("native probe event spool is incomplete")
        matches: list[dict[str, object]] = []
        expected = window.to_mapping()
        for raw in content.splitlines():
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValidationError("native probe event is invalid") from exc
            if not isinstance(value, dict) or raw + b"\n" != _canonical(value):
                raise ValidationError("native probe event is not canonical")
            if value.get("format") != "projectos-probe-event-v2":
                continue
            if all(value.get(field) == expected[field] for field in expected if field != "format"):
                matches.append(value)
        return matches

    def _wait_sequence(
        self,
        window: NativeTriggerWindow,
        offset: int,
        expected_statuses: tuple[str, ...],
    ) -> list[dict[str, object]]:
        deadline = self.monotonic() + self.profile.max_probe_seconds
        while self.monotonic() < deadline:
            events = self._events(window, offset)
            statuses = tuple(str(event.get("status")) for event in events)
            if statuses and statuses != expected_statuses[: len(statuses)]:
                raise ValidationError("native probe events are duplicated or reordered")
            if len(events) > len(expected_statuses):
                raise ValidationError("native probe events are duplicated or reordered")
            if statuses == expected_statuses:
                return events
            self.sleep(0.02)
        raise ValidationError("native probe event timed out")

    def _trigger(self) -> None:
        inspection = self.runner.trigger(self.definition)
        if (
            inspection.state is not SchedulerState.ENABLED
            or inspection.definition_sha256 != self.definition.sha256
        ):
            raise ValidationError("native trigger did not preserve owned enabled state")

    def prove_immediate(self) -> ProbeResult:
        window, offset = self._open_window("immediate_trigger")
        try:
            self._trigger()
            events = self._wait_sequence(window, offset, ("COMPLETE",))
            return ProbeResult(True, "COMPLETE", str(events[0].get("code")))
        finally:
            self.active_path.unlink(missing_ok=True)

    def prove_non_overlap(self) -> ProbeResult:
        window, offset = self._open_window("native_non_overlap")
        barrier_root = self.runtime_root / "acceptance/barriers"
        active = barrier_root / "native_non_overlap.active"
        release = barrier_root / "native_non_overlap.release"
        try:
            self._trigger()
            self._wait_sequence(window, offset, ("STARTED",))
            if not active.is_file() or active.is_symlink():
                raise ValidationError("native non-overlap barrier did not start")
            if active.read_text(encoding="ascii").strip() != self.profile.target.receipt_id:
                raise ValidationError("native non-overlap barrier is not receipt-bound")
            self._trigger()
            events = self._wait_sequence(window, offset, ("STARTED", "LOCKED"))
            _atomic_write(release, (self.profile.target.receipt_id + "\n").encode("ascii"))
            self._wait_sequence(window, offset, ("STARTED", "LOCKED", "COMPLETE"))
            return ProbeResult(True, "LOCKED", str(events[-1].get("code")))
        finally:
            self.active_path.unlink(missing_ok=True)
            active.unlink(missing_ok=True)
            release.unlink(missing_ok=True)
