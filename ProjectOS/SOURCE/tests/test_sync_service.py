from __future__ import annotations

import json
import os
import unittest
from dataclasses import asdict, replace
from unittest.mock import patch
from uuid import uuid4

from tests.helpers import TemporaryDirectoryMixin

from projectos.bindings import GoogleBindingRepository
from projectos.credentials import CredentialReferenceCreate, CredentialReferenceService
from projectos.google.fake_gateway import FakeGoogleGateway, FailurePoint
from projectos.google.gateway import GooglePreflight, PublicationReceipt
from projectos.google.types import GoogleBindingCreate, UserCreate, UserRole
from projectos.repositories import ProjectRepository
from projectos.sync.lock import LockOwner, LockUnavailable, ProjectOSFileLock
from projectos.sync.requests import (
    RemoteAccessEvent,
    RemoteRequest,
    compute_access_hash,
    compute_request_hash,
)
from projectos.sync.service import GoogleSyncService
from projectos.types import ProjectCreate, ProjectType, ProjectVisibility
from projectos.users import UserRepository


class DeniedPreflightGateway(FakeGoogleGateway):
    def preflight(self, binding):
        self._log("preflight")
        return GooglePreflight(False, True, True, False, ("UNEXPECTED_SHARING",))


class MismatchGateway(FakeGoogleGateway):
    def publish_projection(self, binding, bundle):
        receipt = super().publish_projection(binding, bundle)
        return PublicationReceipt(
            receipt.revision_id,
            True,
            {**receipt.row_counts, "Projects": receipt.row_counts.get("Projects", 0) + 1},
            receipt.hashes,
        )


