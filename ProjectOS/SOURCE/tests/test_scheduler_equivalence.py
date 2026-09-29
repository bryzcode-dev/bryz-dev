from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import PurePosixPath, PureWindowsPath

from projectos.acceptance.equivalence import compare_scheduler_definitions
from projectos.acceptance.profile import acceptance_machine_profile
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.adoption.scheduler import adapter_for


class SchedulerEquivalenceTests(unittest.TestCase):
    def profile(self, family: HostFamily) -> MachineProfile:
        if family is HostFamily.WINDOWS:
            path = PureWindowsPath
            contextos = path(r"Z:\Fixture")
            runtime = path(r"C:\Acceptance\Runtime")
            python = path(r"C:\Acceptance\venv\python.exe")
            scheduler = SchedulerKind.WINDOWS_TASK_SCHEDULER
            task = r"ContextOS\ProjectOS\Sync"
        else:
            path = PurePosixPath
            contextos = path("/fixture/contextos")
            runtime = path("/acceptance/runtime")
            python = path("/acceptance/venv/bin/python3")
            scheduler = SchedulerKind.LAUNCHD
            task = "com.contextos.projectos.sync"
        return MachineProfile(
            1, "99999999-9999-9999-9999-999999999999", "fixture-machine", family,
            "0.1.0", "3.0.1", 1, contextos, contextos / "context-os/extensions",
            contextos / "skills", runtime, runtime / "projectos.db",
            runtime / "projectos.toml", runtime / "projectos.sync.lock", runtime / "logs",
            runtime / "staging", python, (str(python), "-m", "projectos.cli"), scheduler,
            task, "ADOPTED", "a" * 64,
        )

    def definitions(self, family: HostFamily):
        production = self.profile(family)
        acceptance = acceptance_machine_profile(production)
        path_type = PureWindowsPath if family is HostFamily.WINDOWS else PurePosixPath
        profile_path = path_type(production.runtime_root) / "adoption/machine-profile.json"
        return (
            adapter_for(production).render(production, profile_path),
            adapter_for(acceptance).render(acceptance, profile_path),
        )

    def test_acceptance_definition_diff_allows_only_task_id_and_entrypoint_module(self) -> None:
        for family in (HostFamily.MACOS, HostFamily.WINDOWS):
            with self.subTest(family=family):
                production, acceptance = self.definitions(family)
                comparison = compare_scheduler_definitions(production, acceptance)
                self.assertTrue(comparison.equivalent, comparison.differences)
                self.assertEqual(("entrypoint_module", "task_id"), comparison.allowed_differences)
                self.assertEqual((), comparison.differences)

    def test_equivalence_rejects_timing_path_argument_policy_or_definition_drift(self) -> None:
        production, acceptance = self.definitions(HostFamily.MACOS)
        changes = (
            {"interval_seconds": 60},
            {"execution_limit_seconds": 60},
            {"argv": (*acceptance.argv[:-1], "skill")},
            {"enabled": True},
            {"content": acceptance.content.replace(b"<false/>", b"<true/>", 1)},
        )
        for change in changes:
            with self.subTest(change=tuple(change)):
                result = compare_scheduler_definitions(production, replace(acceptance, **change))
                self.assertFalse(result.equivalent)
                self.assertTrue(result.differences)
        foreign_production = replace(production, task_id="com.example.foreign")
        self.assertFalse(
            compare_scheduler_definitions(foreign_production, acceptance).equivalent
        )


if __name__ == "__main__":
    unittest.main()
