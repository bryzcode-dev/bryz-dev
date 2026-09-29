from __future__ import annotations

import inspect
import json
import sys
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path, PurePosixPath
from unittest.mock import patch
from uuid import uuid4

from tests.helpers import TemporaryDirectoryMixin

from projectos.acceptance.authority import (
    ACCEPTANCE_ACKNOWLEDGEMENT,
    AcceptanceTarget,
    detect_host_session,
)
from projectos.acceptance.probe import AcceptanceProbe
from projectos.acceptance.profile import AcceptanceProfile
from projectos.acceptance.store import LocalAcceptanceStore
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind, machine_profile_mapping
from projectos.errors import ValidationError
from projectos.google.fake_gateway import FakeGoogleGateway
from projectos.runtime import RuntimeSyncCoordinator, RuntimeTrigger
from projectos.sync.service import SyncRunResult


class AcceptanceProbeTests(TemporaryDirectoryMixin, unittest.TestCase):
    def prepare(self) -> tuple[AcceptanceProfile, Path]:
        runtime = (self.temp_path / "runtime").resolve()
        contextos = (self.temp_path / "fixture").resolve()
        python = PurePosixPath(sys.executable)
        production = MachineProfile(
            1, "99999999-9999-9999-9999-999999999999", "fixture-machine",
            HostFamily.MACOS, "0.1.0", "3.0.1", 1, PurePosixPath(contextos),
            PurePosixPath(contextos / "context-os/extensions"), PurePosixPath(contextos / "skills"),
            PurePosixPath(runtime), PurePosixPath(runtime / "projectos.db"),
            PurePosixPath(runtime / "projectos.toml"), PurePosixPath(runtime / "projectos.sync.lock"),
            PurePosixPath(runtime / "logs"), PurePosixPath(runtime / "staging"), python,
            (str(python), "-m", "projectos.cli"), SchedulerKind.LAUNCHD,
            "com.contextos.projectos.sync", "ADOPTED", "a" * 64,
        )
        session = detect_host_session()
        AcceptanceTarget.issue(self.temp_path / "authority", runtime, HostFamily.MACOS)
        target = AcceptanceTarget.open(
            self.temp_path / "authority", runtime, ACCEPTANCE_ACKNOWLEDGEMENT, session
        )
        profile = AcceptanceProfile.from_machine_profile(
            production, target, source_revision="1" * 40, release_sha256="2" * 64,
            wheel_sha256="3" * 64, definition_transaction_id="definition-01",
            activation_id="activation-01", max_probe_seconds=2,
        )
        store = LocalAcceptanceStore.open(target, profile)
        store.save_profile(profile)
        profile_path = runtime / "adoption/machine-profile.json"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_text(
            json.dumps(machine_profile_mapping(production), sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return profile, profile_path

    def test_probe_refuses_without_receipt_acceptance_entrypoint_and_local_paths(self) -> None:
        profile, profile_path = self.prepare()
        probe = AcceptanceProbe()
        (profile.target.runtime_root / "acceptance/receipts" / f"{profile.target.receipt_id}.json").unlink()
        with self.assertRaisesRegex(ValidationError, "receipt"):
            probe.run(profile_path, Path(profile.machine_profile.database_path), RuntimeTrigger.SCHEDULER, "immediate_trigger")

        profile, profile_path = self.prepare_again("second")
        stored = profile.target.runtime_root / "acceptance/state/acceptance-profile.json"
        mapping = json.loads(stored.read_text())
        mapping["machine_profile"]["scheduler_task_id"] = "com.contextos.projectos.sync"
        stored.write_text(json.dumps(mapping, sort_keys=True, separators=(",", ":")) + "\n")
        with self.assertRaises(ValidationError):
            probe.run(profile_path, Path(profile.machine_profile.database_path), RuntimeTrigger.SCHEDULER, "immediate_trigger")

        profile, profile_path = self.prepare_again("third")
        with self.assertRaisesRegex(ValidationError, "database"):
            probe.run(profile_path, self.temp_path / "outside.db", RuntimeTrigger.SCHEDULER, "immediate_trigger")

    def prepare_again(self, name: str) -> tuple[AcceptanceProfile, Path]:
        original = self.temp_path
        self.temp_path = original / name
        self.temp_path.mkdir()
        try:
            return self.prepare()
        finally:
            self.temp_path = original

    def test_probe_has_no_gateway_fixture_network_or_production_alias(self) -> None:
        signature = inspect.signature(AcceptanceProbe.run)
        self.assertNotIn("fixture", signature.parameters)
        source = inspect.getsource(AcceptanceProbe)
        self.assertNotIn("from_fixture", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("projectos.cli", source)

    def test_probe_runs_complete_and_locked_through_one_runtime_coordinator_and_lock(self) -> None:
        profile, profile_path = self.prepare()
        results = (
            SyncRunResult(uuid4(), "COMPLETE"),
            SyncRunResult(uuid4(), "LOCKED", error_code="SYNC_LOCKED"),
        )
        probe = AcceptanceProbe()
        for case_id, result in zip(("immediate_trigger", "common_lock_contention"), results):
            with self.subTest(case_id=case_id), patch.object(
                RuntimeSyncCoordinator, "run", return_value=result
            ) as run:
                actual = probe.run(
                    profile_path, Path(profile.machine_profile.database_path),
                    RuntimeTrigger.SCHEDULER, case_id,
                )
                self.assertTrue(actual.ok)
                self.assertEqual(result.status, actual.status)
                self.assertIsInstance(run.call_args.args[3], FakeGoogleGateway)
                self.assertEqual(1, run.call_count)

    def test_probe_barrier_is_receipt_bound_bounded_and_records_only_one_started_invocation(self) -> None:
        profile, profile_path = self.prepare()
        probe = AcceptanceProbe()
        completed = SyncRunResult(uuid4(), "COMPLETE")
        first: list[object] = []
        with patch.object(RuntimeSyncCoordinator, "run", return_value=completed) as run:
            thread = threading.Thread(
                target=lambda: first.append(
                    probe.run(profile_path, Path(profile.machine_profile.database_path), RuntimeTrigger.SCHEDULER, "native_non_overlap")
                )
            )
            thread.start()
            barrier = profile.target.runtime_root / "acceptance/barriers/native_non_overlap.active"
            for _ in range(100):
                if barrier.exists():
                    break
                time.sleep(0.01)
            second = probe.run(
                profile_path, Path(profile.machine_profile.database_path), RuntimeTrigger.SCHEDULER,
                "native_non_overlap",
            )
            (profile.target.runtime_root / "acceptance/barriers/native_non_overlap.release").write_text(
                profile.target.receipt_id + "\n", encoding="ascii"
            )
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual("LOCKED", second.status)
        self.assertEqual(1, run.call_count)
        events = [json.loads(line) for line in (profile.target.runtime_root / "acceptance/evidence-spool/probe-events.jsonl").read_text().splitlines()]
        self.assertEqual(1, sum(event["code"] == "BARRIER_STARTED" for event in events))

    def test_probe_events_are_canonical_bounded_and_identifier_clean(self) -> None:
        profile, profile_path = self.prepare()
        with patch.object(RuntimeSyncCoordinator, "run", return_value=SyncRunResult(uuid4(), "COMPLETE")):
            AcceptanceProbe().run(
                profile_path, Path(profile.machine_profile.database_path), RuntimeTrigger.SCHEDULER,
                "immediate_trigger",
            )
        event_path = profile.target.runtime_root / "acceptance/evidence-spool/probe-events.jsonl"
        content = event_path.read_text(encoding="utf-8")
        self.assertLessEqual(len(content.encode()), 4096)
        for line in content.splitlines():
            self.assertEqual(json.dumps(json.loads(line), sort_keys=True, separators=(",", ":")), line)
        for forbidden in (str(self.temp_path), "fixture-machine", "owner@example.com", "sheet-runtime"):
            self.assertNotIn(forbidden, content)


if __name__ == "__main__":
    unittest.main()
