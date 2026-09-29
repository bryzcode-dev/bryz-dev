from __future__ import annotations

import hashlib
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.contextos import ContextOSLocator
from projectos.adoption.fixture import FixtureInstallationTarget, issue_empty_fixture
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.adoption.scheduler import SchedulerAction, SchedulerState, adapter_for
from projectos.adoption.scheduler_fixture import FixtureSchedulerRunner
from projectos.adoption.store import LocalAdoptionStore
from projectos.errors import ValidationError


class SchedulerFixtureTests(TemporaryDirectoryMixin, unittest.TestCase):
    def context(self):
        runtime = (self.temp_path / "runtime").resolve()
        contextos = (self.temp_path / "contextos-fixture").resolve()
        profile = MachineProfile(
            1,
            "55555555-5555-5555-5555-555555555555",
            "fixture-mac",
            HostFamily.MACOS,
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
            Path(sys.executable),
            (sys.executable, "-m", "projectos.cli"),
            SchedulerKind.LAUNCHD,
            "com.contextos.projectos.sync",
            "ADOPTED",
            "a" * 64,
        )
        issue_empty_fixture(
            contextos,
            runtime,
            profile.host_family,
            profile.machine_id,
            profile.contextos_version,
        )
        installation = ContextOSLocator(
            HostFamily.MACOS, {}, self.temp_path / "home"
        ).inspect(contextos)
        target = FixtureInstallationTarget.open(installation, runtime, "FIXTURE_ONLY")
        store = LocalAdoptionStore.open(profile)
        profile_path = store.root / "machine-profile.json"
        definition = adapter_for(profile).render(profile, profile_path)
        return profile, target, store, definition

    @staticmethod
    def inventory(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_fixture_runner_persists_only_under_local_adoption_store(self) -> None:
        profile, target, store, definition = self.context()
        before_target = self.inventory(target.root)
        runner = FixtureSchedulerRunner.open(target, profile, store)

        runner.perform(SchedulerAction.INSTALL, definition)

        self.assertEqual(before_target, self.inventory(target.root))
        self.assertTrue(runner.root.is_relative_to(store.root / "scheduler-fixtures"))
        self.assertEqual(
            {"definition.bin", "state.json"},
            {path.name for path in runner.root.iterdir()},
        )
        self.assertEqual([], list(store.root.rglob("*.tmp")))

    def test_fixture_runner_install_enable_disable_remove_lifecycle(self) -> None:
        profile, target, store, definition = self.context()
        runner = FixtureSchedulerRunner.open(target, profile, store)

        self.assertEqual(SchedulerState.ABSENT, runner.inspect(definition).state)
        self.assertEqual(
            SchedulerState.INSTALLED_DISABLED,
            runner.perform(SchedulerAction.INSTALL, definition).state,
        )
        self.assertEqual(
            SchedulerState.ENABLED,
            runner.perform(SchedulerAction.ENABLE, definition).state,
        )
        self.assertEqual(SchedulerState.ENABLED, runner.inspect(definition).state)
        self.assertEqual(
            SchedulerState.INSTALLED_DISABLED,
            runner.perform(SchedulerAction.DISABLE, definition).state,
        )
        self.assertEqual(
            SchedulerState.ABSENT,
            runner.perform(SchedulerAction.REMOVE, definition).state,
        )
        self.assertFalse(runner.root.exists())

    def test_fixture_runner_rejects_enable_before_install_and_changed_definition(self) -> None:
        profile, target, store, definition = self.context()
        runner = FixtureSchedulerRunner.open(target, profile, store)

        with self.assertRaisesRegex(ValidationError, "transition"):
            runner.perform(SchedulerAction.ENABLE, definition)
        runner.perform(SchedulerAction.INSTALL, definition)
        changed = replace(definition, sha256="0" * 64)
        with self.assertRaisesRegex(ValidationError, "definition"):
            runner.perform(SchedulerAction.ENABLE, changed)
        changed_argv = replace(definition, argv=(*definition.argv, "--unexpected"))
        with self.assertRaisesRegex(ValidationError, "canonical"):
            runner.perform(SchedulerAction.ENABLE, changed_argv)

    def test_fixture_runner_rejects_nonfixture_overlap_symlink_and_native_executable_request(self) -> None:
        profile, target, store, definition = self.context()
        with self.assertRaisesRegex(ValidationError, "profile"):
            FixtureSchedulerRunner.open(
                target,
                replace(profile, installation_id="66666666-6666-6666-6666-666666666666"),
                store,
            )

        fixture_root = store.root / "scheduler-fixtures"
        fixture_root.parent.mkdir(parents=True, exist_ok=True)
        fixture_root.symlink_to(self.temp_path / "outside", target_is_directory=True)
        with self.assertRaisesRegex(ValidationError, "symlink"):
            FixtureSchedulerRunner.open(target, profile, store)
        fixture_root.unlink()

        runner = FixtureSchedulerRunner.open(target, profile, store)
        native = replace(
            definition,
            argv=("/bin/launchctl", "bootstrap"),
            sha256=hashlib.sha256(definition.content).hexdigest(),
        )
        with self.assertRaisesRegex(ValidationError, "executable"):
            runner.perform(SchedulerAction.INSTALL, native)

    def test_fixture_runner_is_idempotent_for_same_definition(self) -> None:
        profile, target, store, definition = self.context()
        runner = FixtureSchedulerRunner.open(target, profile, store)

        first = runner.perform(SchedulerAction.INSTALL, definition)
        second = runner.perform(SchedulerAction.INSTALL, definition)
        runner.perform(SchedulerAction.ENABLE, definition)
        enabled_again = runner.perform(SchedulerAction.ENABLE, definition)
        runner.perform(SchedulerAction.DISABLE, definition)
        disabled_again = runner.perform(SchedulerAction.DISABLE, definition)

        self.assertEqual(first, second)
        self.assertEqual(SchedulerState.ENABLED, enabled_again.state)
        self.assertEqual(SchedulerState.INSTALLED_DISABLED, disabled_again.state)

    def test_fixture_runner_state_contains_no_secret_or_absolute_contextos_path(self) -> None:
        profile, target, store, definition = self.context()
        runner = FixtureSchedulerRunner.open(target, profile, store)
        runner.perform(SchedulerAction.INSTALL, definition)
        state = (runner.root / "state.json").read_text(encoding="utf-8")
        mapping = json.loads(state)

        self.assertEqual(target.fixture_id, mapping["fixture_id"])
        self.assertEqual(profile.installation_id, mapping["installation_id"])
        self.assertNotIn(str(target.root), state)
        self.assertNotIn("owner@example.com", state)
        self.assertNotIn("credential", state.lower())
        self.assertNotIn("password", state.lower())


if __name__ == "__main__":
    unittest.main()
