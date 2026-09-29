from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import PurePath

from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.adoption.scheduler import (
    EXECUTION_LIMIT_SECONDS,
    SCHEDULE_INTERVAL_SECONDS,
    RunnerDelegatingAdapter,
    SchedulerDefinition,
)
from projectos.errors import ValidationError
from projectos.runtime import RuntimeTrigger, runtime_sync_argv


_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
ET.register_namespace("", _NS)


def _tag(name: str) -> str:
    return f"{{{_NS}}}{name}"


def _child(parent: ET.Element, name: str, text: str | None = None, **attributes) -> ET.Element:
    element = ET.SubElement(parent, _tag(name), attributes)
    element.text = text
    return element


def _quote(argument: str) -> str:
    if argument and not any(character in ' \t"' for character in argument):
        return argument
    result = '"'
    backslashes = 0
    for character in argument:
        if character == "\\":
            backslashes += 1
        elif character == '"':
            result += "\\" * (backslashes * 2 + 1) + '"'
            backslashes = 0
        else:
            result += "\\" * backslashes + character
            backslashes = 0
    return result + "\\" * (backslashes * 2) + '"'


class WindowsTaskSchedulerAdapter(RunnerDelegatingAdapter):
    def render(
        self, profile: MachineProfile, profile_path: PurePath
    ) -> SchedulerDefinition:
        if (
            profile.host_family is not HostFamily.WINDOWS
            or profile.scheduler_kind is not SchedulerKind.WINDOWS_TASK_SCHEDULER
        ):
            raise ValidationError("Task Scheduler adapter requires a Windows profile")
        argv = runtime_sync_argv(profile, profile_path, RuntimeTrigger.SCHEDULER)
        root = ET.Element(_tag("Task"), {"version": "1.4"})
        registration = _child(root, "RegistrationInfo")
        _child(registration, "Description", "ProjectOS configured synchronization")
        triggers = _child(root, "Triggers")
        calendar = _child(triggers, "CalendarTrigger")
        _child(calendar, "StartBoundary", "2000-01-01T00:00:00")
        _child(calendar, "Enabled", "true")
        repetition = _child(calendar, "Repetition")
        _child(repetition, "Interval", f"PT{SCHEDULE_INTERVAL_SECONDS // 3600}H")
        _child(repetition, "StopAtDurationEnd", "false")
        schedule = _child(calendar, "ScheduleByDay")
        _child(schedule, "DaysInterval", "1")
        principals = _child(root, "Principals")
        principal = _child(principals, "Principal", id="Author")
        _child(principal, "LogonType", "InteractiveToken")
        _child(principal, "RunLevel", "LeastPrivilege")
        settings = _child(root, "Settings")
        _child(settings, "MultipleInstancesPolicy", "IgnoreNew")
        _child(settings, "DisallowStartIfOnBatteries", "false")
        _child(settings, "StopIfGoingOnBatteries", "false")
        _child(settings, "StartWhenAvailable", "true")
        _child(settings, "ExecutionTimeLimit", f"PT{EXECUTION_LIMIT_SECONDS // 60}M")
        _child(settings, "Enabled", "false")
        actions = _child(root, "Actions", Context="Author")
        execute = _child(actions, "Exec")
        _child(execute, "Command", argv[0])
        _child(execute, "Arguments", " ".join(_quote(item) for item in argv[1:]))
        _child(execute, "WorkingDirectory", str(profile.runtime_root))
        content = ET.tostring(
            root, encoding="utf-8", xml_declaration=True, short_empty_elements=False
        )
        return self._definition(profile, content, argv)

    def verify(
        self,
        definition: SchedulerDefinition,
        profile: MachineProfile,
        profile_path: PurePath,
    ) -> None:
        self._verify_exact(definition, profile, profile_path)
