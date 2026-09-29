from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from pathlib import PureWindowsPath

from tests.helpers import TemporaryDirectoryMixin

from projectos.acceptance.native import NativeProcessResult, RecordingProcessExecutor
from projectos.acceptance.native_windows import WindowsNativeSchedulerRunner
from projectos.acceptance.profile import acceptance_machine_profile
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.adoption.scheduler import SchedulerAction, SchedulerState, adapter_for
from projectos.errors import ValidationError


class WindowsNativeSchedulerTests(TemporaryDirectoryMixin, unittest.TestCase):
    def definition(self):
        contextos = PureWindowsPath(r"Z:\Fixture")
        runtime = PureWindowsPath(r"C:\Acceptance\Runtime")
        python = PureWindowsPath(r"C:\Acceptance\venv\python.exe")
        production = MachineProfile(
            1, "99999999-9999-9999-9999-999999999999", "fixture", HostFamily.WINDOWS,
            "0.1.0", "3.0.1", 1, contextos, contextos / "context-os/extensions",
            contextos / "skills", runtime, runtime / "projectos.db", runtime / "projectos.toml",
            runtime / "projectos.sync.lock", runtime / "logs", runtime / "staging", python,
            (str(python), "-m", "projectos.cli"), SchedulerKind.WINDOWS_TASK_SCHEDULER,
            r"ContextOS\ProjectOS\Sync", "ADOPTED", "a" * 64,
        )
        profile = acceptance_machine_profile(production)
        return adapter_for(profile).render(profile, runtime / "adoption/machine-profile.json")

    def runner(self, responses=(), *, elevated: bool = False):
        executor = RecordingProcessExecutor(responses)
        return WindowsNativeSchedulerRunner(self.temp_path / "runtime", executor, elevated=elevated), executor

    def absent(self):
        return NativeProcessResult(1, "", "ERROR: The system cannot find the file specified.")

    def test_windows_runner_uses_only_fixed_schtasks_argument_arrays(self) -> None:
        definition = self.definition()
        runner, _ = self.runner()
        for argv in runner.planned_actions(definition):
            self.assertEqual("schtasks.exe", argv[0])
            self.assertIn("/TN", argv)
            self.assertIn(definition.task_id, argv)
            self.assertNotIn("/RU", argv)
            self.assertNotIn("/RP", argv)

    def test_windows_runner_imports_verified_xml_with_interactive_least_privilege_and_no_password(self) -> None:
        definition = self.definition()
        lowered = definition.content.lower()
        self.assertIn(b"interactivetoken", lowered)
        self.assertIn(b"leastprivilege", lowered)
        self.assertNotIn(b"password", lowered)
        runner, _ = self.runner()
        create = runner.planned_actions(definition)[1]
        self.assertEqual(("schtasks.exe", "/Create", "/TN", definition.task_id, "/XML"), create[:5])
        self.assertNotIn("/F", create)

    def test_windows_runner_create_disabled_enable_trigger_query_disable_delete(self) -> None:
        definition = self.definition()
        enabled = definition.content.replace(b"<Enabled>false</Enabled>", b"<Enabled>true</Enabled>", 1)
        runner, executor = self.runner((
            self.absent(), NativeProcessResult(0, "SUCCESS", ""),
            NativeProcessResult(0, "SUCCESS", ""), NativeProcessResult(0, enabled.decode(), ""),
            NativeProcessResult(0, "SUCCESS", ""), NativeProcessResult(0, enabled.decode(), ""),
            NativeProcessResult(0, "SUCCESS", ""), NativeProcessResult(0, "SUCCESS", ""),
        ))
        self.assertEqual(SchedulerState.INSTALLED_DISABLED, runner.perform(SchedulerAction.INSTALL, definition).state)
        self.assertEqual(SchedulerState.ENABLED, runner.perform(SchedulerAction.ENABLE, definition).state)
        self.assertEqual(SchedulerState.ENABLED, runner.trigger(definition).state)
        self.assertEqual(SchedulerState.ENABLED, runner.perform(SchedulerAction.INSPECT, definition).state)
        self.assertEqual(SchedulerState.INSTALLED_DISABLED, runner.perform(SchedulerAction.DISABLE, definition).state)
        self.assertEqual(SchedulerState.ABSENT, runner.perform(SchedulerAction.REMOVE, definition).state)
        self.assertEqual(
            ["/Query", "/Create", "/Change", "/Query", "/Run", "/Query", "/Change", "/Delete"],
            [argv[1] for argv in executor.history],
        )

    def test_windows_trigger_is_one_fixed_schtasks_run_array(self) -> None:
        definition = self.definition()
        enabled = definition.content.replace(b"<Enabled>false</Enabled>", b"<Enabled>true</Enabled>", 1)
        runner, executor = self.runner((
            NativeProcessResult(0, enabled.decode(), ""),
            NativeProcessResult(0, "SUCCESS", ""),
        ))
        runner._write_owned_definition(definition)
        result = runner.trigger(definition)
        self.assertEqual(SchedulerState.ENABLED, result.state)
        self.assertEqual(("schtasks.exe", "/Run", "/TN", definition.task_id), executor.history[-1])

        runner, executor = self.runner((NativeProcessResult(0, definition.content.decode(), ""),))
        runner._write_owned_definition(definition)
        with self.assertRaisesRegex(ValidationError, "enabled"):
            runner.trigger(definition)
        self.assertFalse(any(argv[1] == "/Run" for argv in executor.history))

    def test_windows_runner_refuses_elevation_production_task_existing_foreign_task_and_changed_hash(self) -> None:
        definition = self.definition()
        runner, _ = self.runner(elevated=True)
        with self.assertRaisesRegex(ValidationError, "elevated"):
            runner.perform(SchedulerAction.INSTALL, definition)
        runner, _ = self.runner()
        with self.assertRaisesRegex(ValidationError, "acceptance task"):
            runner.perform(SchedulerAction.INSTALL, replace(definition, task_id=r"ContextOS\ProjectOS\Sync"))
        runner, _ = self.runner((NativeProcessResult(0, definition.content.decode(), ""),))
        with self.assertRaisesRegex(ValidationError, "existing"):
            runner.perform(SchedulerAction.INSTALL, definition)
        runner, _ = self.runner((self.absent(), NativeProcessResult(0, "SUCCESS", "")))
        runner.perform(SchedulerAction.INSTALL, definition)
        changed_content = definition.content + b" "
        changed = replace(definition, content=changed_content, sha256=hashlib.sha256(changed_content).hexdigest())
        with self.assertRaisesRegex(ValidationError, "definition hash"):
            runner.perform(SchedulerAction.REMOVE, changed)

    def test_windows_runner_requires_no_powershell_com_developer_mode_or_symlink(self) -> None:
        definition = self.definition()
        runner, _ = self.runner()
        searchable = " ".join(" ".join(argv) for argv in runner.planned_actions(definition)).lower()
        for forbidden in ("powershell", "comobject", "developer mode", "mklink", "password"):
            self.assertNotIn(forbidden, searchable)

    def test_windows_runner_fails_closed_on_localized_truncated_or_contradictory_output(self) -> None:
        definition = self.definition()
        cases = ("", "tarea habilitada", definition.content.decode() + definition.content.decode())
        for output in cases:
            with self.subTest(output=output[:20]):
                runner, _ = self.runner((NativeProcessResult(0, output, ""),))
                runner._write_owned_definition(definition)
                with self.assertRaisesRegex(ValidationError, "output"):
                    runner.perform(SchedulerAction.INSPECT, definition)


if __name__ == "__main__":
    unittest.main()
