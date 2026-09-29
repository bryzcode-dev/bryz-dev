from __future__ import annotations

import unittest
from dataclasses import replace

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.bundle import ArtifactPolicy
from projectos.adoption.host import HostFamily
from projectos.adoption.manifest import (
    CommandDeclaration,
    CompatibilityDeclaration,
    ExtensionManifest,
    SkillDeclaration,
)
from projectos.adoption.skill import render_projectos_skill, verify_projectos_skill
from projectos.errors import ValidationError


class ProjectOSSkillTests(TemporaryDirectoryMixin, unittest.TestCase):
    def manifest(self) -> ExtensionManifest:
        return ExtensionManifest(
            1,
            1,
            "projectos",
            "0.1.0",
            "2026-09-27T00:00:00Z",
            CompatibilityDeclaration(
                "3.0.1", "4.0.0", 1, (HostFamily.MACOS, HostFamily.WINDOWS)
            ),
            SkillDeclaration(
                "projectos",
                "0.1.0",
                "skills/projectos/SKILL.md",
                ("sync", "inspect-project", "status"),
            ),
            (CommandDeclaration("health", ("projectos", "doctor"), False),),
            2,
            "CURRENT",
            "machine-profile.json",
            True,
            (),
            "STAGED",
            (),
        )

    def test_skill_render_is_canonical_and_binds_sorted_manifest_capabilities(self) -> None:
        expected = b"""---
name: projectos
description: ContextOS ProjectOS project and connection management.
version: 0.1.0
capabilities:
  - inspect-project
  - status
  - sync
---
# ProjectOS

Use only the adapter capabilities declared above. Do not embed or execute shell commands or resolved local paths.

Synchronize through the ProjectOS runtime adapter before answering state-dependent questions. Report lock contention using only the bounded adapter result.

Authorization: Owner has full access and is the only role allowed to change users. Admin may edit projects but cannot see the admin menu. User is view-only and cannot see the admin menu.

Visibility: PUBLIC projects are visible to all authorized users. PRIVATE projects are visible only to Owner.

Looker capabilities are unavailable in this skill.
"""

        first = render_projectos_skill(self.manifest())
        reordered = replace(
            self.manifest(),
            skill=replace(
                self.manifest().skill,
                capabilities=("status", "sync", "inspect-project"),
            ),
        )

        self.assertEqual(expected, first)
        self.assertEqual(first, render_projectos_skill(reordered))
        verify_projectos_skill(first, self.manifest(), ArtifactPolicy(()))

    def test_skill_requires_sync_before_state_dependent_actions(self) -> None:
        content = render_projectos_skill(self.manifest()).decode("utf-8")

        self.assertIn(
            "Synchronize through the ProjectOS runtime adapter before answering state-dependent questions.",
            content,
        )
        self.assertIn("Report lock contention using only the bounded adapter result.", content)
        self.assertNotIn("projectos runtime sync", content)

    def test_skill_preserves_role_visibility_and_excludes_looker(self) -> None:
        content = render_projectos_skill(self.manifest()).decode("utf-8")

        self.assertIn("Owner has full access and is the only role allowed to change users.", content)
        self.assertIn("Admin may edit projects but cannot see the admin menu.", content)
        self.assertIn("User is view-only and cannot see the admin menu.", content)
        self.assertIn("PUBLIC projects are visible to all authorized users.", content)
        self.assertIn("PRIVATE projects are visible only to Owner.", content)
        self.assertIn("Looker capabilities are unavailable", content)

    def test_skill_rejects_modified_text_extra_capability_secret_and_host_identifier(self) -> None:
        content = render_projectos_skill(self.manifest())
        cases = (
            content.replace(b"# ProjectOS", b"# Changed", 1),
            content.replace(b"  - sync\n", b"  - sync\n  - rollback\n", 1),
            content + b"api_token: do-not-store\n",
            content + b"built on developer-workstation\n",
        )
        for modified in cases:
            with self.subTest(modified=modified[-40:]), self.assertRaisesRegex(
                ValidationError, "canonical"
            ):
                verify_projectos_skill(
                    modified,
                    self.manifest(),
                    ArtifactPolicy(("developer-workstation",)),
                )

        with self.assertRaisesRegex(ValidationError, "forbidden host identifier"):
            verify_projectos_skill(
                content,
                self.manifest(),
                ArtifactPolicy(("state-dependent",)),
            )

    def test_schema_three_manifest_renders_canonical_read_only_looker_capabilities(self) -> None:
        looker = ("looker-status", "looker-assets", "looker-dependencies", "looker-findings", "looker-impact", "looker-reconciliation")
        manifest = replace(self.manifest(), database_schema_version=3, skill=replace(self.manifest().skill, version="0.2.0", capabilities=("status", *looker)))
        content = render_projectos_skill(manifest)
        text = content.decode("utf-8")
        self.assertEqual(content, render_projectos_skill(manifest)); verify_projectos_skill(content, manifest, ArtifactPolicy(()))
        for capability in looker: self.assertIn(f"  - {capability}\n", text)
        self.assertIn("Looker queries are read-only", text); self.assertNotIn("looker-refresh", text); self.assertNotIn("looker waive", text)


if __name__ == "__main__":
    unittest.main()
