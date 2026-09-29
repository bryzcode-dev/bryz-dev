from __future__ import annotations

import unittest

from tests.helpers import TemporaryDirectoryMixin

from projectos.google.types import UserCreate, UserRole
from projectos.repositories import ConnectionRepository, ProjectRepository, ResourceRepository
from projectos.sync.authorization import AuthorizationService
from projectos.sync.types import Capability, OperationRequest
from projectos.types import (
    ConnectionUpsert,
    ProjectCreate,
    ProjectType,
    ProjectVisibility,
    ResourceUpsert,
)
from projectos.users import UserRepository


class AuthorizationTests(TemporaryDirectoryMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.database = self.open_database()
        users = UserRepository(self.database, "owner@example.com")
        users.seed_owner("owner@example.com", "Owner")
        users.create(UserCreate("admin@example.com", "Admin", UserRole.ADMIN), "owner@example.com")
        user = users.create(UserCreate("user@example.com", "User", UserRole.USER), "owner@example.com")
        users.deactivate(user.user_id, user.version, "owner@example.com")
        self.projects = ProjectRepository(self.database)
        self.public = self.projects.create(
            ProjectCreate(
                "public-project",
                "Public Project",
                ProjectType.GAS,
                ProjectVisibility.PUBLIC,
                description="safe searchable text",
                owner_notes="owner secret note",
                context_os_registered=True,
                context_os_project_id="context-private-id",
            ),
            "owner@example.com",
        )
        self.private = self.projects.create(
            ProjectCreate(
                "private-project",
                "Hidden Codename",
                ProjectType.LOCAL,
                ProjectVisibility.PRIVATE,
                description="invisible needle",
                owner_notes="private owner note",
            ),
            "owner@example.com",
        )
        self.authorization = AuthorizationService(self.database, "owner@example.com")

    def test_blank_unlisted_inactive_and_malformed_callers_get_no_data(self) -> None:
        for email in ("", "unknown@example.com", "user@example.com", "not-an-email"):
            context = self.authorization.resolve(email)
            self.assertFalse(context.authorized)
            self.assertEqual((), context.capabilities)
            self.assertIsNone(self.authorization.filter_entity(context, self.public))

    def test_user_views_only_public_safe_fields(self) -> None:
        users = UserRepository(self.database, "owner@example.com")
        users.create(UserCreate("viewer@example.com", "Viewer", UserRole.USER), "owner@example.com")
        context = self.authorization.resolve("viewer@example.com")
        dto = self.authorization.filter_entity(context, self.public)
        self.assertEqual("Public Project", dto.name)
        self.assertFalse(hasattr(dto, "owner_notes"))
        self.assertNotIn("context-private-id", repr(dto))
        self.assertIsNone(self.authorization.filter_entity(context, self.private))
        self.assertFalse(self.authorization.authorize_operation(
            context, OperationRequest("project", "UPDATE", ProjectVisibility.PUBLIC, frozenset({"name"}))
        ))

    def test_admin_edits_only_allowlisted_public_fields(self) -> None:
        context = self.authorization.resolve("admin@example.com")
        self.assertTrue(
            self.authorization.authorize_operation(
                context,
                OperationRequest(
                    "project", "UPDATE", ProjectVisibility.PUBLIC, frozenset({"name", "tags"})
                ),
            )
        )
        for fields in ({"visibility"}, {"owner_notes"}, {"context_os_registered"}):
            self.assertFalse(
                self.authorization.authorize_operation(
                    context,
                    OperationRequest("project", "UPDATE", ProjectVisibility.PUBLIC, frozenset(fields)),
                )
            )
        self.assertFalse(
            self.authorization.authorize_operation(
                context,
                OperationRequest("project", "UPDATE", ProjectVisibility.PRIVATE, frozenset({"name"})),
            )
        )

    def test_owner_sees_owner_only_fields(self) -> None:
        context = self.authorization.resolve("owner@example.com")
        self.assertIn(Capability.ADMIN_MENU, context.capabilities)
        dto = self.authorization.filter_entity(context, self.private)
        self.assertEqual("private owner note", dto.owner.owner_notes)
        self.assertTrue(
            self.authorization.authorize_operation(
                context,
                OperationRequest("user", "UPDATE", None, frozenset({"display_name", "role"})),
            )
        )

    def test_private_absence_is_indistinguishable_from_not_found(self) -> None:
        context = self.authorization.resolve("admin@example.com")
        self.assertEqual(
            self.authorization.safe_not_found(context, self.private),
            self.authorization.safe_not_found(context, None),
        )
        self.assertEqual({"code": "NOT_FOUND", "message": "Record not found"}, self.authorization.safe_not_found(context, None))

    def test_search_counts_errors_graph_and_children_do_not_leak_private_existence(self) -> None:
        context = self.authorization.resolve("admin@example.com")
        records = (self.public, self.private)
        self.assertEqual((), self.authorization.filter_search(context, records, "invisible needle"))
        self.assertEqual({"total": 1, "by_status": {"ACTIVE": 1}}, self.authorization.filter_counts(context, records))
        rendered = repr((
            self.authorization.filter_search(context, records, "hidden"),
            self.authorization.filter_counts(context, records),
            self.authorization.safe_not_found(context, self.private),
        ))
        self.assertNotIn("Hidden Codename", rendered)
        self.assertNotIn(str(self.private.project_id), rendered)

    def test_connection_is_hidden_when_either_endpoint_is_invisible(self) -> None:
        # Seed a legacy inconsistent edge directly to prove output filtering still fails closed.
        connection = ConnectionRepository(self.database).upsert(
            ConnectionUpsert(
                connection_type="DEPENDS_ON",
                implementation_method="fixture",
                source_project_id=self.public.project_id,
                target_project_id=self.public.project_id,
            ),
            "owner@example.com",
        )
        self.database.connection.execute(
            "UPDATE connections SET target_project_id=? WHERE connection_id=?",
            (str(self.private.project_id), str(connection.connection_id)),
        )
        connection = ConnectionRepository(self.database).get(connection.connection_id)
        context = self.authorization.resolve("admin@example.com")
        self.assertEqual(
            (),
            self.authorization.filter_connections(context, (connection,), (self.public, self.private)),
        )

    def test_resource_connection_resolves_parent_visibility_before_serialization(self) -> None:
        resources = ResourceRepository(self.database)
        source = resources.upsert(
            self.public.project_id,
            ResourceUpsert("SHEET", "GOOGLE", "Source", external_id="source"),
            "owner@example.com",
        )
        target = resources.upsert(
            self.public.project_id,
            ResourceUpsert("DATASET", "GCP", "Target", external_id="target"),
            "owner@example.com",
        )
        connection = ConnectionRepository(self.database).upsert(
            ConnectionUpsert(
                connection_type="LOADS",
                implementation_method="GAS",
                source_resource_id=source.resource_id,
                target_resource_id=target.resource_id,
            ),
            "owner@example.com",
        )
        context = self.authorization.resolve("admin@example.com")
        visible = self.authorization.filter_connections(
            context, (connection,), (self.public, self.private), (source, target)
        )
        self.assertEqual((connection.connection_id,), tuple(item.connection_id for item in visible))


if __name__ == "__main__":
    unittest.main()
