from __future__ import annotations

import unittest
from dataclasses import replace
from uuid import uuid4

from tests.helpers import TemporaryDirectoryMixin

from projectos.bindings import GoogleBindingRepository
from projectos.credentials import CredentialReferenceCreate, CredentialReferenceService
from projectos.google.types import GoogleBindingCreate, UserCreate, UserRole
from projectos.repositories import (
    ConnectionRepository,
    DeploymentRepository,
    LocationRepository,
    ProjectRepository,
    ResourceRepository,
)
from projectos.sync.authorization import AuthorizationService
from projectos.sync.mutations import MutationRegistry
from projectos.sync.requests import (
    AccessEventProcessor,
    RemoteAccessEvent,
    RemoteRequest,
    RequestProcessor,
    RequestResultCode,
    compute_access_hash,
    compute_request_hash,
)
from projectos.types import (
    ConnectionUpsert,
    DeploymentEnvironment,
    DeploymentUpsert,
    LocationUpsert,
    ProjectCreate,
    ProjectType,
    ProjectVisibility,
    ResourceUpsert,
)
from projectos.users import UserRepository


class ChangeRequestTests(TemporaryDirectoryMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.database = self.open_database()
        self.owner_email = "owner@example.com"
        users = UserRepository(self.database, self.owner_email)
        self.owner = users.seed_owner(self.owner_email, "Owner")
        self.admin = users.create(UserCreate("admin@example.com", "Admin", UserRole.ADMIN), self.owner_email)
        self.viewer = users.create(UserCreate("user@example.com", "User", UserRole.USER), self.owner_email)
        credential = CredentialReferenceService(self.database).create(
            CredentialReferenceCreate(
                "GOOGLE", "sync", "ADC", "sync", "KEYCHAIN", "projectos/google"
            ),
            self.owner_email,
        )
        self.binding = GoogleBindingRepository(self.database).create(
            GoogleBindingCreate(
                "DEV", "sheet-id", "ProjectOS", 1, credential.credential_id, enabled=True, write_enabled=True
            ),
            self.owner_email,
        )
        self.projects = ProjectRepository(self.database)
        self.project = self.projects.create(
            ProjectCreate(
                "request-project", "Request Project", ProjectType.GAS, ProjectVisibility.PUBLIC
            ),
            self.owner_email,
        )
        self.authorization = AuthorizationService(self.database, self.owner_email)
        self.registry = MutationRegistry(self.database, self.owner_email)
        self.processor = RequestProcessor(
            self.database, self.binding.binding_id, self.authorization, self.registry
        )

    def request(self, **overrides) -> RemoteRequest:
        values = {
            "request_id": uuid4(),
            "request_schema_version": 1,
            "actor_email": "admin@example.com",
            "actor_role_claim": "ADMIN",
            "entity_type": "project",
            "entity_id": self.project.project_id,
            "operation": "UPDATE",
            "base_version": self.projects.get(self.project.project_id).version,
            "changes": {"name": "Renamed Project"},
            "submitted_at": "2026-09-26T12:00:00Z",
            "gas_deployment_id": "gas-dev",
            "source_row": 2,
            "observed_at": "2026-09-26T12:01:00Z",
        }
        values.update(overrides)
        provisional = RemoteRequest(client_request_hash="", **values)
        return replace(provisional, client_request_hash=compute_request_hash(provisional))

    def test_identical_request_replay_returns_durable_result(self) -> None:
        request = self.request()
        first = self.processor.ingest(request)
        second = self.processor.ingest(request)
        self.assertEqual(RequestResultCode.ACCEPTED, first.code)
        self.assertEqual(first, second)
        self.assertEqual(2, self.projects.get(self.project.project_id).version)
        audits = self.database.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='project.updated'"
        ).fetchone()[0]
        self.assertEqual(1, audits)

    def test_uuid_reuse_with_changed_payload_is_tampering(self) -> None:
        request = self.request()
        self.assertEqual(RequestResultCode.ACCEPTED, self.processor.ingest(request).code)
        changed = self.request(request_id=request.request_id, changes={"name": "Malicious Rewrite"}, base_version=2)
        result = self.processor.ingest(changed)
        self.assertEqual(RequestResultCode.REJECTED_TAMPERED, result.code)
        self.assertEqual("Renamed Project", self.projects.get(self.project.project_id).name)
        self.assertEqual(1, self.database.connection.execute(
            "SELECT COUNT(*) FROM remote_request_receipts WHERE request_id=?", (str(request.request_id),)
        ).fetchone()[0])

    def test_historical_row_edit_or_delete_fails_closed(self) -> None:
        first = self.request()
        second = self.request(changes={"description": "updated"})
        self.processor.ingest(first)
        self.processor.ingest(second)
        self.assertTrue(self.processor.verify_remote_history((first, second)))
        with self.assertRaisesRegex(ValueError, "historical"):
            self.processor.verify_remote_history((first,))
        edited = replace(first, changes={"name": "edited"})
        edited = replace(edited, client_request_hash=compute_request_hash(edited))
        with self.assertRaisesRegex(ValueError, "historical"):
            self.processor.verify_remote_history((edited, second))
        edited_with_stale_hash = replace(first, changes={"name": "edited but stale hash"})
        with self.assertRaisesRegex(ValueError, "historical"):
            self.processor.verify_remote_history((edited_with_stale_hash, second))

    def test_unauthorized_and_secret_requests_never_open_domain_mutation(self) -> None:
        unauthorized = self.request(actor_email="user@example.com")
        unauthorized = replace(unauthorized, client_request_hash=compute_request_hash(unauthorized))
        self.assertEqual(
            RequestResultCode.REJECTED_AUTHORIZATION,
            self.processor.ingest(unauthorized).code,
        )
        malformed = self.request(actor_email="not-an-email")
        malformed = replace(malformed, client_request_hash=compute_request_hash(malformed))
        self.assertEqual(
            RequestResultCode.REJECTED_AUTHORIZATION,
            self.processor.ingest(malformed).code,
        )
        secret = self.request(changes={"token": "ghp_abcdefghijklmnopqrstuvwxyz123456"})
        self.assertEqual(RequestResultCode.REJECTED_VALIDATION, self.processor.ingest(secret).code)
        self.assertEqual(1, self.project.version)
        secret_receipts = self.database.connection.execute(
            "SELECT COUNT(*) FROM remote_request_receipts WHERE request_id=?", (str(secret.request_id),)
        ).fetchone()[0]
        self.assertEqual(0, secret_receipts)

    def test_stale_base_version_creates_conflict_without_change(self) -> None:
        result = self.processor.ingest(self.request(base_version=0))
        self.assertEqual(RequestResultCode.CONFLICT, result.code)
        self.assertEqual(1, self.projects.get(self.project.project_id).version)
        self.assertEqual(1, self.database.connection.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0])

    def test_each_supported_entity_operation_uses_typed_allowlisted_handler(self) -> None:
        locations = LocationRepository(self.database)
        resources = ResourceRepository(self.database)
        deployments = DeploymentRepository(self.database)
        connections = ConnectionRepository(self.database)
        location = locations.upsert(
            self.project.project_id,
            LocationUpsert("mac", "LOCAL", drive_folder_url="https://drive.example/old"),
            self.owner_email,
        )
        resource = resources.upsert(
            self.project.project_id,
            ResourceUpsert("SHEET", "GOOGLE", "Old Resource", external_id="stable-resource"),
            self.owner_email,
        )
        deployment = deployments.upsert(
            self.project.project_id,
            DeploymentUpsert(DeploymentEnvironment.DEVELOPMENT, "stable-deploy", deployment_url="https://old.example"),
            self.owner_email,
        )
        connection = connections.upsert(
            ConnectionUpsert(
                "READS", "GAS", source_project_id=self.project.project_id, target_project_id=self.project.project_id
            ),
            self.owner_email,
        )
        cases = (
            ("location", location.location_id, location.version, {"drive_folder_url": "https://drive.example/new"}),
            ("resource", resource.resource_id, resource.version, {"name": "New Resource"}),
            ("deployment", deployment.deployment_id, deployment.version, {"deployment_url": "https://new.example"}),
            ("connection", connection.connection_id, connection.version, {"purpose": "Updated purpose"}),
            ("user", self.admin.user_id, self.admin.version, {"display_name": "Updated Admin"}),
        )
        for entity_type, entity_id, version, changes in cases:
            result = self.processor.ingest(
                self.request(
                    actor_email=self.owner_email,
                    actor_role_claim="OWNER",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    base_version=version,
                    changes=changes,
                )
            )
            self.assertEqual(RequestResultCode.ACCEPTED, result.code, entity_type)

    def test_admin_cannot_change_stable_ids_visibility_paths_credentials_or_users(self) -> None:
        attempts = (
            ("project", self.project.project_id, {"visibility": "PRIVATE"}),
            ("location", uuid4(), {"path": "/private/example"}),
            ("resource", uuid4(), {"external_id": "changed"}),
            ("deployment", uuid4(), {"script_id": "changed"}),
            ("user", self.admin.user_id, {"display_name": "Escalated"}),
        )
        for entity_type, entity_id, changes in attempts:
            result = self.processor.ingest(
                self.request(entity_type=entity_type, entity_id=entity_id, changes=changes)
            )
            self.assertEqual(RequestResultCode.REJECTED_AUTHORIZATION, result.code, entity_type)

    def test_accepted_request_mutation_receipt_and_audit_are_atomic(self) -> None:
        self.database.connection.execute(
            "CREATE TRIGGER fail_project_audit BEFORE INSERT ON audit_events "
            "WHEN NEW.event_type='project.updated' BEGIN SELECT RAISE(ABORT,'audit failed'); END"
        )
        request = self.request()
        result = self.processor.ingest(request)
        self.assertEqual(RequestResultCode.REJECTED_VALIDATION, result.code)
        self.assertEqual(1, self.projects.get(self.project.project_id).version)
        self.assertEqual(0, self.database.connection.execute(
            "SELECT COUNT(*) FROM change_requests WHERE request_id=?", (str(request.request_id),)
        ).fetchone()[0])
        self.assertEqual("REJECTED_VALIDATION", self.database.connection.execute(
            "SELECT processing_status FROM remote_request_receipts WHERE request_id=?", (str(request.request_id),)
        ).fetchone()[0])

    def test_owner_resolution_creates_new_transaction_without_rewriting_history(self) -> None:
        conflict = self.processor.ingest(self.request(base_version=0))
        before = self.database.connection.execute(
            "SELECT request_id,status FROM change_requests ORDER BY submitted_at"
        ).fetchall()
        resolution = self.processor.resolve_conflict(conflict.conflict_id, self.owner_email, "KEEP_CANONICAL")
        after = self.database.connection.execute(
            "SELECT request_id,status FROM change_requests ORDER BY submitted_at,request_id"
        ).fetchall()
        self.assertEqual(RequestResultCode.ACCEPTED, resolution.code)
        self.assertEqual("CONFLICT", before[0][1])
        self.assertEqual(2, len(after))
        self.assertEqual("RESOLVED", self.database.connection.execute(
            "SELECT status FROM conflicts WHERE conflict_id=?", (str(conflict.conflict_id),)
        ).fetchone()[0])

    def test_access_event_is_idempotent_and_only_advances_last_access(self) -> None:
        processor = AccessEventProcessor(self.database, self.binding.binding_id, self.owner_email)
        event = RemoteAccessEvent(uuid4(), "admin@example.com", "2026-09-26T13:00:00Z", "", 3, "2026-09-26T13:01:00Z")
        event = replace(event, payload_hash=compute_access_hash(event))
        first = processor.ingest(event)
        second = processor.ingest(event)
        self.assertEqual(first, second)
        older = RemoteAccessEvent(uuid4(), "admin@example.com", "2026-09-25T13:00:00Z", "", 4, "2026-09-26T13:02:00Z")
        older = replace(older, payload_hash=compute_access_hash(older))
        processor.ingest(older)
        self.assertEqual(
            "2026-09-26T13:00:00Z",
            UserRepository(self.database, self.owner_email).get_by_email("admin@example.com").last_access_at,
        )
        self.assertEqual(2, self.database.connection.execute("SELECT COUNT(*) FROM remote_access_receipts").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
