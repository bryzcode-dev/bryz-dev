from __future__ import annotations

import json
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.bundle import ArtifactPolicy, ExtensionBundleBuilder
from projectos.adoption.contextos import ContextOSLocator
from projectos.adoption.fixture import FixtureInstallationTarget, issue_empty_fixture
from projectos.adoption.host import HostFamily
from projectos.adoption.manifest import (
    CommandDeclaration,
    CompatibilityDeclaration,
    ExtensionManifest,
    SkillDeclaration,
)
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.adoption.staging import (
    copy_verified_version,
    stage_extension,
    verify_staged_extension,
)
from projectos.adoption.store import LocalAdoptionStore
from projectos.errors import ValidationError


class AdoptionStagingTests(TemporaryDirectoryMixin, unittest.TestCase):
    def profile(self) -> MachineProfile:
        runtime = (self.temp_path / "runtime").resolve()
        contextos = (self.temp_path / "contextos").resolve()
        python = Path("/usr/bin/python3")
        return MachineProfile(
            1,
            "66666666-6666-6666-6666-666666666666",
            "fixture-mac",
            HostFamily.MACOS,
            "0.1.0",
            "3.0.1",
            1,
            contextos,
            contextos / "context-os/extensions",
            contextos / "skills",
            runtime,
            runtime / "projectos.db",
            runtime / "projectos.toml",
            runtime / "projectos.sync.lock",
            runtime / "logs",
            runtime / "staging",
            python,
            (str(python), "-m", "projectos.cli"),
            SchedulerKind.LAUNCHD,
            "com.contextos.projectos.sync",
            "PLANNED",
            None,
        )

    def manifest(self, version: str = "0.1.0") -> ExtensionManifest:
        return ExtensionManifest(
            1,
            1,
            "projectos",
            version,
            "2026-09-27T00:00:00Z",
            CompatibilityDeclaration(
                "3.0.1", "4.0.0", 1, (HostFamily.MACOS, HostFamily.WINDOWS)
            ),
            SkillDeclaration(
                "projectos", version, "skills/projectos/SKILL.md", ("sync",)
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

    def bundle(self, name: str = "bundle", version: str = "0.1.0") -> Path:
        payload = self.temp_path / f"{name}-payload"
        skill = payload / "skills/projectos/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# ProjectOS fixture skill\n", encoding="utf-8")
        (payload / "projectos.whl").write_bytes(b"fixture-wheel")
        output = self.temp_path / f"{name}.zip"
        ExtensionBundleBuilder().build(
            self.manifest(version), payload, output, ArtifactPolicy(())
        )
        return output

    def target(self, profile: MachineProfile) -> FixtureInstallationTarget:
        issue_empty_fixture(
            Path(profile.contextos_root),
            Path(profile.runtime_root),
            profile.host_family,
            profile.machine_id,
        )
        installation = ContextOSLocator(
            profile.host_family, {}, self.temp_path / "home"
        ).inspect(profile.contextos_root)
        return FixtureInstallationTarget.open(
            installation, profile.runtime_root, "FIXTURE_ONLY"
        )

    @staticmethod
    def files(root: Path) -> set[str]:
        return {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        }

    def test_stage_expands_verified_bundle_only_under_local_transaction_root(self) -> None:
        profile = self.profile()
        target = self.target(profile)
        store = LocalAdoptionStore.open(profile)
        before = self.files(target.root)

        staged = stage_extension(
            self.bundle(), profile, store, "tx-stage", ArtifactPolicy(())
        )

        self.assertEqual(
            store.transaction_root("tx-stage")
            / "staged/projectos/versions"
            / staged.version_name,
            staged.root,
        )
        self.assertEqual(
            {"manifest.json", "projectos.whl", "skills/projectos/SKILL.md"},
            self.files(staged.root),
        )
        self.assertEqual(before, self.files(target.root))
        self.assertTrue(str(staged.root).startswith(str(profile.runtime_root)))

    def test_stage_rejects_manifest_profile_or_host_incompatibility(self) -> None:
        profile = self.profile()
        store = LocalAdoptionStore.open(profile)
        bundle = self.bundle()
        cases = (
            replace(profile, contextos_version="4.0.0"),
            replace(profile, extension_contract_version=2),
            replace(profile, host_family=HostFamily.WINDOWS),
        )
        for index, incompatible in enumerate(cases):
            with self.subTest(index=index), self.assertRaisesRegex(
                ValidationError, "incompatible"
            ):
                stage_extension(
                    bundle,
                    incompatible,
                    store,
                    f"tx-incompatible-{index}",
                    ArtifactPolicy(()),
                )

    def test_stage_rejects_symlink_duplicate_traversal_and_secret_members(self) -> None:
        profile = self.profile()
        store = LocalAdoptionStore.open(profile)
        original = self.bundle()
        cases: dict[str, Path] = {}
        for case in ("symlink", "duplicate", "traversal", "secret"):
            output = self.temp_path / f"{case}.zip"
            with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "w") as target:
                for info in source.infolist():
                    content = source.read(info.filename)
                    if case == "symlink" and info.filename == "projectos.whl":
                        info.external_attr = (0o120777 & 0xFFFF) << 16
                    if case == "secret" and info.filename == "projectos.whl":
                        content = b"ghp_abcdefghijklmnopqrstuvwxyz123456"
                    target.writestr(info, content)
                if case == "duplicate":
                    target.writestr("PROJECTOS.WHL", b"duplicate")
                if case == "traversal":
                    target.writestr("../escape.txt", b"escape")
            cases[case] = output

        for case, bundle in cases.items():
            with self.subTest(case=case), self.assertRaises(ValidationError):
                stage_extension(
                    bundle, profile, store, f"tx-{case}", ArtifactPolicy(())
                )

    def test_verify_detects_post_extraction_byte_change(self) -> None:
        profile = self.profile()
        store = LocalAdoptionStore.open(profile)
        staged = stage_extension(
            self.bundle(), profile, store, "tx-change", ArtifactPolicy(())
        )
        (staged.root / "projectos.whl").write_bytes(b"changed")

        with self.assertRaisesRegex(ValidationError, "inventory"):
            verify_staged_extension(staged, profile, ArtifactPolicy(()))

    def test_copy_reverifies_source_and_refuses_existing_nonidentical_version(self) -> None:
        profile = self.profile()
        target = self.target(profile)
        store = LocalAdoptionStore.open(profile)
        staged = stage_extension(
            self.bundle(), profile, store, "tx-copy", ArtifactPolicy(())
        )
        (staged.root / "projectos.whl").write_bytes(b"changed")
        with self.assertRaisesRegex(ValidationError, "inventory"):
            copy_verified_version(staged, target)

        staged = stage_extension(
            self.bundle("second"), profile, store, "tx-copy-2", ArtifactPolicy(())
        )
        destination = target.extensions_root / "projectos/versions" / staged.version_name
        destination.mkdir(parents=True)
        (destination / "wrong.txt").write_text("wrong", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "nonidentical"):
            copy_verified_version(staged, target)

    def test_copy_is_idempotent_for_identical_immutable_version(self) -> None:
        profile = self.profile()
        target = self.target(profile)
        store = LocalAdoptionStore.open(profile)
        staged = stage_extension(
            self.bundle(), profile, store, "tx-idempotent", ArtifactPolicy(())
        )

        first = copy_verified_version(staged, target)
        first_files = self.files(first)
        second = copy_verified_version(staged, target)

        self.assertEqual(first, second)
        self.assertEqual(first_files, self.files(second))
        self.assertEqual([], list(first.parent.glob(".*.tmp")))


if __name__ == "__main__":
    unittest.main()
