from __future__ import annotations

import sqlite3
import unittest
from dataclasses import replace
from uuid import uuid4

from tests.helpers import TemporaryDirectoryMixin

from projectos.bindings import GoogleBindingRepository
from projectos.credentials import CredentialReferenceCreate, CredentialReferenceService
from projectos.google.fake_gateway import FakeGoogleGateway
from projectos.google.gateway import PublicationReceipt
from projectos.google.types import GoogleBindingCreate
from projectos.repositories import ConnectionRepository, ProjectRepository, ResourceRepository
from projectos.sync.projection import (
    ProjectionBuilder,
    ProjectionPublisher,
    safe_result_rows,
)
from projectos.sync.requests import RequestResult, RequestResultCode
from projectos.types import (
    ConnectionUpsert,
    ProjectCreate,
    ProjectType,
    ProjectVisibility,
    ResourceUpsert,
)


class MismatchingGateway(FakeGoogleGateway):
    def publish_projection(self, binding, bundle):
        receipt = super().publish_projection(binding, bundle)
        return PublicationReceipt(
            receipt.revision_id,
            True,
            {**receipt.row_counts, "Projects": receipt.row_counts.get("Projects", 0) + 1},
            receipt.hashes,
        )


class ProjectionTests(TemporaryDirectoryMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.database = self.open_database()
        self.projects = ProjectRepository(self.database)
        self.public = self.projects.create(
            ProjectCreate(
                "z-public", "Zulu Public", ProjectType.GAS, ProjectVisibility.PUBLIC,
                owner_notes="owner-only-public-note"
            ),
            "owner@example.com",
        )
        self.private = self.projects.create(
            ProjectCreate(
                "a-private", "Alpha Private", ProjectType.LOCAL, ProjectVisibility.PRIVATE,
                owner_notes="private-note-never-public"
            ),
            "owner@example.com",
        )
        credential = CredentialReferenceService(self.database).create(
            CredentialReferenceCreate("GOOGLE", "sync", "ADC", "sync", "KEYCHAIN", "projectos/google"),
            "owner@example.com",
        )
        self.binding = GoogleBindingRepository(self.database).create(
            GoogleBindingCreate(
                "DEV", "sheet-id", "ProjectOS", 1, credential.credential_id,
                enabled=True, write_enabled=True
            ),
            "owner@example.com",
        )

    def test_bundle_uses_one_sqlite_read_snapshot(self) -> None:
        statements: list[str] = []
        self.database.connection.set_trace_callback(statements.append)
        ProjectionBuilder().build(self.database.connection, uuid4())
        self.database.connection.set_trace_callback(None)
        transaction_statements = [item.strip().upper() for item in statements if item.strip().upper() in {"BEGIN", "COMMIT"}]
        self.assertEqual(["BEGIN", "COMMIT"], transaction_statements)
        self.assertFalse(self.database.connection.in_transaction)

    def test_projection_rows_have_stable_order_version_revision_and_hash(self) -> None:
        revision_id = uuid4()
        bundle = ProjectionBuilder().build(self.database.connection, revision_id)
        rows = bundle.tabs["Projects"]
        self.assertEqual(
            sorted(row["project_id"] for row in rows),
            [row["project_id"] for row in rows],
        )
        self.assertTrue(all(row["projection_revision"] == str(revision_id) for row in rows))
        self.assertTrue(all(row["version"] == 1 and len(row["row_hash"]) == 64 for row in rows))
        self.assertEqual(64, len(bundle.snapshot_hash))

    def test_private_and_owner_only_fields_never_enter_public_dtos(self) -> None:
        resources = ResourceRepository(self.database)
        first = resources.upsert(
            self.private.project_id,
            ResourceUpsert("FILE", "LOCAL", "Private Source", external_id="private-source"),
            "owner@example.com",
        )
        second = resources.upsert(
            self.private.project_id,
            ResourceUpsert("FILE", "LOCAL", "Private Target", external_id="private-target"),
            "owner@example.com",
        )
        private_connection = ConnectionRepository(self.database).upsert(
            ConnectionUpsert(
                "DEPENDS_ON", "LOCAL", source_resource_id=first.resource_id,
                target_resource_id=second.resource_id
            ),
            "owner@example.com",
        )
        bundle = ProjectionBuilder().build(self.database.connection, uuid4())
        rendered = repr(bundle.public_tabs)
        self.assertIn("Zulu Public", rendered)
        self.assertNotIn("Alpha Private", rendered)
        self.assertNotIn("private-note-never-public", rendered)
        self.assertNotIn("owner-only-public-note", rendered)
        self.assertNotIn("owner_notes", rendered)
        self.assertNotIn(str(private_connection.connection_id), rendered)

    def test_readback_mismatch_keeps_previous_revision_active(self) -> None:
        old_id = str(uuid4())
        self.database.connection.execute(
            "INSERT INTO projection_revisions(revision_id,binding_id,schema_version,snapshot_hash,"
            "entity_counts_json,state,started_at,verified_at,activated_at) "
            "VALUES(?,?,?,?,?,'ACTIVE','t','t','t')",
            (old_id, str(self.binding.binding_id), 1, "old", "{}"),
        )
        bundle = ProjectionBuilder().build(self.database.connection, uuid4())
        gateway = MismatchingGateway.from_fixture({"write_ready": True})
        receipt = ProjectionPublisher(self.database).stage_and_activate(self.binding, bundle, gateway)
        self.assertFalse(receipt.verified)
        states = dict(self.database.connection.execute(
            "SELECT revision_id,state FROM projection_revisions"
        ).fetchall())
        self.assertEqual("ACTIVE", states[old_id])
        self.assertEqual("FAILED", states[str(bundle.revision_id)])

    def test_success_activates_pointer_last_and_supersedes_prior_revision(self) -> None:
        old_id = str(uuid4())
        self.database.connection.execute(
            "INSERT INTO projection_revisions(revision_id,binding_id,schema_version,snapshot_hash,"
            "entity_counts_json,state,started_at,verified_at,activated_at) "
            "VALUES(?,?,?,?,?,'ACTIVE','t','t','t')",
            (old_id, str(self.binding.binding_id), 1, "old", "{}"),
        )
        bundle = ProjectionBuilder().build(self.database.connection, uuid4())
        gateway = FakeGoogleGateway.from_fixture({"write_ready": True})
        receipt = ProjectionPublisher(self.database).stage_and_activate(self.binding, bundle, gateway)
        self.assertTrue(receipt.verified)
        states = dict(self.database.connection.execute(
            "SELECT revision_id,state FROM projection_revisions"
        ).fetchall())
        self.assertEqual("SUPERSEDED", states[old_id])
        self.assertEqual("ACTIVE", states[str(bundle.revision_id)])
        active = self.database.connection.execute(
            "SELECT last_publication_revision FROM google_bindings WHERE binding_id=?",
            (str(self.binding.binding_id),),
        ).fetchone()[0]
        self.assertEqual(str(bundle.revision_id), active)
        self.assertEqual("publish_projection", gateway.call_log[-1]["method"])

    def test_result_publication_contains_only_safe_messages(self) -> None:
        result = RequestResult(
            uuid4(), RequestResultCode.REJECTED_VALIDATION,
            "token ghp_abcdefghijklmnopqrstuvwxyz123456 leaked", 4
        )
        rows = safe_result_rows((result,))
        self.assertEqual("Request validation failed", rows[0]["result_message"])
        self.assertNotIn("ghp_", repr(rows))


if __name__ == "__main__":
    unittest.main()
