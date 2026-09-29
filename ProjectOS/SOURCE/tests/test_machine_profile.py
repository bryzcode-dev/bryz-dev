from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path, PurePosixPath, PureWindowsPath

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.contextos import ContextOSExtensionContract, ContextOSInstallation
from projectos.adoption.host import HostFamily, HostIdentity
from projectos.adoption.paths import PlatformPaths, resolve_platform_paths
from projectos.adoption.profile import (
    SchedulerKind,
    machine_profile_mapping,
    plan_machine_profile,
)


class MachineProfileTests(TemporaryDirectoryMixin, unittest.TestCase):
    def installation(
        self,
        family: HostFamily,
        *,
        machine_id: str | None = "workstation-01",
        contract_version: int = 1,
        supported_hosts: tuple[HostFamily, ...] | None = None,
    ) -> ContextOSInstallation:
        if family is HostFamily.WINDOWS:
            root = PureWindowsPath(r"Z:\ContextOS\shared")
        else:
            root = PurePosixPath(str((self.temp_path / "contextos").resolve()))
        contract = ContextOSExtensionContract(
            contract_version,
            "3.0.1",
            str(PureWindowsPath("context-os/extensions") if family is HostFamily.WINDOWS else PurePosixPath("context-os/extensions")),
            "skills",
            "%LOCALAPPDATA%\\ClaudeContextOS\\home"
            if family is HostFamily.WINDOWS
            else "~/Library/Application Support/ClaudeContextOS/home",
            supported_hosts or (HostFamily.MACOS, HostFamily.WINDOWS),
        )
        return ContextOSInstallation(
            root,  # type: ignore[arg-type]
            root / "context-os/config/context-os.json",  # type: ignore[arg-type]
            root / "context-os-machine.json",  # type: ignore[arg-type]
            root / "context-os/config/extension-contract.json",  # type: ignore[arg-type]
            contract,
            machine_id,
        )

    def test_macos_profile_contains_only_target_host_values(self) -> None:
        paths = resolve_platform_paths(
            HostFamily.MACOS, {}, PurePosixPath("/Users/Example")
        )

        plan = plan_machine_profile(
            self.installation(HostFamily.MACOS),
            HostIdentity(HostFamily.MACOS, "workstation-01"),
            paths,
            "/opt/projectos/bin/python3",
            "0.1.0",
            SchedulerKind.LAUNCHD,
            (str(self.temp_path / "contextos"),),
        )

        self.assertTrue(plan.ready, plan.errors)
        self.assertIsNotNone(plan.profile)
        self.assertEqual("macos", plan.profile.host_family.value)
        self.assertEqual("launchd", plan.profile.scheduler_kind.value)
        self.assertEqual("com.contextos.projectos.sync", plan.profile.scheduler_task_id)
        self.assertNotIn("windows", str(machine_profile_mapping(plan.profile)).lower())

    def test_windows_profile_contains_localappdata_and_task_scheduler(self) -> None:
        paths = resolve_platform_paths(
            HostFamily.WINDOWS,
            {"LOCALAPPDATA": r"C:\Users\Example\AppData\Local"},
            PureWindowsPath(r"C:\Users\Example"),
        )

        plan = plan_machine_profile(
            self.installation(HostFamily.WINDOWS, machine_id="workstation-02"),
            HostIdentity(HostFamily.WINDOWS, "workstation-02"),
            paths,
            r"C:\Python311\python.exe",
            "0.1.0",
            SchedulerKind.WINDOWS_TASK_SCHEDULER,
            (r"Z:\ContextOS\shared",),
        )

        self.assertTrue(plan.ready, plan.errors)
        self.assertEqual("windows", plan.profile.host_family.value)
        self.assertEqual("windows-task-scheduler", plan.profile.scheduler_kind.value)
        self.assertEqual(r"ContextOS\ProjectOS\Sync", plan.profile.scheduler_task_id)
        self.assertIn(r"C:\Users\Example\AppData\Local\ProjectOS", str(plan.profile.runtime_root))

    def test_profile_rejects_scheduler_for_other_host(self) -> None:
        paths = resolve_platform_paths(
            HostFamily.MACOS, {}, PurePosixPath("/Users/Example")
        )

        plan = plan_machine_profile(
            self.installation(HostFamily.MACOS),
            HostIdentity(HostFamily.MACOS, "workstation-01"),
            paths,
            "/usr/bin/python3",
            "0.1.0",
            SchedulerKind.WINDOWS_TASK_SCHEDULER,
        )

        self.assertFalse(plan.ready)
        self.assertIsNone(plan.profile)
        self.assertIn("scheduler does not match host family", plan.errors)

    def test_profile_rejects_relative_python_executable(self) -> None:
        paths = resolve_platform_paths(
            HostFamily.MACOS, {}, PurePosixPath("/Users/Example")
        )

        plan = plan_machine_profile(
            self.installation(HostFamily.MACOS),
            HostIdentity(HostFamily.MACOS, "workstation-01"),
            paths,
            "python3",
            "0.1.0",
            SchedulerKind.LAUNCHD,
        )

        self.assertFalse(plan.ready)
        self.assertIn("python executable must be absolute", plan.errors)

    def test_profile_rejects_runtime_database_lock_or_log_under_shared_root(self) -> None:
        base = resolve_platform_paths(
            HostFamily.MACOS, {}, PurePosixPath("/Users/Example")
        )
        shared = PurePosixPath("/Volumes/ContextOS/shared")
        cases = {
            "runtime": replace(base, runtime_root=shared / "runtime"),
            "database": replace(base, database_path=shared / "projectos.db"),
            "lock": replace(base, lock_path=shared / "projectos.lock"),
            "log": replace(base, log_root=shared / "logs"),
        }

        for name, paths in cases.items():
            with self.subTest(name=name):
                plan = plan_machine_profile(
                    self.installation(HostFamily.MACOS),
                    HostIdentity(HostFamily.MACOS, "workstation-01"),
                    paths,
                    "/usr/bin/python3",
                    "0.1.0",
                    SchedulerKind.LAUNCHD,
                    (str(shared),),
                )
                self.assertFalse(plan.ready)
                self.assertTrue(any(name in error for error in plan.errors), plan.errors)

    def test_profile_rejects_contextos_contract_mismatch(self) -> None:
        paths = resolve_platform_paths(
            HostFamily.MACOS, {}, PurePosixPath("/Users/Example")
        )
        installation = self.installation(
            HostFamily.MACOS,
            contract_version=2,
            supported_hosts=(HostFamily.WINDOWS,),
        )

        plan = plan_machine_profile(
            installation,
            HostIdentity(HostFamily.MACOS, "workstation-01"),
            paths,
            "/usr/bin/python3",
            "0.1.0",
            SchedulerKind.LAUNCHD,
        )

        self.assertFalse(plan.ready)
        self.assertIn("ContextOS extension contract is incompatible", plan.errors)
        self.assertIn("ContextOS contract does not support host family", plan.errors)

    def test_profile_planning_does_not_write_files(self) -> None:
        home = self.temp_path / "unused-home"
        paths = resolve_platform_paths(HostFamily.MACOS, {}, home)
        before = tuple(self.temp_path.rglob("*"))

        plan_machine_profile(
            self.installation(HostFamily.MACOS),
            HostIdentity(HostFamily.MACOS, "workstation-01"),
            paths,
            "/usr/bin/python3",
            "0.1.0",
            SchedulerKind.LAUNCHD,
        )

        self.assertEqual(before, tuple(self.temp_path.rglob("*")))

    def test_profile_mapping_is_stable_and_contains_every_spec_field(self) -> None:
        paths = resolve_platform_paths(
            HostFamily.MACOS, {}, PurePosixPath("/Users/Example")
        )
        plan = plan_machine_profile(
            self.installation(HostFamily.MACOS),
            HostIdentity(HostFamily.MACOS, "workstation-01"),
            paths,
            "/usr/bin/python3",
            "0.1.0",
            SchedulerKind.LAUNCHD,
        )

        mapping = machine_profile_mapping(plan.profile)
        self.assertEqual(
            {
                "profile_schema_version",
                "installation_id",
                "machine_id",
                "host_family",
                "projectos_version",
                "contextos_version",
                "extension_contract_version",
                "contextos_root",
                "extensions_root",
                "skills_root",
                "runtime_root",
                "database_path",
                "config_path",
                "lock_path",
                "log_root",
                "staging_root",
                "python_executable",
                "projectos_entrypoint",
                "scheduler_kind",
                "scheduler_task_id",
                "adoption_state",
                "last_verified_manifest_hash",
            },
            set(mapping),
        )
        self.assertEqual("PLANNED", mapping["adoption_state"])
        self.assertIsNone(mapping["last_verified_manifest_hash"])
        self.assertEqual(
            ["/usr/bin/python3", "-m", "projectos.cli"], mapping["projectos_entrypoint"]
        )


if __name__ == "__main__":
    unittest.main()
