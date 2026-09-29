from __future__ import annotations

import hashlib
import json
import os
import tempfile
import xml.etree.ElementTree as ET
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
_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


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


def _xml_tree(content: bytes | str) -> ET.Element:
    try:
        return ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValidationError("Windows native output is invalid") from exc


def _semantic(element: ET.Element) -> tuple[object, ...]:
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        (element.text or "").strip(),
        tuple(_semantic(child) for child in element),
    )


class WindowsNativeSchedulerRunner:
    def __init__(
        self,
        runtime_root: Path,
        executor: NativeProcessExecutor,
        *,
        elevated: bool = False,
    ) -> None:
        self.runtime_root = Path(runtime_root).expanduser().resolve(strict=False)
        self.executor = executor
        self.elevated = elevated
        self.native_root = self.runtime_root / "native/windows"
        self.xml_path = self.native_root / "projectos-acceptance.xml"
        self.ownership_path = self.native_root / "projectos-acceptance.ownership.json"

    def planned_actions(self, definition: SchedulerDefinition) -> tuple[tuple[str, ...], ...]:
        self._validate(definition)
        task = definition.task_id
        return (
            ("schtasks.exe", "/Query", "/TN", task, "/XML"),
            ("schtasks.exe", "/Create", "/TN", task, "/XML", str(self.xml_path)),
            ("schtasks.exe", "/Change", "/TN", task, "/ENABLE"),
            ("schtasks.exe", "/Run", "/TN", task),
            ("schtasks.exe", "/Query", "/TN", task, "/XML"),
            ("schtasks.exe", "/Change", "/TN", task, "/DISABLE"),
            ("schtasks.exe", "/Delete", "/TN", task, "/F"),
        )

    def _validate(self, definition: SchedulerDefinition) -> None:
        if self.elevated:
            raise ValidationError("Windows acceptance rejects an elevated session")
        if definition.host_family is not HostFamily.WINDOWS:
            raise ValidationError("Windows runner requires a Windows definition")
        if definition.task_id != ACCEPTANCE_TASKS["windows"]:
            raise ValidationError("Windows runner requires the dedicated acceptance task")
        if definition.enabled:
            raise ValidationError("acceptance scheduler definition must be disabled")
        if hashlib.sha256(definition.content).hexdigest() != definition.sha256:
            raise ValidationError("scheduler definition hash is invalid")
        root = _xml_tree(definition.content)
        if (
            root.findtext(".//t:LogonType", namespaces=_NS) != "InteractiveToken"
            or root.findtext(".//t:RunLevel", namespaces=_NS) != "LeastPrivilege"
            or root.findtext(".//t:MultipleInstancesPolicy", namespaces=_NS) != "IgnoreNew"
            or root.findtext(".//t:Settings/t:Enabled", namespaces=_NS) != "false"
        ):
            raise ValidationError("Windows scheduler definition is not canonical")
        if self.runtime_root.is_symlink() or self.native_root.is_symlink():
            raise ValidationError("Windows native state cannot use a symlink")

    @staticmethod
    def _require_success(result, action: str) -> None:
        if result.timed_out or result.returncode != 0:
            raise ValidationError(f"Windows native {action} failed")

    @staticmethod
    def _is_absent(result) -> bool:
        return (
            not result.timed_out
            and result.returncode == 1
            and result.stdout == ""
            and result.stderr.strip() == "ERROR: The system cannot find the file specified."
        )

    def _owner_hash(self, definition: SchedulerDefinition) -> str | None:
        if not self.ownership_path.exists():
            return None
        if self.ownership_path.is_symlink():
            raise ValidationError("Windows ownership record cannot be a symlink")
        try:
            content = self.ownership_path.read_bytes()
            value = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("Windows ownership record is invalid") from exc
        expected = {
            "definition_sha256": definition.sha256,
            "format": "projectos-windows-native-owner-v1",
            "task_id": definition.task_id,
        }
        if value != expected or content != _canonical(expected):
            raise ValidationError("Windows owned definition hash does not match")
        return definition.sha256

    def _write_owned_definition(self, definition: SchedulerDefinition) -> None:
        self._validate(definition)
        _atomic_write(self.xml_path, definition.content)
        _atomic_write(
            self.ownership_path,
            _canonical({
                "definition_sha256": definition.sha256,
                "format": "projectos-windows-native-owner-v1",
                "task_id": definition.task_id,
            }),
        )

    def _inspect(self, definition: SchedulerDefinition) -> SchedulerInspection:
        result = self.executor.run(
            ("schtasks.exe", "/Query", "/TN", definition.task_id, "/XML"), _TIMEOUT
        )
        if self._is_absent(result):
            return SchedulerInspection(definition.task_id, SchedulerState.ABSENT, None)
        if result.timed_out or result.returncode != 0 or not result.stdout.strip() or result.stderr:
            raise ValidationError("Windows native output is invalid")
        actual = _xml_tree(result.stdout)
        expected = _xml_tree(definition.content)
        actual_enabled = actual.find(".//t:Settings/t:Enabled", namespaces=_NS)
        expected_enabled = expected.find(".//t:Settings/t:Enabled", namespaces=_NS)
        if actual_enabled is None or expected_enabled is None or actual_enabled.text not in {"true", "false"}:
            raise ValidationError("Windows native output is invalid")
        state = SchedulerState.ENABLED if actual_enabled.text == "true" else SchedulerState.INSTALLED_DISABLED
        actual_enabled.text = "false"
        expected_enabled.text = "false"
        if _semantic(actual) != _semantic(expected):
            raise ValidationError("Windows native output is invalid")
        return SchedulerInspection(definition.task_id, state, self._owner_hash(definition))

    def perform(
        self, action: SchedulerAction, definition: SchedulerDefinition
    ) -> SchedulerInspection:
        selected = SchedulerAction(action)
        self._validate(definition)
        owner = self._owner_hash(definition)
        if selected is SchedulerAction.INSTALL:
            if owner is not None:
                return SchedulerInspection(definition.task_id, SchedulerState.INSTALLED_DISABLED, owner)
            existing = self.executor.run(
                ("schtasks.exe", "/Query", "/TN", definition.task_id, "/XML"), _TIMEOUT
            )
            if not self._is_absent(existing):
                raise ValidationError("Windows acceptance found an existing task")
            self._write_owned_definition(definition)
            result = self.executor.run(
                ("schtasks.exe", "/Create", "/TN", definition.task_id, "/XML", str(self.xml_path)),
                _TIMEOUT,
            )
            try:
                self._require_success(result, "create")
            except ValidationError:
                self.xml_path.unlink(missing_ok=True)
                self.ownership_path.unlink(missing_ok=True)
                raise
            return SchedulerInspection(definition.task_id, SchedulerState.INSTALLED_DISABLED, definition.sha256)
        if selected is SchedulerAction.INSPECT:
            return self._inspect(definition)
        if owner is None:
            inspection = self._inspect(definition)
            if inspection.state is SchedulerState.ABSENT and selected in {SchedulerAction.DISABLE, SchedulerAction.REMOVE}:
                return inspection
            raise ValidationError("Windows acceptance task is not owned")
        if selected is SchedulerAction.ENABLE:
            self._require_success(
                self.executor.run(("schtasks.exe", "/Change", "/TN", definition.task_id, "/ENABLE"), _TIMEOUT),
                "enable",
            )
            return SchedulerInspection(definition.task_id, SchedulerState.ENABLED, owner)
        if selected is SchedulerAction.DISABLE:
            self._require_success(
                self.executor.run(("schtasks.exe", "/Change", "/TN", definition.task_id, "/DISABLE"), _TIMEOUT),
                "disable",
            )
            return SchedulerInspection(definition.task_id, SchedulerState.INSTALLED_DISABLED, owner)
        if selected is SchedulerAction.REMOVE:
            self._require_success(
                self.executor.run(("schtasks.exe", "/Delete", "/TN", definition.task_id, "/F"), _TIMEOUT),
                "delete",
            )
            self.xml_path.unlink(missing_ok=True)
            self.ownership_path.unlink(missing_ok=True)
            return SchedulerInspection(definition.task_id, SchedulerState.ABSENT, None)
        raise ValidationError("Windows scheduler action is invalid")

    def trigger(self, definition: SchedulerDefinition) -> SchedulerInspection:
        self._validate(definition)
        if self._owner_hash(definition) is None:
            raise ValidationError("Windows acceptance task is not owned")
        inspection = self._inspect(definition)
        if (
            inspection.state is not SchedulerState.ENABLED
            or inspection.definition_sha256 != definition.sha256
        ):
            raise ValidationError("Windows acceptance task is not enabled and hash-owned")
        self._require_success(
            self.executor.run(("schtasks.exe", "/Run", "/TN", definition.task_id), _TIMEOUT),
            "run",
        )
        return inspection
