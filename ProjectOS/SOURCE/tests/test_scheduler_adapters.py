from __future__ import annotations

import hashlib
import plistlib
import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import PurePosixPath, PureWindowsPath

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.adoption.scheduler import (
    EXECUTION_LIMIT_SECONDS,
    SCHEDULE_INTERVAL_SECONDS,
    SchedulerAction,
    SchedulerInspection,
    SchedulerState,
    adapter_for,
)
from projectos.errors import ValidationError
from projectos.runtime import RuntimeTrigger, runtime_sync_argv


class RecordingRunner:
    def __init__(self) -> None:
        self.actions: list[SchedulerAction] = []
        self.state = SchedulerState.ABSENT

    def perform(self, action, definition):
        self.actions.append(action)
        transitions = {
            SchedulerAction.INSTALL: SchedulerState.INSTALLED_DISABLED,
            SchedulerAction.ENABLE: SchedulerState.ENABLED,
            SchedulerAction.INSPECT: self.state,
            SchedulerAction.DISABLE: SchedulerState.INSTALLED_DISABLED,
            SchedulerAction.REMOVE: SchedulerState.ABSENT,
        }
        self.state = transitions[action]
        return SchedulerInspection(definition.task_id, self.state, definition.sha256)


class SchedulerAdapterTests(TemporaryDirectoryMixin, unittest.TestCase):
    def profile(self, family: HostFamily, *, special: bool = False) -> MachineProfile:
        if family is HostFamily.WINDOWS:
            path_type = PureWindowsPath
            contextos = path_type(r"Z:\ContextOS\shared")
            runtime = path_type(r"C:\Users\Example\AppData\Local\ProjectOS & Data")
            python = path_type(r"C:\Python311\python.exe")
            scheduler = SchedulerKind.WINDOWS_TASK_SCHEDULER
            task_id = r"ContextOS\ProjectOS\Sync"
        else:
            path_type = PurePosixPath
            contextos = path_type("/Volumes/ContextOS/shared")
            runtime = path_type("/Users/Example/Library/Application Support/ProjectOS <Local>" if special else "/Users/Example/Library/Application Support/ProjectOS")
            python = path_type("/opt/projectos/bin/python3")
            scheduler = SchedulerKind.LAUNCHD
            task_id = "com.contextos.projectos.sync"
        return MachineProfile(
            1,
            "58b9478e-07be-4b08-a901-45e4110c8882",
            "fixture-machine",
            family,
            "0.1.0",
            "3.0.1",
            1,
            contextos,
            contextos / "context-os/extensions",
            contextos / "skills",
            runtime,
            runtime / "projectos.db",
            runtime / "projectos.toml",
            runtime / "projectos.sync.lock",
            runtime / "logs",
            runtime / "staging",
            python,
            (str(python), "-m", "projectos.cli"),
            scheduler,
            task_id,
            "ADOPTED",
            "a" * 64,
        )

    def test_launchd_render_is_canonical_disabled_two_hour_and_local(self) -> None:
        profile = self.profile(HostFamily.MACOS)
        profile_path = PurePosixPath(profile.runtime_root) / "adoption/machine-profile.json"
        adapter = adapter_for(profile)

        first = adapter.render(profile, profile_path)
        second = adapter.render(profile, profile_path)
        parsed = plistlib.loads(first.content)

        self.assertEqual(first, second)
        self.assertEqual(SCHEDULE_INTERVAL_SECONDS, parsed["StartInterval"])
        self.assertEqual(EXECUTION_LIMIT_SECONDS, parsed["TimeOut"])
        self.assertTrue(parsed["Disabled"])
        self.assertFalse(first.enabled)
        self.assertEqual(str(profile.runtime_root), parsed["WorkingDirectory"])
        self.assertEqual(hashlib.sha256(first.content).hexdigest(), first.sha256)

    def test_windows_render_is_canonical_disabled_two_hour_interactive_and_nonoverlapping(self) -> None:
        profile = self.profile(HostFamily.WINDOWS)
        profile_path = PureWindowsPath(profile.runtime_root) / "adoption/machine-profile.json"
        definition = adapter_for(profile).render(profile, profile_path)
        root = ET.fromstring(definition.content)
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

        self.assertEqual("PT2H", root.findtext(".//t:Repetition/t:Interval", namespaces=ns))
        self.assertEqual("PT30M", root.findtext(".//t:ExecutionTimeLimit", namespaces=ns))
        self.assertEqual("InteractiveToken", root.findtext(".//t:LogonType", namespaces=ns))
        self.assertEqual("IgnoreNew", root.findtext(".//t:MultipleInstancesPolicy", namespaces=ns))
        self.assertEqual("false", root.findtext(".//t:Settings/t:Enabled", namespaces=ns))
        self.assertFalse(definition.enabled)

    def test_definitions_use_exact_common_runtime_argv_and_explicit_database(self) -> None:
        for family in (HostFamily.MACOS, HostFamily.WINDOWS):
            with self.subTest(family=family):
                profile = self.profile(family)
                path_type = PureWindowsPath if family is HostFamily.WINDOWS else PurePosixPath
                profile_path = path_type(profile.runtime_root) / "adoption/machine-profile.json"
                definition = adapter_for(profile).render(profile, profile_path)

                self.assertEqual(
                    runtime_sync_argv(profile, profile_path, RuntimeTrigger.SCHEDULER),
                    definition.argv,
                )
                self.assertIn(str(profile.database_path), definition.argv)

    def test_render_escapes_xml_metacharacters_without_shell_or_wrapper(self) -> None:
        profile = self.profile(HostFamily.WINDOWS, special=True)
        profile_path = PureWindowsPath(profile.runtime_root) / "adoption/machine-profile.json"
        definition = adapter_for(profile).render(profile, profile_path)
        root = ET.fromstring(definition.content)
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

        self.assertIn(b"&amp;", definition.content)
        self.assertEqual(str(profile.runtime_root), root.findtext(".//t:WorkingDirectory", namespaces=ns))
        lowered = definition.content.lower()
        self.assertNotIn(b"powershell", lowered)
        self.assertNotIn(b"cmd.exe", lowered)
        self.assertNotIn(b"shell", lowered)

    def test_verify_rejects_changed_hash_interval_limit_task_id_or_enabled_state(self) -> None:
        profile = self.profile(HostFamily.MACOS)
        profile_path = PurePosixPath(profile.runtime_root) / "adoption/machine-profile.json"
        adapter = adapter_for(profile)
        definition = adapter.render(profile, profile_path)
        adapter.verify(definition, profile, profile_path)

        changes = (
            {"sha256": "0" * 64},
            {"interval_seconds": 60},
            {"execution_limit_seconds": 60},
            {"task_id": "other"},
            {"enabled": True},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                adapter.verify(replace(definition, **change), profile, profile_path)

    def test_adapter_lifecycle_uses_runner_actions_in_order(self) -> None:
        profile = self.profile(HostFamily.MACOS)
        profile_path = PurePosixPath(profile.runtime_root) / "adoption/machine-profile.json"
        adapter = adapter_for(profile)
        definition = adapter.render(profile, profile_path)
        runner = RecordingRunner()

        adapter.install(definition, runner)
        adapter.enable(definition, runner)
        inspection = adapter.inspect(definition, runner)
        adapter.disable(definition, runner)
        adapter.remove(definition, runner)

        self.assertEqual(SchedulerState.ENABLED, inspection.state)
        self.assertEqual(
            [
                SchedulerAction.INSTALL,
                SchedulerAction.ENABLE,
                SchedulerAction.INSPECT,
                SchedulerAction.DISABLE,
                SchedulerAction.REMOVE,
            ],
            runner.actions,
        )

    def test_windows_definition_requires_no_password_symlink_or_developer_mode(self) -> None:
        profile = self.profile(HostFamily.WINDOWS)
        profile_path = PureWindowsPath(profile.runtime_root) / "adoption/machine-profile.json"
        content = adapter_for(profile).render(profile, profile_path).content.lower()

        for prohibited in (b"password", b"symlink", b"developer mode", b"s4u"):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, content)


if __name__ == "__main__":
    unittest.main()
