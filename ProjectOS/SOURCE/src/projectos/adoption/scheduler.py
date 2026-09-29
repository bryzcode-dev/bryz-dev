from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath
from typing import Protocol, runtime_checkable

from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.errors import ValidationError


SCHEDULE_INTERVAL_SECONDS = 7200
EXECUTION_LIMIT_SECONDS = 1800


class SchedulerAction(StrEnum):
    INSTALL = "install"
    ENABLE = "enable"
    INSPECT = "inspect"
    DISABLE = "disable"
    REMOVE = "remove"


class SchedulerState(StrEnum):
    ABSENT = "absent"
    INSTALLED_DISABLED = "installed-disabled"
    ENABLED = "enabled"


@dataclass(frozen=True)
class SchedulerDefinition:
    host_family: HostFamily
    scheduler_kind: SchedulerKind
    task_id: str
    interval_seconds: int
    execution_limit_seconds: int
    enabled: bool
    content: bytes
    sha256: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class SchedulerInspection:
    task_id: str
    state: SchedulerState
    definition_sha256: str | None


@runtime_checkable
class SchedulerRunner(Protocol):
    def perform(
        self, action: SchedulerAction, definition: SchedulerDefinition
    ) -> SchedulerInspection: ...


@runtime_checkable
class SchedulerAdapter(Protocol):
    def render(
        self, profile: MachineProfile, profile_path: PurePath
    ) -> SchedulerDefinition: ...

    def verify(
        self,
        definition: SchedulerDefinition,
        profile: MachineProfile,
        profile_path: PurePath,
    ) -> None: ...

    def install(
        self, definition: SchedulerDefinition, runner: SchedulerRunner
    ) -> SchedulerInspection: ...

    def enable(
        self, definition: SchedulerDefinition, runner: SchedulerRunner
    ) -> SchedulerInspection: ...

    def inspect(
        self, definition: SchedulerDefinition, runner: SchedulerRunner
    ) -> SchedulerInspection: ...

    def disable(
        self, definition: SchedulerDefinition, runner: SchedulerRunner
    ) -> SchedulerInspection: ...

    def remove(
        self, definition: SchedulerDefinition, runner: SchedulerRunner
    ) -> SchedulerInspection: ...


class RunnerDelegatingAdapter:
    def install(self, definition, runner):
        return runner.perform(SchedulerAction.INSTALL, definition)

    def enable(self, definition, runner):
        return runner.perform(SchedulerAction.ENABLE, definition)

    def inspect(self, definition, runner):
        return runner.perform(SchedulerAction.INSPECT, definition)

    def disable(self, definition, runner):
        return runner.perform(SchedulerAction.DISABLE, definition)

    def remove(self, definition, runner):
        return runner.perform(SchedulerAction.REMOVE, definition)

    @staticmethod
    def _definition(
        profile: MachineProfile,
        content: bytes,
        argv: tuple[str, ...],
    ) -> SchedulerDefinition:
        return SchedulerDefinition(
            profile.host_family,
            profile.scheduler_kind,
            profile.scheduler_task_id,
            SCHEDULE_INTERVAL_SECONDS,
            EXECUTION_LIMIT_SECONDS,
            False,
            content,
            hashlib.sha256(content).hexdigest(),
            argv,
        )

    def _verify_exact(self, actual, profile, profile_path):
        expected = self.render(profile, profile_path)
        if actual != expected:
            raise ValidationError("scheduler definition is not canonical")


def adapter_for(profile: MachineProfile) -> SchedulerAdapter:
    if (
        profile.host_family is HostFamily.MACOS
        and profile.scheduler_kind is SchedulerKind.LAUNCHD
    ):
        from projectos.adoption.scheduler_macos import LaunchdSchedulerAdapter

        return LaunchdSchedulerAdapter()
    if (
        profile.host_family is HostFamily.WINDOWS
        and profile.scheduler_kind is SchedulerKind.WINDOWS_TASK_SCHEDULER
    ):
        from projectos.adoption.scheduler_windows import WindowsTaskSchedulerAdapter

        return WindowsTaskSchedulerAdapter()
    raise ValidationError("scheduler adapter does not match machine profile")
