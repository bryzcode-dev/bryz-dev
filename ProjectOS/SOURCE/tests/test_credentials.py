from __future__ import annotations

import json
import unittest

from tests.helpers import TemporaryDirectoryMixin

from projectos.audit import AuditLog
from projectos.credentials import CredentialReferenceCreate, CredentialReferenceService
from projectos.errors import ValidationError
from projectos.repositories import ProjectRepository, ResourceRepository
from projectos.types import ProjectCreate, ProjectType, ProjectVisibility, ResourceUpsert
from projectos.validation import redact_sensitive, reject_secret_material


class CredentialReferenceTests(TemporaryDirectoryMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.database = self.open_database()
        self.projects = ProjectRepository(self.database)
        self.resources = ResourceRepository(self.database)
        self.service = CredentialReferenceService(self.database)
        self.project = self.projects.create(
            ProjectCreate(
                slug="credential-project",
                name="Credential Project",
                project_type=ProjectType.GAS,
                visibility=ProjectVisibility.PUBLIC,
            ),
            actor="owner",
        )

    def safe_command(self) -> CredentialReferenceCreate:
        return CredentialReferenceCreate(
            provider="GOOGLE",
            label="Production GAS OAuth",
            credential_type="OAUTH_REFERENCE",
            purpose="Deploy the project",
            storage_system="1PASSWORD",
            storage_reference="vault://engineering/google-gas-prod",
            owner_project_id=self.project.project_id,
        )

    def test_safe_reference_never_stores_secret_value(self) -> None:
        record = self.service.create(self.safe_command(), actor="owner")
        columns = {
            row[1] for row in self.database.connection.execute("PRAGMA table_info(credential_references)")
        }
        stored = self.database.connection.execute(
            "SELECT * FROM credential_references WHERE credential_id=?", (str(record.credential_id),)
        ).fetchone()

        self.assertNotIn("secret_value", columns)
        self.assertNotIn("token", columns)
        self.assertEqual("vault://engineering/google-gas-prod", stored["storage_reference"])

    def test_duplicate_safe_reference_is_a_validation_error(self) -> None:
        command = self.safe_command()
        self.service.create(command, actor="owner")

        with self.assertRaises(ValidationError):
            self.service.create(command, actor="owner")

    def test_secret_like_keys_are_rejected_recursively(self) -> None:
        for payload in (
            {"nested": {"password": "hunter2"}},
            {"items": [{"api_key": "abc123456789"}]},
            {"refreshToken": "long-refresh-token-value"},
            {"recovery_code": "1111-2222"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                reject_secret_material(payload)

    def test_private_key_and_token_patterns_are_rejected(self) -> None:
        for value in (
            "-----BEGIN PRIVATE KEY-----\nabc",
            "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            "AIzaSyDUMMYLONGGOOGLEKEY1234567890",
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                reject_secret_material({"value": value})

    def test_audit_payload_redacts_sensitive_values(self) -> None:
        with self.database.transaction() as connection:
            AuditLog().append(
                connection,
                "test.redaction",
                "owner",
                "project",
                str(self.project.project_id),
                {"nested": {"password": "do-not-store"}, "safe": "visible"},
            )
        payload = json.loads(
            self.database.connection.execute(
                "SELECT payload_json FROM audit_events WHERE event_type='test.redaction'"
            ).fetchone()[0]
        )
        self.assertEqual("[REDACTED]", payload["nested"]["password"])
        self.assertEqual("visible", payload["safe"])

    def test_impact_lists_all_consuming_projects_and_resources(self) -> None:
        second = self.projects.create(
            ProjectCreate(
                slug="consumer-project",
                name="Consumer Project",
                project_type=ProjectType.GIT,
                visibility=ProjectVisibility.PUBLIC,
            ),
            actor="owner",
        )
        resource = self.resources.upsert(
            second.project_id,
            ResourceUpsert(
                resource_type="API",
                provider="GOOGLE",
                external_id="api-1",
                name="Google API",
            ),
            actor="owner",
        )
        credential = self.service.create(self.safe_command(), actor="owner")
        self.service.link_usage(
            credential.credential_id, self.project.project_id, None, "deployment", actor="owner"
        )
        self.service.link_usage(
            credential.credential_id, second.project_id, resource.resource_id, "runtime", actor="owner"
        )

        impact = self.service.impact(credential.credential_id)
        self.assertEqual(
            {self.project.project_id, second.project_id}, set(impact.project_ids)
        )
        self.assertEqual((resource.resource_id,), impact.resource_ids)

    def test_backup_serialization_path_uses_same_redactor(self) -> None:
        payload = {"config": {"private_key": "secret", "label": "safe"}}
        serialized = json.dumps(redact_sensitive(payload), sort_keys=True)
        self.assertNotIn("secret", serialized)
        self.assertIn("[REDACTED]", serialized)


if __name__ == "__main__":
    unittest.main()
