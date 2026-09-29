from __future__ import annotations

import json
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from tests.helpers import TemporaryDirectoryMixin

from projectos.acceptance.authority import ACCEPTANCE_ACKNOWLEDGEMENT, AcceptanceTarget, detect_host_session
from projectos.acceptance.journal import HostAcceptanceState
from projectos.acceptance.profile import AcceptanceProfile
from projectos.acceptance.probe import ProbeResult
from projectos.acceptance.store import LocalAcceptanceStore
from projectos.acceptance.transaction import HostAcceptanceContext, HostAcceptanceTransaction
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.adoption.scheduler import SchedulerAction, SchedulerInspection, SchedulerState, adapter_for
from projectos.errors import ValidationError


class Controller:
    def __init__(self, events: list[str], prefix: str) -> None:
        self.events = events
        self.prefix = prefix
        self.active = False

    def adopt(self):
        self.events.append("definition_adopt")
        self.active = True

    def rollback(self):
        self.events.append("definition_rollback")
        self.active = False

    def activate(self):
        self.events.append("runtime_activate")
        self.active = True

    def deactivate(self):
        self.events.append("registry_disable")
        self.active = False


class NativeRunner:
    def __init__(self, events: list[str], *, foreign: bool = False) -> None:
        self.events = events
        self.state = SchedulerState.ENABLED if foreign else SchedulerState.ABSENT
        self.foreign = foreign
        self.hash = None

    def perform(self, action, definition):
        action = SchedulerAction(action)
        if action is SchedulerAction.INSPECT:
            return SchedulerInspection(definition.task_id, self.state, None if self.foreign else self.hash)
        if self.foreign:
            raise ValidationError("foreign existing task")
        self.events.append(f"native_{action.value}")
        if action is SchedulerAction.INSTALL:
            self.state = SchedulerState.INSTALLED_DISABLED
            self.hash = definition.sha256
        elif action is SchedulerAction.ENABLE:
            self.state = SchedulerState.ENABLED
        elif action is SchedulerAction.DISABLE:
            self.state = SchedulerState.INSTALLED_DISABLED
        elif action is SchedulerAction.REMOVE:
            self.state = SchedulerState.ABSENT
            self.hash = None
        return SchedulerInspection(definition.task_id, self.state, self.hash)


class Probe:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def prove_immediate(self) -> ProbeResult:
        self.events.append("probe_immediate_trigger")
        return ProbeResult(True, "COMPLETE", "OK")

    def prove_non_overlap(self) -> ProbeResult:
        self.events.append("probe_native_non_overlap")
        return ProbeResult(True, "LOCKED", "OK")


