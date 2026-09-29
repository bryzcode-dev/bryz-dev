from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError

from tests.helpers import TemporaryDirectoryMixin

from projectos.errors import ValidationError, VersionConflict
from projectos.repositories import ProjectRepository
from projectos.types import (
    ProjectCreate,
    ProjectPatch,
    ProjectStatus,
    ProjectType,
    ProjectVisibility,
)


def command(slug: str = "example", source_key: str | None = "source:example") -> ProjectCreate:
    return ProjectCreate(
        slug=slug,
        name="Example Project",
        description="A tracked project",
        project_type=ProjectType.GAS,
        visibility=ProjectVisibility.PUBLIC,
        provenance={"adapter": "test"},
        source_key=source_key,
    )


class ProjectRepositoryTests(TemporaryDirectoryMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.database = self.open_database()
        self.repository = ProjectRepository(self.database)

    def test_create_project_assigns_stable_uuid_version_and_provenance(self) -> None:
        record = self.repository.create(command(), actor="owner@example.com")

        self.assertEqual(1, record.version)
        self.assertEqual(ProjectStatus.ACTIVE, record.status)
        self.assertEqual(ProjectVisibility.PUBLIC, record.visibility)
        self.assertEqual({"adapter": "test"}, record.provenance)
        self.assertRegex(str(record.project_id), r"^[0-9a-f-]{36}$")
        self.assertRegex(record.created_at, r"Z$")
        with self.assertRaises(FrozenInstanceError):
            record.name = "Changed"  # type: ignore[misc]

    def test_duplicate_slug_is_rejected(self) -> None:
        self.repository.create(command(source_key=None), actor="owner")
        with self.assertRaises(ValidationError):
            self.repository.create(command(source_key=None), actor="owner")

        with self.assertRaises(ValidationError):
            ProjectCreate(
                slug="bad",
                name="Bad",
                project_type=ProjectType.GAS,
                visibility="EVERYONE",  # type: ignore[arg-type]
            )

    def test_update_requires_current_version(self) -> None:
        created = self.repository.create(command(), actor="owner")
        updated = self.repository.update(
            created.project_id,
            expected_version=1,
            patch=ProjectPatch(name="Renamed"),
            actor="owner",
        )

        self.assertEqual(2, updated.version)
        self.assertEqual("Renamed", updated.name)
        with self.assertRaises(VersionConflict):
            self.repository.update(
                created.project_id,
                expected_version=1,
                patch=ProjectPatch(description="stale"),
                actor="owner",
            )
        self.assertEqual("Renamed", self.repository.get(created.project_id).name)

    def test_archive_increments_version_without_delete(self) -> None:
        created = self.repository.create(command(), actor="owner")
        archived = self.repository.archive(created.project_id, 1, actor="owner")

        self.assertEqual(ProjectStatus.ARCHIVED, archived.status)
        self.assertEqual(2, archived.version)
        self.assertIsNotNone(archived.archived_at)
        self.assertIsNotNone(self.repository.get(created.project_id))

    def test_list_excludes_archived_by_default(self) -> None:
        created = self.repository.create(command(), actor="owner")
        self.repository.archive(created.project_id, 1, actor="owner")

        self.assertEqual([], self.repository.list())
        self.assertEqual(1, len(self.repository.list(include_archived=True)))

    def test_repeated_identical_registration_is_idempotent(self) -> None:
        first = self.repository.create(command(), actor="owner")
        second = self.repository.create(command(), actor="owner")
        audits = self.database.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='project.created'"
        ).fetchone()[0]

        self.assertEqual(first, second)
        self.assertEqual(1, audits)

    def test_source_key_rejects_any_changed_canonical_state(self) -> None:
        self.repository.create(command(), actor="owner")
        changed = ProjectCreate(
            slug="example",
            name="Example Project",
            description="Changed description",
            project_type=ProjectType.GAS,
            visibility=ProjectVisibility.PUBLIC,
            provenance={"adapter": "test"},
            source_key="source:example",
        )

        with self.assertRaises(VersionConflict):
            self.repository.create(changed, actor="owner")

    def test_audit_is_in_same_transaction(self) -> None:
        def fail_audit(*_args, **_kwargs):
            raise RuntimeError("audit failed")

        self.repository.audit.append = fail_audit
        with self.assertRaisesRegex(RuntimeError, "audit failed"):
            self.repository.create(command(), actor="owner")

        project_count = self.database.connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        audit_count = self.database.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        self.assertEqual((0, 0), (project_count, audit_count))


if __name__ == "__main__":
    unittest.main()
