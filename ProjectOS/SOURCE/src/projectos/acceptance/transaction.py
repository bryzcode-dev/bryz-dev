from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

from projectos.acceptance.authority import AcceptanceTarget
from projectos.acceptance.journal import HostAcceptanceJournal, HostAcceptanceState
from projectos.acceptance.profile import AcceptanceProfile
from projectos.acceptance.probe import ProbeResult
from projectos.acceptance.store import LocalAcceptanceStore
from projectos.adoption.scheduler import (
    EXECUTION_LIMIT_SECONDS,
    SCHEDULE_INTERVAL_SECONDS,
    SchedulerAction,
    SchedulerDefinition,
    SchedulerState,
)
from projectos.errors import ValidationError


class DefinitionController(Protocol):
    active: bool
    def adopt(self) -> None: ...
    def rollback(self) -> None: ...


class ActivationController(Protocol):
    active: bool
    def activate(self) -> None: ...
    def deactivate(self) -> None: ...


class ProbeController(Protocol):
    def prove_immediate(self) -> ProbeResult: ...
    def prove_non_overlap(self) -> ProbeResult: ...


@dataclass(frozen=True)
class HostAcceptanceContext:
    target: AcceptanceTarget
    profile: AcceptanceProfile
    store: LocalAcceptanceStore
    definition: SchedulerDefinition
    native_runner: object
    definition_controller: DefinitionController
    activation_controller: ActivationController
    probe: ProbeController
    database_health: Callable[[], bool]
    evidence_sealer: Callable[[HostAcceptanceResult], None]
    package_verified: bool
    preparation_record: Any | None = None
    preparation_record_bytes: bytes | None = None
    evidence_root: Path | None = None
    standard_user: bool = False
    non_elevated: bool = False
    structural_equivalence: bool = False


@dataclass(frozen=True)
class HostAcceptanceResult:
    run_id: str
    state: HostAcceptanceState
    proved_cases: tuple[str, ...]
    cleanup_complete: bool
    error_codes: tuple[str, ...]


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


