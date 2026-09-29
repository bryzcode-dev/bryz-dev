from __future__ import annotations

import unittest

from tests.helpers import TemporaryDirectoryMixin

from projectos.errors import ValidationError
from projectos.repositories import (
    ConnectionRepository,
    DeploymentRepository,
    LocationRepository,
    ProjectRepository,
    ResourceRepository,
)
from projectos.types import (
    ConnectionUpsert,
    DeploymentEnvironment,
    DeploymentUpsert,
    LocationUpsert,
    ProjectCreate,
    ProjectPatch,
    ProjectType,
    ProjectVisibility,
    ResourceUpsert,
)


class AssetRepositoryTests(TemporaryDirectoryMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.database = self.open_database()
        self.projects = ProjectRepository(self.database)
        self.locations = LocationRepository(self.database)
        self.resources = ResourceRepository(self.database)
        self.deployments = DeploymentRepository(self.database)
        self.connections = ConnectionRepository(self.database)
        self.public = self.projects.create(
            ProjectCreate(
                slug="public-project",
                name="Public Project",
                project_type=ProjectType.GAS,
                visibility=ProjectVisibility.PUBLIC,
            ),
            actor="owner",
        )

    def test_project_can_have_multiple_machine_locations(self) -> None:
        first = self.locations.upsert(
            self.public.project_id,
            LocationUpsert(machine_id="mac-mini", location_type="LOCAL", path="/tmp/project-a"),
            actor="owner",
        )
        second = self.locations.upsert(
            self.public.project_id,
            LocationUpsert(machine_id="macbook", location_type="LOCAL", path="/tmp/project-a"),
            actor="owner",
        )

        self.assertNotEqual(first.location_id, second.location_id)
        self.assertEqual(2, len(self.locations.list(self.public.project_id)))

    def test_location_preserves_original_and_normalizes_resolved_path(self) -> None:
        original = str(self.temp_path / "folder" / ".." / "project")
        record = self.locations.upsert(
            self.public.project_id,
            LocationUpsert(machine_id="mac-mini", location_type="LOCAL", path=original),
            actor="owner",
        )

        self.assertEqual(original, record.original_path)
        self.assertEqual(str((self.temp_path / "project").resolve(strict=False)), record.normalized_path)

    def test_var_and_private_var_compare_as_same_location(self) -> None:
        first = self.locations.upsert(
            self.public.project_id,
            LocationUpsert(machine_id="mac-mini", location_type="LOCAL", path="/var/tmp/projectos-demo"),
            actor="owner",
        )
        second = self.locations.upsert(
            self.public.project_id,
            LocationUpsert(machine_id="mac-mini", location_type="LOCAL", path="/private/var/tmp/projectos-demo"),
            actor="owner",
        )

        self.assertEqual(first.location_id, second.location_id)

    def test_resource_identity_uses_provider_and_external_id_not_url(self) -> None:
        first = self.resources.upsert(
            self.public.project_id,
            ResourceUpsert(
                resource_type="SHEET",
                provider="GOOGLE",
                external_id="sheet-123",
                name="Master Sheet",
                url="https://docs.google.com/old",
            ),
            actor="owner",
        )
        second = self.resources.upsert(
            self.public.project_id,
            ResourceUpsert(
                resource_type="SHEET",
                provider="GOOGLE",
                external_id="sheet-123",
                name="Master Sheet",
                url="https://docs.google.com/new",
            ),
            actor="owner",
        )

        self.assertEqual(first.resource_id, second.resource_id)
        self.assertEqual("https://docs.google.com/new", second.url)
        self.assertEqual(2, second.version)

    def test_project_supports_multiple_prod_and_dev_deployments(self) -> None:
        dev = self.deployments.upsert(
            self.public.project_id,
            DeploymentUpsert(
                environment=DeploymentEnvironment.DEVELOPMENT,
                external_deployment_id="dev-1",
                script_id="script-1",
                deployment_url="https://example.test/dev",
            ),
            actor="owner",
        )
        prod = self.deployments.upsert(
            self.public.project_id,
            DeploymentUpsert(
                environment=DeploymentEnvironment.PRODUCTION,
                external_deployment_id="prod-1",
                script_id="script-1",
                deployment_url="https://example.test/prod",
            ),
            actor="owner",
        )

        self.assertNotEqual(dev.deployment_id, prod.deployment_id)
        self.assertEqual(2, len(self.deployments.list(self.public.project_id)))

    def test_connection_requires_existing_endpoints(self) -> None:
        with self.assertRaises(ValidationError):
            self.connections.upsert(
                ConnectionUpsert(
                    source_project_id=self.public.project_id,
                    target_resource_id="00000000-0000-0000-0000-000000000099",
                    connection_type="LOADS_TO",
                    implementation_method="GAS",
                ),
                actor="owner",
            )

    def test_connection_cannot_broaden_private_visibility(self) -> None:
        private = self.projects.create(
            ProjectCreate(
                slug="private-project",
                name="Private Project",
                project_type=ProjectType.GIT,
                visibility=ProjectVisibility.PRIVATE,
            ),
            actor="owner",
        )

        with self.assertRaises(ValidationError):
            self.connections.upsert(
                ConnectionUpsert(
                    source_project_id=private.project_id,
                    target_project_id=self.public.project_id,
                    connection_type="DEPENDS_ON",
                    implementation_method="DIRECT",
                ),
                actor="owner",
            )

    def test_visibility_update_cannot_broaden_existing_connections(self) -> None:
        first = self.projects.create(
            ProjectCreate(
                slug="private-one",
                name="Private One",
                project_type=ProjectType.LOCAL,
                visibility=ProjectVisibility.PRIVATE,
            ),
            actor="owner",
        )
        second = self.projects.create(
            ProjectCreate(
                slug="private-two",
                name="Private Two",
                project_type=ProjectType.LOCAL,
                visibility=ProjectVisibility.PRIVATE,
            ),
            actor="owner",
        )
        self.connections.upsert(
            ConnectionUpsert(
                connection_type="DATA_FLOW",
                implementation_method="LOCAL",
                source_project_id=first.project_id,
                target_project_id=second.project_id,
            ),
            actor="owner",
        )

        with self.assertRaises(ValidationError):
            self.projects.update(
                first.project_id,
                first.version,
                ProjectPatch(visibility=ProjectVisibility.PUBLIC),
                actor="owner",
            )

        self.assertEqual(
            ProjectVisibility.PRIVATE, self.projects.get(first.project_id).visibility
        )

    def test_impact_lists_direct_and_related_projects(self) -> None:
        related = self.projects.create(
            ProjectCreate(
                slug="related-project",
                name="Related Project",
                project_type=ProjectType.GIT,
                visibility=ProjectVisibility.PUBLIC,
            ),
            actor="owner",
        )
        resource = self.resources.upsert(
            self.public.project_id,
            ResourceUpsert(
                resource_type="DATASET",
                provider="GCP",
                external_id="dataset-1",
                name="Shared Dataset",
            ),
            actor="owner",
        )
        self.connections.upsert(
            ConnectionUpsert(
                source_project_id=related.project_id,
                target_resource_id=resource.resource_id,
                connection_type="READS_FROM",
                implementation_method="DIRECT",
            ),
            actor="owner",
        )

        report = self.connections.impact(resource.resource_id)
        self.assertEqual((self.public.project_id,), report.direct_project_ids)
        self.assertEqual((related.project_id,), report.related_project_ids)


if __name__ == "__main__":
    unittest.main()
