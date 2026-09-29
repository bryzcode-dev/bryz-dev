from __future__ import annotations

import unittest

from tests.helpers import TemporaryDirectoryMixin

from projectos.google.diagnostics import DiagnosticBundleService
from projectos.google.types import UserCreate, UserRole
from projectos.repositories import ProjectRepository
from projectos.types import ProjectCreate, ProjectType, ProjectVisibility
from projectos.users import UserRepository


class DiagnosticTests(TemporaryDirectoryMixin, unittest.TestCase):
    def test_diagnostic_bundle_excludes_secrets_emails_private_counts_and_rows(self) -> None:
        database = self.open_database()
        users = UserRepository(database, "owner@example.com")
        users.seed_owner("owner@example.com", "Owner")
        users.create(UserCreate("admin@example.com", "Admin", UserRole.ADMIN), "owner@example.com")
        ProjectRepository(database).create(
            ProjectCreate(
                "private-diagnostic", "Hidden Project", ProjectType.LOCAL,
                ProjectVisibility.PRIVATE, owner_notes="ghp_abcdefghijklmnopqrstuvwxyz123456"
            ),
            "owner@example.com",
        )
        manifest = DiagnosticBundleService(database).create(self.temp_path / "diagnostics")
        rendered = "\n".join(path.read_text(encoding="utf-8") for path in manifest.files)
        for forbidden in (
            "owner@example.com", "admin@example.com", "Hidden Project", "private-diagnostic",
            "ghp_", "PRIVATE", "project_count"
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertIn('"schema_version": 3', rendered)
        self.assertEqual(64, len(manifest.sha256))


if __name__ == "__main__":
    unittest.main()