class HostAcceptanceTransactionTests(TemporaryDirectoryMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._system_index = 0

    def context(self, *, foreign: bool = False, package_verified: bool = True, database: bool = True):
        self._system_index += 1
        root = self.temp_path / f"system-{self._system_index}"
        runtime = (root / "runtime").resolve()
        contextos = (root / "fixture").resolve()
        session = detect_host_session()
        AcceptanceTarget.issue(root / "authority", runtime, HostFamily.MACOS)
        target = AcceptanceTarget.open(
            root / "authority", runtime, ACCEPTANCE_ACKNOWLEDGEMENT, session
        )
        python = PurePosixPath("/usr/bin/python3")
        production = MachineProfile(
            1, "99999999-9999-9999-9999-999999999999", "fixture-machine", HostFamily.MACOS,
            "0.1.0", "3.0.1", 1, PurePosixPath(contextos),
            PurePosixPath(contextos / "context-os/extensions"), PurePosixPath(contextos / "skills"),
            PurePosixPath(runtime), PurePosixPath(runtime / "projectos.db"),
            PurePosixPath(runtime / "projectos.toml"), PurePosixPath(runtime / "projectos.sync.lock"),
            PurePosixPath(runtime / "logs"), PurePosixPath(runtime / "staging"), python,
            (str(python), "-m", "projectos.cli"), SchedulerKind.LAUNCHD,
            "com.contextos.projectos.sync", "ADOPTED", "a" * 64,
        )
        profile = AcceptanceProfile.from_machine_profile(
            production, target, source_revision="1" * 40, release_sha256="2" * 64,
            wheel_sha256="3" * 64, definition_transaction_id="definition-01",
            activation_id="activation-01",
        )
        store = LocalAcceptanceStore.open(target, profile)
        db = Path(production.database_path)
        db.parent.mkdir(parents=True, exist_ok=True)
        if database:
            db.write_bytes(b"disposable-current-schema")
        events: list[str] = []
        definition = adapter_for(profile.machine_profile).render(
            profile.machine_profile, PurePosixPath(runtime / "adoption/machine-profile.json")
        )
        context = HostAcceptanceContext(
            target, profile, store, definition, NativeRunner(events, foreign=foreign),
            Controller(events, "definition"), Controller(events, "runtime"), Probe(events),
            lambda: database, lambda result: events.append("evidence_seal"), package_verified,
        )
        return context, events

    def test_host_transaction_requires_verified_package_clean_authority_and_disposable_database(self) -> None:
        for kwargs in ({"package_verified": False}, {"database": False}):
            with self.subTest(kwargs=kwargs):
                context, _ = self.context(**kwargs)
                with self.assertRaises(ValidationError):
                    HostAcceptanceTransaction(context).begin()

    def test_host_transaction_runs_every_state_in_exact_order(self) -> None:
        context, _ = self.context()
        observed: list[str] = []
        result = HostAcceptanceTransaction(context).begin(boundary_hook=observed.append)
        self.assertEqual(HostAcceptanceState.EVIDENCE_SEALED, result.state)
        self.assertEqual(list(HostAcceptanceTransaction.boundaries()), observed)

    def test_registry_is_disabled_before_native_scheduler_teardown(self) -> None:
        context, events = self.context()
        HostAcceptanceTransaction(context).begin()
        self.assertLess(events.index("registry_disable"), events.index("native_disable"))
        self.assertLess(events.index("native_disable"), events.index("native_remove"))

    def test_transaction_proves_immediate_lock_non_overlap_schedule_discovery_cleanup_and_database_health(self) -> None:
        context, events = self.context()
        result = HostAcceptanceTransaction(context).begin()
        self.assertTrue(result.cleanup_complete)
        expected = {
            "immediate_trigger", "common_lock_contention", "native_non_overlap",
            "two_hour_configuration", "skill_discovery",
        }
        self.assertTrue(expected.issubset(result.proved_cases))
        self.assertIn("probe_immediate_trigger", events)

    def test_foreign_existing_task_is_never_changed(self) -> None:
        context, events = self.context(foreign=True)
        with self.assertRaisesRegex(ValidationError, "foreign"):
            HostAcceptanceTransaction(context).begin()
        self.assertFalse(any(item in events for item in ("native_disable", "native_remove")))

    def test_recovery_at_every_persisted_boundary_is_idempotent(self) -> None:
        for boundary in HostAcceptanceTransaction.boundaries():
            with self.subTest(boundary=boundary):
                context, _ = self.context()
                transaction = HostAcceptanceTransaction(context)
                with self.assertRaises(RuntimeError):
                    transaction.begin(boundary_hook=lambda name, selected=boundary: (_ for _ in ()).throw(RuntimeError(name)) if name == selected else None)
                first = transaction.recover(transaction.run_id)
                second = transaction.recover(transaction.run_id)
                self.assertTrue(first.cleanup_complete)
                self.assertEqual(first, second)

    def test_recovery_after_native_enable_before_journal_write_inspects_and_removes_owned_task(self) -> None:
        context, events = self.context()
        transaction = HostAcceptanceTransaction(context)
        with self.assertRaises(RuntimeError):
            transaction.begin(
                boundary_hook=lambda name: (_ for _ in ()).throw(RuntimeError(name))
                if name == "after_native_enable_before_journal" else None
            )
        result = transaction.recover(transaction.run_id)
        self.assertTrue(result.cleanup_complete)
        self.assertIn("native_remove", events)

    def test_crash_after_each_native_effect_recovers_only_matching_task(self) -> None:
        for boundary in (
            "after_native_install_before_journal",
            "after_native_enable_before_journal",
            "after_native_disable_before_journal",
            "after_native_remove_before_journal",
        ):
            with self.subTest(boundary=boundary):
                context, events = self.context()
                transaction = HostAcceptanceTransaction(context)
                with self.assertRaises(RuntimeError):
                    transaction.begin(
                        boundary_hook=lambda name, selected=boundary: (
                            (_ for _ in ()).throw(RuntimeError(name))
                            if name == selected else None
                        )
                    )
                result = transaction.recover(transaction.run_id)
                self.assertTrue(result.cleanup_complete)
                self.assertEqual(SchedulerState.ABSENT, context.native_runner.state)

    def test_foreign_task_registry_inventory_or_release_mismatch_preserves_uncertain_state(self) -> None:
        context, events = self.context()
        transaction = HostAcceptanceTransaction(context)
        with self.assertRaises(RuntimeError):
            transaction.begin(
                boundary_hook=lambda name: (_ for _ in ()).throw(RuntimeError(name))
                if name == "after_native_enable_before_journal" else None
            )
        context.native_runner.hash = "f" * 64
        with self.assertRaisesRegex(ValidationError, "definition"):
            transaction.recover(transaction.run_id)
        self.assertEqual(SchedulerState.ENABLED, context.native_runner.state)
        self.assertNotIn("native_remove", events)

    def test_recovery_stops_on_definition_registry_or_inventory_mismatch(self) -> None:
        context, _ = self.context()
        transaction = HostAcceptanceTransaction(context)
        with self.assertRaises(RuntimeError):
            transaction.begin(boundary_hook=lambda name: (_ for _ in ()).throw(RuntimeError(name)) if name == "NATIVE_ENABLED" else None)
        context.native_runner.hash = "f" * 64
        with self.assertRaisesRegex(ValidationError, "definition"):
            transaction.recover(transaction.run_id)

    def test_host_journal_contains_only_bounded_identifier_clean_metadata(self) -> None:
        context, _ = self.context()
        transaction = HostAcceptanceTransaction(context)
        transaction.begin()
        path = context.store.root / "runs" / transaction.run_id / "journal.json"
        content = path.read_text(encoding="utf-8")
        mapping = json.loads(content)
        self.assertLess(len(content), 8192)
        self.assertNotIn(str(self.temp_path), content)
        self.assertNotIn("fixture-machine", content)
        self.assertEqual(json.dumps(mapping, sort_keys=True, separators=(",", ":")) + "\n", content)


if __name__ == "__main__":
    unittest.main()
