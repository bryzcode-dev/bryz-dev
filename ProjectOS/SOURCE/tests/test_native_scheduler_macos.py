from __future__ import annotations

import hashlib
import plistlib
import unittest
from dataclasses import replace
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from tests.helpers import TemporaryDirectoryMixin

from projectos.acceptance.model import ACCEPTANCE_TASKS
from projectos.acceptance.native import (
    NativeProcessResult,
    RecordingProcessExecutor,
    SubprocessNativeExecutor,
)
from projectos.acceptance.native_macos import MacOSNativeSchedulerRunner
from projectos.acceptance.profile import acceptance_machine_profile
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.adoption.scheduler import SchedulerAction, SchedulerState, adapter_for
from projectos.errors import ValidationError


class MacOSNativeSchedulerTests(TemporaryDirectoryMixin, unittest.TestCase):
    def definition(self):
        runtime = PurePosixPath(str((self.temp_path / "runtime").resolve()))
        contextos = PurePosixPath(str((self.temp_path / "fixture").resolve()))
        python = PurePosixPath("/usr/bin/python3")
        production = MachineProfile(
            1, "99999999-9999-9999-9999-999999999999", "fixture", HostFamily.MACOS,
            "0.1.0", "3.0.1", 1, contextos, contextos / "context-os/extensions",
            contextos / "skills", runtime, runtime / "projectos.db", runtime / "projectos.toml",
            runtime / "projectos.sync.lock", runtime / "logs", runtime / "staging", python,
            (str(python), "-m", "projectos.cli"), SchedulerKind.LAUNCHD,
            "com.contextos.projectos.sync", "ADOPTED", "a" * 64,
        )
        profile = acceptance_machine_profile(production)
        return adapter_for(profile).render(profile, runtime / "adoption/machine-profile.json")

    def test_subprocess_executor_uses_argument_array_shell_false_bounded_timeout_and_redacts_output(self) -> None:
        completed = type("Completed", (), {
            "returncode": 0,
            "stdout": "ok\n" + "x" * 5000,
            "stderr": "access_token=abcdefghijklmnopqrstuvwx",
        })()
        with patch("projectos.acceptance.native.subprocess.run", return_value=completed) as run:
            result = SubprocessNativeExecutor().run(("launchctl", "print", "gui/501"), 3)
        self.assertEqual(("launchctl", "print", "gui/501"), tuple(run.call_args.args[0]))
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(3, run.call_args.kwargs["timeout"])
        self.assertLessEqual(len(result.stdout), 2048)
        self.assertIn("[REDACTED]", result.stderr)

    def test_macos_runner_uses_only_fixed_per_user_launchctl_argument_arrays(self) -> None:
        definition = self.definition()
        runner = MacOSNativeSchedulerRunner(self.temp_path / "runtime", 501, RecordingProcessExecutor())
        actions = runner.planned_actions(definition)
        self.assertTrue(actions)
        for argv in actions:
            self.assertEqual("launchctl", argv[0])
            self.assertNotIn("sudo", argv)
            self.assertTrue(any("gui/501" in item for item in argv[1:]))

    def test_macos_runner_never_uses_shell_sudo_or_system_launch_locations(self) -> None:
        definition = self.definition()
        searchable = " ".join(" ".join(argv) for argv in MacOSNativeSchedulerRunner(
            self.temp_path / "runtime", 501, RecordingProcessExecutor()
        ).planned_actions(definition))
        for forbidden in ("sudo", "/Library/LaunchDaemons", "/Library/LaunchAgents", "sh -c"):
            self.assertNotIn(forbidden, searchable)

    def test_macos_runner_stages_disabled_then_enable_trigger_disable_bootout(self) -> None:
        definition = self.definition()
        task = definition.task_id
        executor = RecordingProcessExecutor(
            (
                NativeProcessResult(113, "", "Could not find service"),
                NativeProcessResult(0, "", ""),
                NativeProcessResult(0, "", ""),
                NativeProcessResult(0, "service = present", ""),
                NativeProcessResult(0, f'"{task}" => false', ""),
                NativeProcessResult(0, "", ""),
                NativeProcessResult(0, "service = present", ""),
                NativeProcessResult(0, f'"{task}" => false', ""),
                NativeProcessResult(0, "", ""),
                NativeProcessResult(0, "", ""),
            )
        )
        runner = MacOSNativeSchedulerRunner(self.temp_path / "runtime", 501, executor)
        self.assertEqual(SchedulerState.INSTALLED_DISABLED, runner.perform(SchedulerAction.INSTALL, definition).state)
        self.assertEqual(SchedulerState.ENABLED, runner.perform(SchedulerAction.ENABLE, definition).state)
        self.assertEqual(SchedulerState.ENABLED, runner.trigger(definition).state)
        self.assertEqual(SchedulerState.ENABLED, runner.perform(SchedulerAction.INSPECT, definition).state)
        self.assertEqual(SchedulerState.INSTALLED_DISABLED, runner.perform(SchedulerAction.DISABLE, definition).state)
        self.assertEqual(SchedulerState.ABSENT, runner.perform(SchedulerAction.REMOVE, definition).state)
        verbs = [argv[1] for argv in executor.history]
        self.assertEqual(
            [
                "print", "bootstrap", "enable", "print", "print-disabled", "kickstart",
                "print", "print-disabled", "disable", "bootout",
            ],
            verbs,
        )
        plist_path = self.temp_path / "runtime/native/macos/com.contextos.projectos.acceptance.sync.plist"
        self.assertFalse(plist_path.exists())

    def test_macos_trigger_is_one_fixed_kickstart_array(self) -> None:
        definition = self.definition()
        task = definition.task_id
        executor = RecordingProcessExecutor((
            NativeProcessResult(0, "service = present", ""),
            NativeProcessResult(0, f'"{task}" => true', ""),
        ))
        runner = MacOSNativeSchedulerRunner(self.temp_path / "runtime", 501, executor)
        runner._write_owned_definition(definition)
        with self.assertRaisesRegex(ValidationError, "enabled"):
            runner.trigger(definition)
        self.assertFalse(any(argv[1] == "kickstart" for argv in executor.history))

        executor = RecordingProcessExecutor((
            NativeProcessResult(0, "service = present", ""),
            NativeProcessResult(0, f'"{task}" => false', ""),
            NativeProcessResult(0, "", ""),
        ))
        runner = MacOSNativeSchedulerRunner(self.temp_path / "runtime", 501, executor)
        runner._write_owned_definition(definition)
        result = runner.trigger(definition)
        self.assertEqual(SchedulerState.ENABLED, result.state)
        self.assertEqual(
            ("launchctl", "kickstart", f"gui/501/{definition.task_id}"),
            executor.history[-1],
        )

    def test_native_trigger_requires_enabled_hash_owned_acceptance_task(self) -> None:
        definition = self.definition()
        runner = MacOSNativeSchedulerRunner(
            self.temp_path / "runtime", 501,
            RecordingProcessExecutor((NativeProcessResult(113, "", "Could not find service"),)),
        )
        with self.assertRaisesRegex(ValidationError, "owned"):
            runner.trigger(definition)

    def test_macos_runner_refuses_root_production_task_existing_foreign_task_and_changed_hash(self) -> None:
        definition = self.definition()
        with self.assertRaisesRegex(ValidationError, "elevated"):
            MacOSNativeSchedulerRunner(self.temp_path / "runtime", 0, RecordingProcessExecutor(), elevated=True).perform(
                SchedulerAction.INSTALL, definition
            )
        with self.assertRaisesRegex(ValidationError, "acceptance task"):
            MacOSNativeSchedulerRunner(self.temp_path / "runtime", 501, RecordingProcessExecutor()).perform(
                SchedulerAction.INSTALL, replace(definition, task_id="com.contextos.projectos.sync")
            )
        foreign = RecordingProcessExecutor((NativeProcessResult(0, "service = present", ""),))
        with self.assertRaisesRegex(ValidationError, "existing"):
            MacOSNativeSchedulerRunner(self.temp_path / "runtime", 501, foreign).perform(SchedulerAction.INSTALL, definition)

        executor = RecordingProcessExecutor((NativeProcessResult(113, "", "Could not find service"), NativeProcessResult(0, "", "")))
        runner = MacOSNativeSchedulerRunner(self.temp_path / "runtime", 501, executor)
        runner.perform(SchedulerAction.INSTALL, definition)
        changed = replace(definition, content=definition.content + b" ", sha256=hashlib.sha256(definition.content + b" ").hexdigest())
        with self.assertRaisesRegex(ValidationError, "definition hash"):
            runner.perform(SchedulerAction.REMOVE, changed)

    def test_macos_runner_is_idempotent_only_for_owned_definition(self) -> None:
        definition = self.definition()
        executor = RecordingProcessExecutor((NativeProcessResult(113, "", "Could not find service"), NativeProcessResult(0, "", "")))
        runner = MacOSNativeSchedulerRunner(self.temp_path / "runtime", 501, executor)
        runner.perform(SchedulerAction.INSTALL, definition)
        count = len(executor.history)
        self.assertEqual(SchedulerState.INSTALLED_DISABLED, runner.perform(SchedulerAction.INSTALL, definition).state)
        self.assertEqual(count, len(executor.history))

    def test_macos_runner_fails_closed_on_localized_truncated_or_contradictory_output(self) -> None:
        definition = self.definition()
        outputs = ("", "servicio no encontrado", f'"{definition.task_id}" => true\n"{definition.task_id}" => false')
        for output in outputs:
            with self.subTest(output=output):
                executor = RecordingProcessExecutor((
                    NativeProcessResult(0, "service = present", ""),
                    NativeProcessResult(0, output, ""),
                ))
                runner = MacOSNativeSchedulerRunner(self.temp_path / "runtime", 501, executor)
                runner._write_owned_definition(definition)
                with self.assertRaisesRegex(ValidationError, "output"):
                    runner.perform(SchedulerAction.INSPECT, definition)


if __name__ == "__main__":
    unittest.main()
