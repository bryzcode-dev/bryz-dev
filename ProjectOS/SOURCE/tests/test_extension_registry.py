from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.host import HostFamily
from projectos.adoption.manifest import (
    CommandDeclaration,
    CompatibilityDeclaration,
    ExtensionManifest,
    SkillDeclaration,
)
from projectos.adoption.registry import (
    ExtensionRegistry,
    ProjectOSExtensionEntry,
    plan_disabled_entry,
    plan_projectos_entry,
)
from projectos.errors import ValidationError


class ExtensionRegistryTests(TemporaryDirectoryMixin, unittest.TestCase):
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
                "projectos", "0.1.0", "skills/projectos/SKILL.md", ("sync",)
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

    def entry(self) -> ProjectOSExtensionEntry:
        return plan_disabled_entry(
            self.manifest(),
            "a" * 64,
            "projectos/versions/0.1.0-aaaaaaaa/manifest.json",
            "2026-09-27T01:00:00Z",
        )

    def test_empty_registry_round_trip_is_canonical(self) -> None:
        registry = ExtensionRegistry.empty()

        self.assertEqual(
            b'{"extensions":{},"registry_version":1}\n', registry.canonical_bytes()
        )
        loaded = ExtensionRegistry.from_mapping(json.loads(registry.canonical_bytes()))
        self.assertEqual(registry.to_mapping(), loaded.to_mapping())
        self.assertIsNone(loaded.projectos_entry())

    def test_registry_preserves_unrelated_extension_values(self) -> None:
        unrelated = {
            "enabled": True,
            "nested": {"z": [3, 2, 1], "label": "unchanged"},
        }
        registry = ExtensionRegistry.from_mapping(
            {"registry_version": 1, "extensions": {"other": unrelated}}
        )

        with_projectos = registry.with_projectos(self.entry())
        without_projectos = with_projectos.without_projectos()

        self.assertEqual(unrelated, with_projectos.to_mapping()["extensions"]["other"])
        self.assertEqual(registry.to_mapping(), without_projectos.to_mapping())
        self.assertFalse(with_projectos.projectos_entry().enabled)

    def test_projectos_entry_is_portable_disabled_and_hash_bound(self) -> None:
        entry = self.entry()
        registry = ExtensionRegistry.empty().with_projectos(entry)

        self.assertEqual("projectos", entry.extension_id)
        self.assertEqual("0.1.0", entry.product_version)
        self.assertEqual("a" * 64, entry.bundle_sha256)
        self.assertFalse(entry.enabled)
        self.assertEqual(entry, ExtensionRegistry.from_mapping(registry.to_mapping()).projectos_entry())

    def test_registry_rejects_absolute_traversal_and_casefold_namespace_collision(self) -> None:
        for manifest_path in (
            "/projectos/versions/v/manifest.json",
            "../projectos/manifest.json",
            r"C:\projectos\manifest.json",
            "projectos/other/manifest.json",
        ):
            with self.subTest(manifest_path=manifest_path):
                mapping = self.entry().to_mapping()
                mapping["manifest"] = manifest_path
                with self.assertRaisesRegex(ValidationError, "manifest"):
                    ExtensionRegistry.from_mapping(
                        {"registry_version": 1, "extensions": {"projectos": mapping}}
                    )

        with self.assertRaisesRegex(ValidationError, "namespace"):
            ExtensionRegistry.from_mapping(
                {
                    "registry_version": 1,
                    "extensions": {
                        "ProjectOS": {},
                        "projectos": self.entry().to_mapping(),
                    },
                }
            )

    def test_registry_rejects_secret_material_and_wrong_types(self) -> None:
        with self.assertRaisesRegex(ValidationError, "secret material"):
            ExtensionRegistry.from_mapping(
                {
                    "registry_version": 1,
                    "extensions": {"other": {"api_token": "do-not-store"}},
                }
            )

        cases = (
            {"registry_version": True, "extensions": {}},
            {"registry_version": 1, "extensions": []},
            {
                "registry_version": 1,
                "extensions": {
                    "projectos": {**self.entry().to_mapping(), "enabled": 0}
                },
            },
            {
                "registry_version": 1,
                "extensions": {
                    "projectos": {**self.entry().to_mapping(), "extra": "field"}
                },
            },
            {
                "registry_version": 1,
                "extensions": {
                    "projectos": {**self.entry().to_mapping(), "adopted_at": True}
                },
            },
        )
        for mapping in cases:
            with self.subTest(mapping=mapping), self.assertRaises(ValidationError):
                ExtensionRegistry.from_mapping(mapping)

    def test_registry_load_does_not_create_missing_file(self) -> None:
        path = self.temp_path / "extensions" / "registry.json"

        registry = ExtensionRegistry.load(path)

        self.assertEqual(ExtensionRegistry.empty().to_mapping(), registry.to_mapping())
        self.assertFalse(path.exists())

        path.parent.mkdir(parents=True)
        path.write_bytes(ExtensionRegistry.empty().with_projectos(self.entry()).canonical_bytes())
        self.assertEqual(self.entry(), ExtensionRegistry.load(path).projectos_entry())

    def test_registry_accepts_canonical_enabled_projectos_entry(self) -> None:
        entry = plan_projectos_entry(
            self.manifest(),
            "a" * 64,
            "projectos/versions/0.1.0-aaaaaaaa/manifest.json",
            "2026-09-27T01:00:00Z",
            enabled=True,
        )

        registry = ExtensionRegistry.empty().with_projectos(entry)
        loaded = ExtensionRegistry.from_mapping(registry.to_mapping())

        self.assertTrue(loaded.projectos_entry().enabled)
        self.assertEqual(registry.canonical_bytes(), loaded.canonical_bytes())

    def test_registry_enabled_transition_changes_only_enabled_field(self) -> None:
        disabled = self.entry()

        enabled = disabled.with_enabled(True)

        expected = disabled.to_mapping()
        expected["enabled"] = True
        self.assertEqual(expected, enabled.to_mapping())
        self.assertEqual(disabled, enabled.with_enabled(False))
        with self.assertRaises(ValidationError):
            disabled.with_enabled(1)


if __name__ == "__main__":
    unittest.main()