class SyncServiceTests(TemporaryDirectoryMixin, unittest.TestCase):
    def make_system(self, name="system", failures=None, gateway_type=FakeGoogleGateway):
        from projectos.database import ProjectOSDatabase

        database = ProjectOSDatabase(self.temp_path / f"{name}.db").initialize()
        self.addCleanup(database.close)
        owner_email = "owner@example.com"
        users = UserRepository(database, owner_email)
        users.seed_owner(owner_email, "Owner")
        users.create(UserCreate("admin@example.com", "Admin", UserRole.ADMIN), owner_email)
        credential = CredentialReferenceService(database).create(
            CredentialReferenceCreate("GOOGLE", f"sync-{name}", "ADC", "sync", "KEYCHAIN", f"projectos/{name}"),
            owner_email,
        )
        binding = GoogleBindingRepository(database).create(
            GoogleBindingCreate(
                "DEV", f"sheet-{name}", "ProjectOS", 1, credential.credential_id,
                enabled=True, write_enabled=True
            ),
            owner_email,
        )
        project = ProjectRepository(database).create(
            ProjectCreate(f"project-{name}", "Before Sync", ProjectType.GAS, ProjectVisibility.PUBLIC),
            owner_email,
        )
        request = RemoteRequest(
            uuid4(), 1, "admin@example.com", "ADMIN", "project", project.project_id,
            "UPDATE", 1, {"name": "After Sync"}, "2026-09-26T12:00:00Z", "", "gas-dev", 2,
            "2026-09-26T12:01:00Z"
        )
        request = replace(request, client_request_hash=compute_request_hash(request))
        event = RemoteAccessEvent(
            uuid4(), "admin@example.com", "2026-09-26T12:02:00Z", "", 2,
            "2026-09-26T12:03:00Z"
        )
        event = replace(event, payload_hash=compute_access_hash(event))
        request_row = {**asdict(request), "request_id": str(request.request_id), "entity_id": str(request.entity_id), "sequence": 1}
        event_row = {**asdict(event), "event_id": str(event.event_id), "sequence": 1}
        gateway = gateway_type.from_fixture(
            {
                "contract_version": 1,
                "tabs": {},
                "requests": [request_row],
                "access_events": [event_row],
                "write_ready": True,
            },
            failures=failures,
        )
        service = GoogleSyncService(
            database,
            owner_email,
            gateway,
            self.temp_path / f"{name}.lock",
        )
        return database, binding, project, gateway, service

    def test_second_sync_exits_without_remote_or_database_write(self) -> None:
        database, binding, _project, gateway, service = self.make_system()
        with ProjectOSFileLock(self.temp_path / "system.lock", "manual", "held"):
            result = service.run(binding.binding_id, "manual")
        self.assertEqual("LOCKED", result.status)
        self.assertEqual([], gateway.call_log)
        self.assertEqual(0, database.connection.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0])

    def test_lock_retry_is_bounded_and_preserves_safe_owner_result(self) -> None:
        database, binding, _project, gateway, service = self.make_system("bounded")
        clock = [0.0]
        sleeps: list[float] = []

        def monotonic() -> float:
            return clock[0]

        def sleeper(seconds: float) -> None:
            sleeps.append(seconds)
            clock[0] += seconds

        with ProjectOSFileLock(self.temp_path / "bounded.lock", "scheduler", "held-run"):
            result = service.run(
                binding.binding_id,
                "skill",
                wait_seconds=2.0,
                monotonic=monotonic,
                sleeper=sleeper,
            )

        self.assertEqual("LOCKED", result.status)
        self.assertEqual([2.0], sleeps)
        self.assertEqual(
            LockOwner("held-run", "scheduler", result.lock_owner.started_at, True),
            result.lock_owner,
        )
        self.assertEqual([], gateway.call_log)
        self.assertEqual(0, database.connection.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0])

    def test_unreadable_owner_fails_closed_without_retrying_lock(self) -> None:
        database, binding, _project, gateway, service = self.make_system("unstable-owner")

        class UnstableLock:
            attempts = 0

            def __init__(self, *args):
                pass

            def __enter__(self):
                type(self).attempts += 1
                if type(self).attempts > 1:
                    raise AssertionError("unreadable owner must not trigger a second lock attempt")
                raise LockUnavailable("busy")

            def __exit__(self, exc_type, exc, traceback):
                return None

            @staticmethod
            def read_owner(path):
                return None

        sleeps: list[float] = []
        with patch("projectos.sync.service.ProjectOSFileLock", UnstableLock):
            result = service.run(
                binding.binding_id,
                "skill",
                wait_seconds=10,
                monotonic=lambda: 0.0,
                sleeper=sleeps.append,
            )

        self.assertEqual("LOCKED", result.status)
        self.assertIsNone(result.lock_owner)
        self.assertEqual([], sleeps)
        self.assertEqual([], gateway.call_log)
        self.assertEqual(0, database.connection.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0])

    def test_preflight_failure_records_safe_run_and_preserves_checkpoint(self) -> None:
        database, binding, _project, gateway, service = self.make_system(
            "preflight", gateway_type=DeniedPreflightGateway
        )
        result = service.run(binding.binding_id, "manual")
        self.assertEqual("PREFLIGHT_FAILED", result.status)
        self.assertIsNone(service.status(binding.binding_id).checkpoint)
        summary = database.connection.execute("SELECT summary_json FROM sync_runs").fetchone()[0]
        self.assertNotIn("owner@example.com", summary)
        self.assertNotIn("sheet-preflight", summary)

    def test_happy_path_processes_requests_access_and_projection_then_advances_checkpoint(self) -> None:
        database, binding, project, gateway, service = self.make_system("happy")
        result = service.run(binding.binding_id, "manual")
        self.assertEqual("COMPLETE", result.status)
        self.assertEqual((1, 1, 1), (result.request_count, result.access_count, result.projection_count))
        self.assertEqual("After Sync", ProjectRepository(database).get(project.project_id).name)
        self.assertEqual("1", service.status(binding.binding_id).checkpoint)
        self.assertEqual("publish_projection", gateway.call_log[-1]["method"])

    def test_local_commit_remote_failure_retry_does_not_mutate_twice(self) -> None:
        database, binding, project, gateway, service = self.make_system(
            "retry", failures={FailurePoint.BEFORE_PUBLISH_RESULTS: 1}
        )
        first = service.run(binding.binding_id, "timer")
        self.assertEqual("FAILED", first.status)
        self.assertEqual(2, ProjectRepository(database).get(project.project_id).version)
        second = service.run(binding.binding_id, "retry")
        self.assertEqual("COMPLETE", second.status)
        self.assertEqual(2, ProjectRepository(database).get(project.project_id).version)
        self.assertEqual(1, database.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='project.updated'"
        ).fetchone()[0])

    def test_failure_at_every_gateway_boundary_keeps_retry_invariants(self) -> None:
        for index, point in enumerate(FailurePoint):
            with self.subTest(point=point):
                database, binding, project, _gateway, service = self.make_system(
                    f"failure-{index}", failures={point: 1}
                )
                result = service.run(binding.binding_id, "test")
                self.assertIn(result.status, {"FAILED", "PREFLIGHT_FAILED"})
                self.assertIsNone(service.status(binding.binding_id).checkpoint)
                self.assertLessEqual(ProjectRepository(database).get(project.project_id).version, 2)

    def test_checkpoint_never_advances_before_verified_activation(self) -> None:
        _database, binding, _project, _gateway, service = self.make_system(
            "mismatch", gateway_type=MismatchGateway
        )
        result = service.run(binding.binding_id, "manual")
        self.assertEqual("FAILED", result.status)
        self.assertIsNone(service.status(binding.binding_id).checkpoint)

    def test_stale_lock_recovery_requires_dead_pid_and_owned_lock_format(self) -> None:
        path = self.temp_path / "stale.lock"
        path.write_text(json.dumps({
            "format": "projectos-lock-v1", "pid": 999999, "started_at": "t",
            "trigger": "timer", "run_id": "old"
        }), encoding="utf-8")
        with ProjectOSFileLock(path, "manual", "new"):
            metadata = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(os.getpid(), metadata["pid"])
        path.write_text(json.dumps({"pid": 999999}), encoding="utf-8")
        with self.assertRaises(LockUnavailable):
            with ProjectOSFileLock(path, "manual", "newer"):
                pass


if __name__ == "__main__":
    unittest.main()
