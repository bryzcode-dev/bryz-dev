from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import tempfile
from pathlib import Path

from projectos.acceptance.model import ACCEPTANCE_TASKS
from projectos.acceptance.native import NativeProcessExecutor
from projectos.adoption.host import HostFamily
from projectos.adoption.scheduler import (
    SchedulerAction,
    SchedulerDefinition,
    SchedulerInspection,
    SchedulerState,
)
from projectos.errors import ValidationError


_TIMEOUT = 30


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


class MacOSNativeSchedulerRunner:
    def __init__(
        self,
        runtime_root: Path,
        uid: int,
        executor: NativeProcessExecutor,
        *,
        elevated: bool = False,
    ) -> None:
        self.runtime_root = Path(runtime_root).expanduser().resolve(strict=False)
        self.uid = uid
        self.executor = executor
        self.elevated = elevated
        self.native_root = self.runtime_root / "native/macos"

    def _plist_path(self, definition: SchedulerDefinition) -> Path:
        return self.native_root / f"{definition.task_id}.plist"

    def _ownership_path(self, definition: SchedulerDefinition) -> Path:
        return self.native_root / f"{definition.task_id}.ownership.json"

    def _domain(self) -> str:
        return f"gui/{self.uid}"

    def _service(self, definition: SchedulerDefinition) -> str:
        return f"{self._domain()}/{definition.task_id}"

    def planned_actions(self, definition: SchedulerDefinition) -> tuple[tuple[str, ...], ...]:
        self._validate(definition)
        plist_path = str(self._plist_path(definition))
        service = self._service(definition)
        domain = self._domain()
        return (
            ("launchctl", "print", service),
            ("launchctl", "bootstrap", domain, plist_path),
            ("launchctl", "enable", service),
            ("launchctl", "kickstart", service),
            ("launchctl", "print", service),
            ("launchctl", "print-disabled", domain),
            ("launchctl", "disable", service),
            ("launchctl", "bootout", domain, plist_path),
        )

    def _validate(self, definition: SchedulerDefinition) -> None:
        if self.elevated or self.uid == 0:
            raise ValidationError("macOS acceptance rejects an elevated session")
        if definition.host_family is not HostFamily.MACOS:
            raise ValidationError("macOS runner requires a macOS definition")
        if definition.task_id != ACCEPTANCE_TASKS["macos"]:
            raise ValidationError("macOS runner requires the dedicated acceptance task")
        if hashlib.sha256(definition.content).hexdigest() != definition.sha256:
            raise ValidationError("scheduler definition hash is invalid")
        if definition.enabled:
            raise ValidationError("acceptance scheduler definition must be disabled")
        try:
            parsed = plistlib.loads(definition.content)
        except Exception as exc:
            raise ValidationError("macOS scheduler definition is invalid") from exc
        if (
            parsed.get("Label") != definition.task_id
            or parsed.get("ProgramArguments") != list(definition.argv)
            or parsed.get("Disabled") is not True
            or parsed.get("WorkingDirectory") != str(self.runtime_root)
        ):
            raise ValidationError("macOS scheduler definition is not canonical")
        if self.runtime_root.is_symlink() or self.native_root.is_symlink():
            raise ValidationError("macOS native state cannot use a symlink")

    @staticmethod
    def _require_success(result, action: str) -> None:
        if result.timed_out or result.returncode != 0:
            raise ValidationError(f"macOS native {action} failed")

    @staticmethod
    def _is_absent(result) -> bool:
        return (
            not result.timed_out
            and result.returncode in {3, 113}
            and result.stdout == ""
            and result.stderr.strip() == "Could not find service"
        )

    def _owner_hash(self, definition: SchedulerDefinition) -> str | None:
        path = self._ownership_path(definition)
        if not path.exists():
            return None
        if path.is_symlink():
            raise ValidationError("macOS ownership record cannot be a symlink")
        try:
            content = path.read_bytes()
            value = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("macOS ownership record is invalid") from exc
        expected = {"definition_sha256": definition.sha256, "format": "projectos-macos-native-owner-v1", "task_id": definition.task_id}
        if value != expected or content != _canonical(expected):
            raise ValidationError("macOS owned definition hash does not match")
        return definition.sha256

    def _write_owned_definition(self, definition: SchedulerDefinition) -> None:
        self._validate(definition)
        _atomic_write(self._plist_path(definition), definition.content)
        _atomic_write(
            self._ownership_path(definition),
            _canonical({
                "definition_sha256": definition.sha256,
                "format": "projectos-macos-native-owner-v1",
                "task_id": definition.task_id,
            }),
        )

    def _inspect(self, definition: SchedulerDefinition) -> SchedulerInspection:
        present = self.executor.run(("launchctl", "print", self._service(definition)), _TIMEOUT)
        if self._is_absent(present):
            return SchedulerInspection(definition.task_id, SchedulerState.ABSENT, None)
        if present.timed_out or present.returncode != 0 or not present.stdout.strip():
            raise ValidationError("macOS inspection output is invalid")
        disabled = self.executor.run(("launchctl", "print-disabled", self._domain()), _TIMEOUT)
        if disabled.timed_out or disabled.returncode != 0:
            raise ValidationError("macOS inspection output is invalid")
        matches = re.findall(
            rf'"{re.escape(definition.task_id)}"\s*=>\s*(true|false)', disabled.stdout
        )
        if len(matches) != 1:
            raise ValidationError("macOS inspection output is invalid")
        owner = self._owner_hash(definition)
        return SchedulerInspection(
            definition.task_id,
            SchedulerState.INSTALLED_DISABLED if matches[0] == "true" else SchedulerState.ENABLED,
            owner,
        )

    def perform(
        self, action: SchedulerAction, definition: SchedulerDefinition
    ) -> SchedulerInspection:
        selected = SchedulerAction(action)
        self._validate(definition)
        owner = self._owner_hash(definition)
        if selected is SchedulerAction.INSTALL:
            if owner is not None:
                return SchedulerInspection(definition.task_id, SchedulerState.INSTALLED_DISABLED, owner)
            existing = self.executor.run(("launchctl", "print", self._service(definition)), _TIMEOUT)
            if not self._is_absent(existing):
                raise ValidationError("macOS acceptance found an existing task")
            self._write_owned_definition(definition)
            result = self.executor.run(
                ("launchctl", "bootstrap", self._domain(), str(self._plist_path(definition))),
                _TIMEOUT,
            )
            try:
                self._require_success(result, "bootstrap")
            except ValidationError:
                self._plist_path(definition).unlink(missing_ok=True)
                self._ownership_path(definition).unlink(missing_ok=True)
                raise
            return SchedulerInspection(definition.task_id, SchedulerState.INSTALLED_DISABLED, definition.sha256)
        if selected is SchedulerAction.INSPECT:
            return self._inspect(definition)
        if owner is None:
            inspection = self._inspect(definition)
            if inspection.state is SchedulerState.ABSENT and selected in {SchedulerAction.DISABLE, SchedulerAction.REMOVE}:
                return inspection
            raise ValidationError("macOS acceptance task is not owned")
        if selected is SchedulerAction.ENABLE:
            self._require_success(
                self.executor.run(("launchctl", "enable", self._service(definition)), _TIMEOUT),
                "enable",
            )
            return SchedulerInspection(definition.task_id, SchedulerState.ENABLED, owner)
        if selected is SchedulerAction.DISABLE:
            self._require_success(
                self.executor.run(("launchctl", "disable", self._service(definition)), _TIMEOUT),
                "disable",
            )
            return SchedulerInspection(definition.task_id, SchedulerState.INSTALLED_DISABLED, owner)
        if selected is SchedulerAction.REMOVE:
            self._require_success(
                self.executor.run(
                    ("launchctl", "bootout", self._domain(), str(self._plist_path(definition))),
                    _TIMEOUT,
                ),
                "bootout",
            )
            self._plist_path(definition).unlink(missing_ok=True)
            self._ownership_path(definition).unlink(missing_ok=True)
            return SchedulerInspection(definition.task_id, SchedulerState.ABSENT, None)
        raise ValidationError("macOS scheduler action is invalid")

    def trigger(self, definition: SchedulerDefinition) -> SchedulerInspection:
        self._validate(definition)
        if self._owner_hash(definition) is None:
            raise ValidationError("macOS acceptance task is not owned")
        inspection = self._inspect(definition)
        if (
            inspection.state is not SchedulerState.ENABLED
            or inspection.definition_sha256 != definition.sha256
        ):
            raise ValidationError("macOS acceptance task is not enabled and hash-owned")
        self._require_success(
            self.executor.run(("launchctl", "kickstart", self._service(definition)), _TIMEOUT),
            "kickstart",
        )
        return inspection