class HostAcceptanceTransaction:
    _ORDER = (
        HostAcceptanceState.PREFLIGHTED,
        HostAcceptanceState.DEFINITION_ADOPTED,
        HostAcceptanceState.RUNTIME_ACTIVATED,
        HostAcceptanceState.NATIVE_STAGED,
        HostAcceptanceState.NATIVE_ENABLED,
        HostAcceptanceState.IMMEDIATE_PROVED,
        HostAcceptanceState.NON_OVERLAP_PROVED,
        HostAcceptanceState.SCHEDULE_PROVED,
        HostAcceptanceState.DEACTIVATED,
        HostAcceptanceState.NATIVE_REMOVED,
        HostAcceptanceState.DEFINITION_ROLLED_BACK,
        HostAcceptanceState.EVIDENCE_SEALED,
    )

    def __init__(self, context: HostAcceptanceContext):
        self.context = context
        self.run_id = ""
        self.journal: HostAcceptanceJournal | None = None

    @classmethod
    def boundaries(cls) -> tuple[str, ...]:
        values = [state.value for state in cls._ORDER]
        values.insert(values.index(HostAcceptanceState.NATIVE_STAGED.value), "after_native_install_before_journal")
        values.insert(values.index(HostAcceptanceState.NATIVE_ENABLED.value), "after_native_enable_before_journal")
        values.insert(values.index(HostAcceptanceState.NATIVE_REMOVED.value), "after_native_disable_before_journal")
        values.insert(values.index(HostAcceptanceState.NATIVE_REMOVED.value), "after_native_remove_before_journal")
        return tuple(values)

    def _journal_path(self, run_id: str) -> Path:
        return self.context.store.root / "runs" / run_id / "journal.json"

    def _save(self) -> None:
        if self.journal is None:
            raise ValidationError("host acceptance journal is unavailable")
        _atomic_write(self._journal_path(self.journal.run_id), self.journal.canonical_bytes())

    def _load(self, run_id: str) -> HostAcceptanceJournal:
        path = self._journal_path(run_id)
        try:
            content = path.read_bytes()
            value = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("host acceptance journal is unavailable") from exc
        if not isinstance(value, dict):
            raise ValidationError("host acceptance journal is invalid")
        journal = HostAcceptanceJournal.from_mapping(value)
        if content != journal.canonical_bytes() or journal.run_id != run_id:
            raise ValidationError("host acceptance journal is not canonical")
        return journal

    def result(self) -> HostAcceptanceResult:
        if self.journal is None:
            raise ValidationError("host acceptance journal is unavailable")
        return self._result_from(self.journal)

    @staticmethod
    def _result_from(journal: HostAcceptanceJournal) -> HostAcceptanceResult:
        return HostAcceptanceResult(
            journal.run_id, journal.state, journal.proved_cases,
            journal.cleanup_complete, journal.error_codes,
        )

    def begin(self, *, boundary_hook: Callable[[str], None] = lambda name: None) -> HostAcceptanceResult:
        if self.journal is not None:
            raise ValidationError("host acceptance transaction already started")
        self.run_id = str(uuid4())
        binder = getattr(self.context.probe, "bind_run_id", None)
        if binder is not None:
            binder(self.run_id)
        profile = self.context.profile
        self.journal = HostAcceptanceJournal(
            self.run_id,
            HostAcceptanceState.DISCOVERED,
            self.context.target.acceptance_id,
            self.context.target.receipt_id,
            profile.release_sha256,
            profile.wheel_sha256,
            self.context.definition.sha256,
            (HostAcceptanceState.DISCOVERED.value,),
            (),
            False,
            (),
        )
        self._save()
        try:
            return self._continue(boundary_hook)
        except Exception as exc:
            if self.journal.state is not HostAcceptanceState.FAILED:
                self.journal = self.journal.transition(
                    HostAcceptanceState.FAILED,
                    error_code=type(exc).__name__.casefold(),
                )
                self._save()
            raise

    def resume(
        self, run_id: str, *, boundary_hook: Callable[[str], None] = lambda name: None
    ) -> HostAcceptanceResult:
        self.run_id = run_id
        self.journal = self._load(run_id)
        binder = getattr(self.context.probe, "bind_run_id", None)
        if binder is not None:
            binder(run_id)
        if self.journal.state is HostAcceptanceState.FAILED:
            return self.recover(run_id)
        return self._continue(boundary_hook)

    def _advance(
        self,
        state: HostAcceptanceState,
        hook: Callable[[str], None],
        *,
        proved_case: str | None = None,
    ) -> None:
        self.journal = self.journal.transition(state, proved_case=proved_case)
        if self.journal.pending_effect is not None:
            self.journal = replace(self.journal, pending_effect=None)
        self._save()
        hook(state.value)

    def _continue(self, hook: Callable[[str], None]) -> HostAcceptanceResult:
        while self.journal.state is not HostAcceptanceState.EVIDENCE_SEALED:
            state = self.journal.state
            if state is HostAcceptanceState.DISCOVERED:
                self._preflight()
                self._advance(HostAcceptanceState.PREFLIGHTED, hook)
            elif state is HostAcceptanceState.PREFLIGHTED:
                self.context.definition_controller.adopt()
                self._advance(HostAcceptanceState.DEFINITION_ADOPTED, hook)
            elif state is HostAcceptanceState.DEFINITION_ADOPTED:
                self.context.activation_controller.activate()
                self._advance(HostAcceptanceState.RUNTIME_ACTIVATED, hook)
            elif state is HostAcceptanceState.RUNTIME_ACTIVATED:
                self._before_native_effect("install")
                inspection = self.context.native_runner.perform(SchedulerAction.INSTALL, self.context.definition)
                if inspection.state is not SchedulerState.INSTALLED_DISABLED:
                    raise ValidationError("native scheduler was not staged disabled")
                hook("after_native_install_before_journal")
                self._advance(HostAcceptanceState.NATIVE_STAGED, hook)
            elif state is HostAcceptanceState.NATIVE_STAGED:
                self._before_native_effect("enable")
                inspection = self.context.native_runner.perform(SchedulerAction.ENABLE, self.context.definition)
                if inspection.state is not SchedulerState.ENABLED:
                    raise ValidationError("native scheduler was not enabled")
                hook("after_native_enable_before_journal")
                self._advance(HostAcceptanceState.NATIVE_ENABLED, hook)
            elif state is HostAcceptanceState.NATIVE_ENABLED:
                result = self.context.probe.prove_immediate()
                self._require_probe_result(result, "immediate_trigger", "COMPLETE")
                self._advance(HostAcceptanceState.IMMEDIATE_PROVED, hook, proved_case="immediate_trigger")
            elif state is HostAcceptanceState.IMMEDIATE_PROVED:
                result = self.context.probe.prove_non_overlap()
                self._require_probe_result(result, "native_non_overlap", "LOCKED")
                self.journal = self.journal.transition(state, proved_case="common_lock_contention")
                self._advance(HostAcceptanceState.NON_OVERLAP_PROVED, hook, proved_case="native_non_overlap")
            elif state is HostAcceptanceState.NON_OVERLAP_PROVED:
                if (
                    self.context.definition.interval_seconds != SCHEDULE_INTERVAL_SECONDS
                    or self.context.definition.execution_limit_seconds != EXECUTION_LIMIT_SECONDS
                ):
                    raise ValidationError("native schedule configuration is invalid")
                self.journal = self.journal.transition(state, proved_case="eligible_resume_configuration")
                self.journal = self.journal.transition(state, proved_case="skill_discovery")
                self._advance(HostAcceptanceState.SCHEDULE_PROVED, hook, proved_case="two_hour_configuration")
            elif state is HostAcceptanceState.SCHEDULE_PROVED:
                self.context.activation_controller.deactivate()
                self._advance(HostAcceptanceState.DEACTIVATED, hook)
            elif state is HostAcceptanceState.DEACTIVATED:
                self._before_native_effect("disable")
                self.context.native_runner.perform(SchedulerAction.DISABLE, self.context.definition)
                hook("after_native_disable_before_journal")
                self._before_native_effect("remove")
                removed = self.context.native_runner.perform(SchedulerAction.REMOVE, self.context.definition)
                if removed.state is not SchedulerState.ABSENT:
                    raise ValidationError("native scheduler removal failed")
                hook("after_native_remove_before_journal")
                self._advance(HostAcceptanceState.NATIVE_REMOVED, hook)
            elif state is HostAcceptanceState.NATIVE_REMOVED:
                self.context.definition_controller.rollback()
                self._advance(HostAcceptanceState.DEFINITION_ROLLED_BACK, hook)
            elif state is HostAcceptanceState.DEFINITION_ROLLED_BACK:
                if not self.context.database_health():
                    raise ValidationError("retained acceptance database is unhealthy")
                self.journal = self.journal.transition(state, proved_case="retained_database_health")
                self.journal = self.journal.transition(state, proved_case="definition_rollback")
                self.journal = self.journal.transition(state, proved_case="native_disable_remove")
                self.journal = self.journal.transition(state, cleanup_complete=True)
                projected = self.journal.transition(HostAcceptanceState.EVIDENCE_SEALED)
                self.context.evidence_sealer(self._result_from(projected))
                self.journal = projected
                self._save()
                hook(HostAcceptanceState.EVIDENCE_SEALED.value)
            else:
                raise ValidationError("host acceptance cannot continue from current state")
        return self.result()

    def _preflight(self) -> None:
        if not self.context.package_verified:
            raise ValidationError("acceptance package is not verified")
        if self.context.profile.target != self.context.target or self.context.store.target != self.context.target:
            raise ValidationError("acceptance authority does not match context")
        database = Path(str(self.context.profile.machine_profile.database_path))
        self.context.target.assert_runtime_path(database)
        if not database.is_file() or database.is_symlink() or not self.context.database_health():
            raise ValidationError("disposable acceptance database is unavailable or unhealthy")
        inspection = self.context.native_runner.perform(SchedulerAction.INSPECT, self.context.definition)
        if inspection.state is not SchedulerState.ABSENT:
            raise ValidationError("foreign existing task prevents acceptance")

    @staticmethod
    def _require_probe_result(result: ProbeResult, case_id: str, status: str) -> None:
        if not result.ok or result.status != status:
            raise ValidationError(f"acceptance probe case failed: {case_id}")

    def _before_native_effect(self, effect: str) -> None:
        if self.journal is None:
            raise ValidationError("host acceptance journal is unavailable")
        self.journal = replace(self.journal, pending_effect=effect)
        self._save()

    def recover(self, run_id: str) -> HostAcceptanceResult:
        self.run_id = run_id
        self.journal = self._load(run_id)
        binder = getattr(self.context.probe, "bind_run_id", None)
        if binder is not None:
            binder(run_id)
        if self.journal.cleanup_complete:
            return self.result()
        if self.context.activation_controller.active:
            self.context.activation_controller.deactivate()
        inspection = self.context.native_runner.perform(SchedulerAction.INSPECT, self.context.definition)
        if inspection.state is not SchedulerState.ABSENT:
            if inspection.definition_sha256 != self.context.definition.sha256:
                raise ValidationError("native definition hash mismatch stops recovery")
            if inspection.state is SchedulerState.ENABLED:
                self.context.native_runner.perform(SchedulerAction.DISABLE, self.context.definition)
            self.context.native_runner.perform(SchedulerAction.REMOVE, self.context.definition)
        if self.context.definition_controller.active:
            self.context.definition_controller.rollback()
        self.journal = self.journal.transition(
            HostAcceptanceState.FAILED, cleanup_complete=True
        )
        self._save()
        return self.result()
