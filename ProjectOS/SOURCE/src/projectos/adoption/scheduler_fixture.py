from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from projectos.adoption.fixture import FixtureInstallationTarget
from projectos.adoption.profile import MachineProfile
from projectos.adoption.scheduler import (
    EXECUTION_LIMIT_SECONDS,
    SCHEDULE_INTERVAL_SECONDS,
    SchedulerAction,
    SchedulerDefinition,
    SchedulerInspection,
    SchedulerState,
    adapter_for,
)
from projectos.adoption.store import LocalAdoptionStore
from projectos.errors import ValidationError
from projectos.validation import reject_secret_material


_STATE_FIELDS = {
    "format",
    "fixture_id",
    "installation_id",
    "scheduler_kind",
    "task_id",
    "definition_sha256",
    "state",
}


def _canonical(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


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


@dataclass
class FixtureSchedulerRunner:
    target: FixtureInstallationTarget
    profile: MachineProfile
    store: LocalAdoptionStore
    root: Path

    @classmethod
    def open(
        cls,
        target: FixtureInstallationTarget,
        profile: MachineProfile,
        store: LocalAdoptionStore,
    ) -> "FixtureSchedulerRunner":
        if store.profile != profile:
            raise ValidationError("scheduler fixture profile does not match adoption store")
        if (
            target.root.resolve(strict=False)
            != Path(str(profile.contextos_root)).resolve(strict=False)
            or target.extensions_root.resolve(strict=False)
            != Path(str(profile.extensions_root)).resolve(strict=False)
        ):
            raise ValidationError("scheduler fixture target does not match profile")
        expected_store = Path(str(profile.runtime_root)) / "adoption"
        if store.root.resolve(strict=False) != expected_store.resolve(strict=False):
            raise ValidationError("scheduler fixture store does not match profile")
        fixtures_root = store.root / "scheduler-fixtures"
        if store.root.is_symlink() or fixtures_root.is_symlink():
            raise ValidationError("scheduler fixture state cannot use a symlink")
        task_hash = hashlib.sha256(
            f"{profile.scheduler_kind.value}:{profile.scheduler_task_id}".encode("utf-8")
        ).hexdigest()
        root = fixtures_root / task_hash
        if root.is_symlink():
            raise ValidationError("scheduler fixture state cannot use a symlink")
        return cls(target, profile, store, root)

    @property
    def _state_path(self) -> Path:
        return self.root / "state.json"

    @property
    def _definition_path(self) -> Path:
        return self.root / "definition.bin"

    def _validate_definition(self, definition: SchedulerDefinition) -> None:
        if (
            definition.host_family is not self.profile.host_family
            or definition.scheduler_kind is not self.profile.scheduler_kind
            or definition.task_id != self.profile.scheduler_task_id
            or definition.interval_seconds != SCHEDULE_INTERVAL_SECONDS
            or definition.execution_limit_seconds != EXECUTION_LIMIT_SECONDS
            or definition.enabled
            or definition.sha256 != hashlib.sha256(definition.content).hexdigest()
        ):
            raise ValidationError("scheduler fixture definition is invalid")
        entrypoint = tuple(self.profile.projectos_entrypoint)
        if (
            definition.argv[: len(entrypoint)] != entrypoint
            or definition.argv[0] != str(self.profile.python_executable)
        ):
            raise ValidationError("scheduler fixture executable is invalid")
        executable = Path(definition.argv[0]).name.casefold()
        if executable in {"launchctl", "schtasks", "schtasks.exe", "powershell", "powershell.exe", "cmd.exe"}:
            raise ValidationError("scheduler fixture native executable is prohibited")
        adapter_for(self.profile).verify(
            definition,
            self.profile,
            self.store.root / "machine-profile.json",
        )

    def _mapping(
        self, definition: SchedulerDefinition, state: SchedulerState
    ) -> dict[str, object]:
        return {
            "format": "projectos-scheduler-fixture-v1",
            "fixture_id": self.target.fixture_id,
            "installation_id": self.profile.installation_id,
            "scheduler_kind": self.profile.scheduler_kind.value,
            "task_id": self.profile.scheduler_task_id,
            "definition_sha256": definition.sha256,
            "state": state.value,
        }

    def _load(self, definition: SchedulerDefinition) -> SchedulerState:
        state_exists = self._state_path.exists()
        definition_exists = self._definition_path.exists()
        if not state_exists and not definition_exists:
            return SchedulerState.ABSENT
        if (
            state_exists != definition_exists
            or self._state_path.is_symlink()
            or self._definition_path.is_symlink()
        ):
            raise ValidationError("scheduler fixture state is incomplete or unsafe")
        try:
            state_content = self._state_path.read_bytes()
            value = json.loads(state_content)
            definition_content = self._definition_path.read_bytes()
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("scheduler fixture state is unavailable or invalid") from exc
        if not isinstance(value, dict) or set(value) != _STATE_FIELDS:
            raise ValidationError("scheduler fixture state fields are invalid")
        reject_secret_material(value)
        try:
            state = SchedulerState(value["state"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("scheduler fixture state is invalid") from exc
        expected = self._mapping(definition, state)
        if value != expected or state_content != _canonical(expected):
            raise ValidationError("scheduler fixture state does not match definition")
        if (
            definition_content != definition.content
            or hashlib.sha256(definition_content).hexdigest() != definition.sha256
        ):
            raise ValidationError("scheduler fixture definition has changed")
        return state

    def inspect(self, definition: SchedulerDefinition) -> SchedulerInspection:
        self._validate_definition(definition)
        state = self._load(definition)
        return SchedulerInspection(
            definition.task_id,
            state,
            definition.sha256 if state is not SchedulerState.ABSENT else None,
        )

    def perform(
        self, action: SchedulerAction, definition: SchedulerDefinition
    ) -> SchedulerInspection:
        try:
            selected = SchedulerAction(action)
        except ValueError as exc:
            raise ValidationError("scheduler fixture action is invalid") from exc
        if selected is SchedulerAction.INSPECT:
            return self.inspect(definition)
        self._validate_definition(definition)
        current = self._load(definition)
        if selected is SchedulerAction.INSTALL:
            if current is SchedulerState.INSTALLED_DISABLED:
                return self.inspect(definition)
            if current is not SchedulerState.ABSENT:
                raise ValidationError("scheduler fixture transition is invalid")
            _atomic_write(self._definition_path, definition.content)
            next_state = SchedulerState.INSTALLED_DISABLED
            _atomic_write(self._state_path, _canonical(self._mapping(definition, next_state)))
        elif selected is SchedulerAction.ENABLE:
            if current is SchedulerState.ENABLED:
                return self.inspect(definition)
            if current is not SchedulerState.INSTALLED_DISABLED:
                raise ValidationError("scheduler fixture transition is invalid")
            next_state = SchedulerState.ENABLED
            _atomic_write(self._state_path, _canonical(self._mapping(definition, next_state)))
        elif selected is SchedulerAction.DISABLE:
            if current is SchedulerState.INSTALLED_DISABLED:
                return self.inspect(definition)
            if current is not SchedulerState.ENABLED:
                raise ValidationError("scheduler fixture transition is invalid")
            next_state = SchedulerState.INSTALLED_DISABLED
            _atomic_write(self._state_path, _canonical(self._mapping(definition, next_state)))
        elif selected is SchedulerAction.REMOVE:
            if current is SchedulerState.ABSENT:
                return self.inspect(definition)
            if current is not SchedulerState.INSTALLED_DISABLED:
                raise ValidationError("scheduler fixture transition is invalid")
            entries = {path.name for path in self.root.iterdir()}
            if entries != {"definition.bin", "state.json"}:
                raise ValidationError("scheduler fixture contains unmanaged state")
            self._state_path.unlink()
            self._definition_path.unlink()
            self.root.rmdir()
            return SchedulerInspection(definition.task_id, SchedulerState.ABSENT, None)
        else:
            raise ValidationError("scheduler fixture action is invalid")
        return self.inspect(definition)
