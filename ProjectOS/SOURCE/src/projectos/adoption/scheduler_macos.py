from __future__ import annotations

import plistlib
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


class LaunchdSchedulerAdapter(RunnerDelegatingAdapter):
    def render(
        self, profile: MachineProfile, profile_path: PurePath
    ) -> SchedulerDefinition:
        if (
            profile.host_family is not HostFamily.MACOS
            or profile.scheduler_kind is not SchedulerKind.LAUNCHD
        ):
            raise ValidationError("launchd adapter requires a macOS profile")
        argv = runtime_sync_argv(profile, profile_path, RuntimeTrigger.SCHEDULER)
        content = plistlib.dumps(
            {
                "Disabled": True,
                "KeepAlive": False,
                "Label": profile.scheduler_task_id,
                "ProcessType": "Background",
                "ProgramArguments": list(argv),
                "RunAtLoad": False,
                "StandardErrorPath": str(profile.log_root / "projectos-sync.err.log"),
                "StandardOutPath": str(profile.log_root / "projectos-sync.out.log"),
                "StartInterval": SCHEDULE_INTERVAL_SECONDS,
                "TimeOut": EXECUTION_LIMIT_SECONDS,
                "WorkingDirectory": str(profile.runtime_root),
            },
            fmt=plistlib.FMT_XML,
            sort_keys=True,
        )
        return self._definition(profile, content, argv)

    def verify(
        self,
        definition: SchedulerDefinition,
        profile: MachineProfile,
        profile_path: PurePath,
    ) -> None:
        self._verify_exact(definition, profile, profile_path)
