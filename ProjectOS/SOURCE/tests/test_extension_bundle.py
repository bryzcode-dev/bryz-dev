from __future__ import annotations

import hashlib
import json
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.bundle import (
    ArtifactPolicy,
    ExtensionBundleBuilder,
    verify_extension_bundle,
)
from projectos.adoption.host import HostFamily
from projectos.adoption.manifest import (
    CommandDeclaration,
    CompatibilityDeclaration,
    ExtensionManifest,
    PayloadEntry,
    SkillDeclaration,
)
from projectos.errors import ValidationError


class ExtensionBundleTests(TemporaryDirectoryMixin, unittest.TestCase):
    def manifest(self) -> ExtensionManifest:
        return ExtensionManifest(
            manifest_version=1,
            bundle_format_version=1,
            extension_id="projectos",
            product_version="0.1.0",
            created_at="2026-09-27T00:00:00Z",
            compatibility=CompatibilityDeclaration(
                "3.0.1",
                "4.0.0",
                1,
                (HostFamily.MACOS, HostFamily.WINDOWS),
            ),
            skill=SkillDeclaration(
                "projectos",
                "0.1.0",
                "skills/projectos/SKILL.md",
                ("sync", "status", "inspect-project"),
            ),
            commands=(
                CommandDeclaration("health", ("projectos", "doctor"), False),
                CommandDeclaration("sync", ("projectos", "sync", "run"), True),
            ),
            database_schema_version=2,
            migration_status="CURRENT",
            machine_profile_reference="machine-profile.json",
            scheduler_required=True,
            safe_google_references=(),
            adoption_state="STAGED",
            payload=(),
        )

    def payload(self, name: str = "payload") -> Path:
        root = self.temp_path / name
        skill = root / "skills" / "projectos" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# ProjectOS\n", encoding="utf-8")
        (root / "projectos.whl").write_bytes(b"wheel-placeholder")
        (root / "machine-profile.json").write_text(
            '{"profile_schema_version":1}\n', encoding="utf-8"
        )
        return root

    def test_manifest_requires_projectos_namespace_supported_hosts_and_allowlisted_commands(self) -> None:
        valid = self.manifest()
        valid.validate()

        with self.assertRaisesRegex(ValidationError, "extension_id"):
            replace(valid, extension_id="other").validate()
        with self.assertRaisesRegex(ValidationError, "supported_hosts"):
            replace(
                valid,
                compatibility=replace(
                    valid.compatibility, supported_hosts=(HostFamily.MACOS,)
                ),
            ).validate()
        with self.assertRaisesRegex(ValidationError, "command"):
            replace(
                valid,
                commands=(CommandDeclaration("shell", ("sh", "-c", "id"), True),),
            ).validate()

    def test_manifest_rejects_absolute_build_host_paths_and_secret_fields(self) -> None:
        with self.assertRaisesRegex(ValidationError, "portable relative path"):
            replace(
                self.manifest(), machine_profile_reference="/Users/developer/profile.json"
            ).validate()

        mapping = self.manifest().to_mapping()
        mapping["api_token"] = "not-allowed"
        with self.assertRaisesRegex(ValidationError, "secret material"):
            ExtensionManifest.from_mapping(mapping)

    def test_manifest_round_trip_is_canonical(self) -> None:
        original = self.manifest()

        loaded = ExtensionManifest.from_mapping(original.to_mapping())

        self.assertEqual(original, loaded)
        self.assertEqual(original.canonical_bytes(), loaded.canonical_bytes())
        self.assertTrue(original.canonical_bytes().endswith(b"\n"))

    def test_machine_profile_reference_is_not_required_inside_portable_payload(self) -> None:
        content = b"# ProjectOS\n"
        manifest = replace(
            self.manifest(),
            payload=(
                PayloadEntry(
                    "skills/projectos/SKILL.md",
                    hashlib.sha256(content).hexdigest(),
                    len(content),
                ),
            ),
        )

        manifest.validate()

    def test_manifest_rejects_boolean_and_integer_type_coercion(self) -> None:
        with self.assertRaisesRegex(ValidationError, "invalid"):
            replace(self.manifest(), manifest_version=True).validate()
        with self.assertRaisesRegex(ValidationError, "invalid"):
            replace(self.manifest(), scheduler_required=1).validate()

        for field, value in (
            ("manifest_version", "1"),
            ("scheduler_required", "false"),
            ("database_schema_version", True),
        ):
            with self.subTest(field=field):
                mapping = self.manifest().to_mapping()
                mapping[field] = value
                with self.assertRaisesRegex(ValidationError, "invalid"):
                    ExtensionManifest.from_mapping(mapping)

        mapping = self.manifest().to_mapping()
        mapping["commands"][0]["state_changing"] = "false"
        with self.assertRaisesRegex(ValidationError, "invalid"):
            ExtensionManifest.from_mapping(mapping)

    def test_looker_capabilities_require_schema_three_extension(self) -> None:
        skill = replace(self.manifest().skill, capabilities=("status", "looker-status"))
        with self.assertRaisesRegex(ValidationError, "schema 3"):
            replace(self.manifest(), skill=skill, database_schema_version=2).validate()
        replace(self.manifest(), skill=skill, database_schema_version=3).validate()

    def test_bundle_is_byte_identical_across_two_builds(self) -> None:
        payload = self.payload()
        first = self.temp_path / "first.projectos-extension.zip"
        second = self.temp_path / "second.projectos-extension.zip"
        builder = ExtensionBundleBuilder()

        first_result = builder.build(self.manifest(), payload, first, ArtifactPolicy(()))
        second_result = builder.build(self.manifest(), payload, second, ArtifactPolicy(()))

        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(first_result.sha256, second_result.sha256)
        self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(), first_result.sha256)

    def test_bundle_inventory_hashes_every_payload_and_excludes_self_reference(self) -> None:
        output = self.temp_path / "bundle.zip"
        result = ExtensionBundleBuilder().build(
            self.manifest(), self.payload(), output, ArtifactPolicy(())
        )

        with zipfile.ZipFile(output) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
        inventory = {row["path"]: row for row in manifest["payload"]}
        self.assertEqual(names - {"manifest.json"}, set(inventory))
        self.assertNotIn("manifest.json", inventory)
        self.assertEqual(len(inventory), result.entry_count)
        self.assertEqual(
            hashlib.sha256(b"wheel-placeholder").hexdigest(),
            inventory["projectos.whl"]["sha256"],
        )

    def test_bundle_rejects_traversal_absolute_and_duplicate_casefolded_names(self) -> None:
        policy = ArtifactPolicy(())
        for name in ("../escape", "/absolute/file", r"C:\absolute\file", r"dir\file"):
            with self.subTest(name=name), self.assertRaisesRegex(
                ValidationError, "archive path"
            ):
                policy.inspect(name, self.temp_path / "source", b"safe")

        duplicate_bundle = self.temp_path / "duplicate.zip"
        with zipfile.ZipFile(duplicate_bundle, "w") as archive:
            archive.writestr("manifest.json", self.manifest().canonical_bytes())
            archive.writestr("Readme.txt", b"one")
            archive.writestr("README.TXT", b"two")
        with self.assertRaisesRegex(ValidationError, "duplicate"):
            verify_extension_bundle(duplicate_bundle, policy)

    def test_bundle_rejects_symlink_inputs(self) -> None:
        payload = self.payload("symlink")
        (payload / "linked-wheel").symlink_to(payload / "projectos.whl")

        with self.assertRaisesRegex(ValidationError, "symlink"):
            ExtensionBundleBuilder().build(
                self.manifest(), payload, self.temp_path / "symlink.zip", ArtifactPolicy(())
            )

    def test_bundle_rejects_private_key_token_and_forbidden_host_identifier(self) -> None:
        cases = {
            "private": "-----BEGIN PRIVATE KEY-----\nunsafe",
            "token": "ghp_abcdefghijklmnopqrstuvwxyz123456",
            "host": "built on developer-workstation",
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                payload = self.payload(name)
                (payload / "unsafe.txt").write_text(content, encoding="utf-8")
                with self.assertRaises(ValidationError):
                    ExtensionBundleBuilder().build(
                        self.manifest(),
                        payload,
                        self.temp_path / f"{name}.zip",
                        ArtifactPolicy(("developer-workstation",)),
                    )

    def test_bundle_policy_inspects_manifest_content(self) -> None:
        manifest = replace(
            self.manifest(),
            commands=(
                CommandDeclaration(
                    "health", ("projectos", "doctor", "developer-root"), False
                ),
            ),
        )

        with self.assertRaisesRegex(ValidationError, "forbidden host identifier"):
            ExtensionBundleBuilder().build(
                manifest,
                self.payload("manifest-policy"),
                self.temp_path / "manifest-policy.zip",
                ArtifactPolicy(("developer-root",)),
            )

    def test_failed_build_never_replaces_existing_output(self) -> None:
        output = self.temp_path / "existing.zip"
        output.write_bytes(b"original")
        payload = self.payload("failed")
        (payload / "unsafe.txt").write_text(
            "-----BEGIN PRIVATE KEY-----", encoding="utf-8"
        )

        with self.assertRaises(ValidationError):
            ExtensionBundleBuilder().build(
                self.manifest(), payload, output, ArtifactPolicy(())
            )

        self.assertEqual(b"original", output.read_bytes())

    def test_verify_rejects_hash_or_inventory_tampering(self) -> None:
        output = self.temp_path / "bundle.zip"
        ExtensionBundleBuilder().build(
            self.manifest(), self.payload(), output, ArtifactPolicy(())
        )
        tampered = self.temp_path / "tampered.zip"
        with zipfile.ZipFile(output) as source, zipfile.ZipFile(tampered, "w") as target:
            for info in source.infolist():
                content = source.read(info.filename)
                if info.filename == "projectos.whl":
                    content = b"tampered"
                target.writestr(info, content)

        with self.assertRaisesRegex(ValidationError, "hash"):
            verify_extension_bundle(tampered, ArtifactPolicy(()))

    def test_verify_rejects_archive_symlink_metadata(self) -> None:
        output = self.temp_path / "bundle.zip"
        ExtensionBundleBuilder().build(
            self.manifest(), self.payload(), output, ArtifactPolicy(())
        )
        symlinked = self.temp_path / "symlinked.zip"
        with zipfile.ZipFile(output) as source, zipfile.ZipFile(symlinked, "w") as target:
            for original in source.infolist():
                content = source.read(original.filename)
                if original.filename == "projectos.whl":
                    original.external_attr = (0o120777 & 0xFFFF) << 16
                target.writestr(original, content)

        with self.assertRaisesRegex(ValidationError, "symlink"):
            verify_extension_bundle(symlinked, ArtifactPolicy(()))


if __name__ == "__main__":
    unittest.main()
