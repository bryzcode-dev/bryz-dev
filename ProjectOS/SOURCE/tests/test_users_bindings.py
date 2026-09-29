from __future__ import annotations

import unittest

from tests.helpers import TemporaryDirectoryMixin

from projectos.bindings import GoogleBindingRepository
from projectos.credentials import CredentialReferenceCreate, CredentialReferenceService
from projectos.errors import ValidationError, VersionConflict
from projectos.google.types import (
    GoogleBindingCreate,
    GoogleBindingPatch,
    UserCreate,
    UserPatch,
    UserRole,
)
from projectos.users import UserRepository


class UserAndBindingTests(TemporaryDirectoryMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.database = self.open_database()
        self.users = UserRepository(self.database, "owner@example.com")

    def _credential(self):
        return CredentialReferenceService(self.database).create(
            CredentialReferenceCreate(
                provider="GOOGLE",
                label="projectos-sync",
                credential_type="APPLICATION_DEFAULT",
                purpose="ProjectOS workbook sync",
                storage_system="KEYCHAIN",
                storage_reference="projectos/google",
            ),
            actor="owner@example.com",
        )

    def test_seed_owner_is_idempotent_and_normalizes_email(self) -> None:
        first = self.users.seed_owner(" OWNER@Example.COM ", "Project Owner")
        second = self.users.seed_owner("owner@example.com", "Project Owner")
        self.assertEqual(first, second)
        self.assertEqual("owner@example.com", first.email)
        self.assertEqual(UserRole.OWNER, first.role)
        self.assertTrue(first.active)

    def test_second_owner_is_rejected(self) -> None:
        self.users.seed_owner("owner@example.com", "Owner")
        with self.assertRaises(ValidationError):
            self.users.create(
                UserCreate("other@example.com", "Other", UserRole.OWNER),
                actor="owner@example.com",
            )

    def test_protected_owner_cannot_be_demoted_disabled_or_replaced(self) -> None:
        owner = self.users.seed_owner("owner@example.com", "Owner")
        for patch in (
            UserPatch(role=UserRole.ADMIN),
            UserPatch(active=False),
            UserPatch(email="replacement@example.com"),
        ):
            with self.assertRaises(ValidationError):
                self.users.update(owner.user_id, owner.version, patch, "owner@example.com")
        with self.assertRaises(ValidationError):
            self.users.deactivate(owner.user_id, owner.version, "owner@example.com")

    def test_admin_and_user_records_version_normally(self) -> None:
        admin = self.users.create(
            UserCreate(" Admin@Example.com ", "Admin", UserRole.ADMIN),
            actor="owner@example.com",
        )
        user = self.users.create(
            UserCreate("user@example.com", "User", UserRole.USER),
            actor="owner@example.com",
        )
        updated = self.users.update(
            admin.user_id,
            1,
            UserPatch(display_name="Operations Admin"),
            "owner@example.com",
        )
        self.assertEqual(("admin@example.com", 2), (updated.email, updated.version))
        self.assertFalse(self.users.deactivate(user.user_id, 1, "owner@example.com").active)
        with self.assertRaises(VersionConflict):
            self.users.update(admin.user_id, 1, UserPatch(notes="stale"), "owner@example.com")

    def test_binding_contains_only_safe_credential_reference(self) -> None:
        credential = self._credential()
        binding = GoogleBindingRepository(self.database).create(
            GoogleBindingCreate(
                environment="DEVELOPMENT",
                spreadsheet_id="sheet-safe-id",
                display_name="ProjectOS Development",
                contract_version=1,
                credential_id=credential.credential_id,
            ),
            actor="owner@example.com",
        )
        self.assertEqual(credential.credential_id, binding.credential_id)
        self.assertNotIn("storage_reference", binding.__dataclass_fields__)
        self.assertNotIn("credential_value", binding.__dataclass_fields__)

    def test_binding_write_gate_requires_every_flag_and_identifier(self) -> None:
        credential = self._credential()
        repository = GoogleBindingRepository(self.database)
        binding = repository.create(
            GoogleBindingCreate(
                environment="PRODUCTION",
                spreadsheet_id="sheet-id",
                display_name="ProjectOS",
                contract_version=1,
                credential_id=credential.credential_id,
            ),
            actor="owner@example.com",
        )
        with self.assertRaises(ValidationError):
            repository.assert_write_ready(binding.binding_id)
        binding = repository.update(
            binding.binding_id,
            binding.version,
            GoogleBindingPatch(enabled=True, write_enabled=True),
            "owner@example.com",
        )
        self.assertEqual(binding, repository.assert_write_ready(binding.binding_id))
        with self.assertRaises(ValidationError):
            repository.create(
                GoogleBindingCreate("DEV", "", "Broken", 1, credential.credential_id),
                actor="owner@example.com",
            )

    def test_user_and_binding_audits_share_the_mutation_transaction(self) -> None:
        def fail_audit(*_args, **_kwargs):
            raise RuntimeError("audit failed")

        self.users.audit.append = fail_audit
        with self.assertRaisesRegex(RuntimeError, "audit failed"):
            self.users.create(
                UserCreate("user@example.com", "User", UserRole.USER),
                actor="owner@example.com",
            )
        self.assertEqual(0, self.database.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

        credential = self._credential()
        repository = GoogleBindingRepository(self.database)
        repository.audit.append = fail_audit
        with self.assertRaisesRegex(RuntimeError, "audit failed"):
            repository.create(
                GoogleBindingCreate("DEV", "sheet", "Sheet", 1, credential.credential_id),
                actor="owner@example.com",
            )
        self.assertEqual(
            0, self.database.connection.execute("SELECT COUNT(*) FROM google_bindings").fetchone()[0]
        )


if __name__ == "__main__":
    unittest.main()
