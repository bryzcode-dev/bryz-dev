from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from projectos.acceptance.authority import (
    ACCEPTANCE_ACKNOWLEDGEMENT,
    AcceptanceTarget,
    detect_host_session,
)
from projectos.acceptance.profile import AcceptanceProfile, acceptance_machine_profile
from projectos.google.contract import WorkbookContract
from projectos.google.fake_gateway import FakeGoogleGateway
from projectos.errors import ValidationError
from projectos.runtime import RuntimeSyncCoordinator, RuntimeTrigger, load_runtime_profile


_PROBE_CASES = {"immediate_trigger", "common_lock_contention", "native_non_overlap"}
_MAX_EVENT_BYTES = 1024
_MAX_SPOOL_BYTES = 64 * 1024


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    status: str
    code: str


def _fake_gateway() -> FakeGoogleGateway:
    contract = WorkbookContract.current()
    return FakeGoogleGateway(
        {
            "contract_version": contract.version,
            "tabs": {
                tab.name: {"headers": list(tab.headers), "row_count": 0}
                for tab in contract.tabs
            },
            "requests": [],
            "access_events": [],
            "write_ready": True,
        }
    )


def _append_event(
    profile: AcceptanceProfile,
    case_id: str,
    status: str,
    code: str,
    *,
    native_window: dict[str, Any] | None = None,
) -> None:
    event = {
        "case_id": case_id,
        "code": code,
        "format": "projectos-probe-event-v2" if native_window is not None else "projectos-probe-event-v1",
        "status": status,
    }
    if native_window is not None:
        expected = {
            "case_id", "definition_sha256", "format", "receipt_id", "release_sha256",
            "run_id", "sequence", "window_id",
        }
        if set(native_window) != expected or native_window.get("case_id") != case_id:
            raise ValidationError("native trigger window is invalid")
        for field in expected - {"format", "case_id"}:
            event[field] = native_window[field]
    content = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(content) > _MAX_EVENT_BYTES:
        raise ValidationError("acceptance probe event exceeds its bound")
    spool = Path(str(profile.evidence_spool))
    spool.mkdir(parents=True, exist_ok=True)
    path = spool / "probe-events.jsonl"
    if path.is_symlink():
        raise ValidationError("acceptance probe event spool cannot be a symlink")
    prior_size = path.stat().st_size if path.exists() else 0
    if prior_size + len(content) > _MAX_SPOOL_BYTES:
        raise ValidationError("acceptance probe event spool exceeds its bound")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        written = os.write(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if written != len(content):
        raise ValidationError("acceptance probe event append was incomplete")


def _load_acceptance_profile(profile_path: Path) -> tuple[AcceptanceProfile, Path]:
    production = load_runtime_profile(profile_path)
    runtime = Path(str(production.runtime_root))
    local_path = runtime / "acceptance/state/acceptance-profile.json"
    if not local_path.is_file() or local_path.is_symlink():
        raise ValidationError("acceptance profile is unavailable or invalid")
    try:
        content = local_path.read_bytes()
        value: Any = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("acceptance profile is unavailable or invalid") from exc
    if not isinstance(value, dict) or not isinstance(value.get("acceptance_root"), str):
        raise ValidationError("acceptance profile is unavailable or invalid")
    target = AcceptanceTarget.open(
        value["acceptance_root"],
        runtime,
        ACCEPTANCE_ACKNOWLEDGEMENT,
        detect_host_session(),
        excluded_roots=(production.contextos_root,),
    )
    profile = AcceptanceProfile.from_mapping(value, target)
    if content != profile.canonical_bytes():
        raise ValidationError("acceptance profile is not canonical")
    if profile.machine_profile != acceptance_machine_profile(production):
        raise ValidationError("acceptance profile does not match runtime machine profile")
    return profile, runtime


class AcceptanceProbe:
    def run(
        self,
        profile_path: Path,
        database_path: Path,
        trigger: RuntimeTrigger,
        case_id: str,
        native_window: dict[str, Any] | None = None,
    ) -> ProbeResult:
        if RuntimeTrigger(trigger) is not RuntimeTrigger.SCHEDULER:
            raise ValidationError("acceptance probe permits only the scheduler trigger")
        if case_id not in _PROBE_CASES:
            raise ValidationError("acceptance probe case is invalid")
        profile, _runtime = _load_acceptance_profile(Path(profile_path))
        database = Path(database_path)
        expected_database = Path(str(profile.machine_profile.database_path))
        if database.is_symlink() or database.resolve(strict=False) != expected_database.resolve(strict=False):
            raise ValidationError("acceptance database does not match profile")
        profile.target.assert_runtime_path(database)
        if case_id == "native_non_overlap":
            barrier_result = self._enter_barrier(profile, case_id, native_window)
            if barrier_result is not None:
                return barrier_result
        result = RuntimeSyncCoordinator().run(
            Path(profile_path), database, RuntimeTrigger.SCHEDULER, _fake_gateway()
        )
        expected = "LOCKED" if case_id == "common_lock_contention" else "COMPLETE"
        ok = result.status == expected
        code = "SYNC_LOCKED" if result.status == "LOCKED" else f"SYNC_{result.status}"
        _append_event(profile, case_id, result.status, code, native_window=native_window)
        return ProbeResult(ok, result.status, code)

    @staticmethod
    def _enter_barrier(
        profile: AcceptanceProfile,
        case_id: str,
        native_window: dict[str, Any] | None,
    ) -> ProbeResult | None:
        barrier_root = profile.target.runtime_root / "acceptance/barriers"
        barrier_root.mkdir(parents=True, exist_ok=True)
        active = barrier_root / f"{case_id}.active"
        release = barrier_root / f"{case_id}.release"
        if active.is_symlink() or release.is_symlink():
            raise ValidationError("acceptance barrier cannot use a symlink")
        try:
            descriptor = os.open(active, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                owner = active.read_text(encoding="ascii").strip()
            except OSError as exc:
                raise ValidationError("acceptance barrier is unavailable") from exc
            if owner != profile.target.receipt_id:
                raise ValidationError("acceptance barrier is not receipt-bound")
            _append_event(
                profile, case_id, "LOCKED", "BARRIER_BUSY", native_window=native_window
            )
            return ProbeResult(True, "LOCKED", "BARRIER_BUSY")
        try:
            os.write(descriptor, (profile.target.receipt_id + "\n").encode("ascii"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _append_event(
            profile, case_id, "STARTED", "BARRIER_STARTED", native_window=native_window
        )
        deadline = time.monotonic() + profile.max_probe_seconds
        try:
            while time.monotonic() < deadline:
                if release.is_file():
                    if release.read_text(encoding="ascii").strip() != profile.target.receipt_id:
                        raise ValidationError("acceptance barrier release is not receipt-bound")
                    return None
                time.sleep(0.02)
            _append_event(
                profile, case_id, "FAILED", "BARRIER_TIMEOUT", native_window=native_window
            )
            return ProbeResult(False, "FAILED", "BARRIER_TIMEOUT")
        finally:
            active.unlink(missing_ok=True)
            release.unlink(missing_ok=True)
