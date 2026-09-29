from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

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
from projectos.adoption.registry import ExtensionRegistry
from projectos.adoption.store import (
    AdoptionOperation,
    LocalAdoptionStore,
    TransactionState,
)
from projectos.adoption.transaction import AdoptionTransaction
from projectos.errors import ValidationError


class AdoptionTransactionTests(TemporaryDirectoryMixin, unittest.TestCase):
    def profile(self, suffix: str = "default") -> MachineProfile:
        runtime = (self.temp_path / f"runtime-{suffix}").resolve()
        contextos = (self.temp_path / f"contextos-{suffix}").resolve()
        python = Path("/usr/bin/python3")
        return MachineProfile(
            1,
            f"77777777-7777-7777-7777-{abs(hash(suffix)) % 10**12:012d}",
            f"fixture-{suffix}",
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

    def manifest(self, version: str) -> ExtensionManifest:
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

    def bundle(self, name: str, version: str) -> Path:
        payload = self.temp_path / f"payload-{name}"
        skill = payload / "skills/projectos/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(f"# ProjectOS {version}\n", encoding="utf-8")
        (payload / "projectos.whl").write_bytes(f"wheel-{version}".encode())
        output = self.temp_path / f"{name}.zip"
        ExtensionBundleBuilder().build(
            self.manifest(version), payload, output, ArtifactPolicy(())
        )
        return output

    def environment(
        self, suffix: str
    ) -> tuple[MachineProfile, FixtureInstallationTarget, LocalAdoptionStore]:
        profile = self.profile(suffix)
        issue_empty_fixture(
            Path(profile.contextos_root),
            Path(profile.runtime_root),
            profile.host_family,
            profile.machine_id,
        )
        installation = ContextOSLocator(
            profile.host_family, {}, self.temp_path / f"home-{suffix}"
        ).inspect(profile.contextos_root)
        target = FixtureInstallationTarget.open(
            installation, profile.runtime_root, "FIXTURE_ONLY"
        )
        return profile, target, LocalAdoptionStore.open(profile)

    def transaction(
        self,
        suffix: str,
        operation: AdoptionOperation = AdoptionOperation.ADOPT,
        version: str = "0.1.0",
    ) -> tuple[AdoptionTransaction, FixtureInstallationTarget, MachineProfile]:
        profile, target, store = self.environment(suffix)
        bundle = None if operation is AdoptionOperation.UNINSTALL else self.bundle(suffix, version)
        transaction = AdoptionTransaction.begin(
            operation,
            target,
            profile,
            store,
            ArtifactPolicy(()),
            f"tx-{suffix}",
            bundle,
        )
        return transaction, target, profile

    @staticmethod
    def run_to_verified(transaction: AdoptionTransaction) -> None:
        transaction.preflight()
        transaction.snapshot()
        transaction.stage()
        transaction.verify()

    @classmethod
    def adopt(cls, transaction: AdoptionTransaction) -> None:
        cls.run_to_verified(transaction)
        transaction.adopt_disabled()

    def test_adopt_requires_ordered_discover_preflight_snapshot_stage_verify(self) -> None:
        transaction, _, _ = self.transaction("ordered")

        for action in (
            transaction.snapshot,
            transaction.stage,
            transaction.verify,
            transaction.adopt_disabled,
        ):
            with self.subTest(action=action.__name__), self.assertRaises(ValidationError):
                action()

        self.assertEqual(TransactionState.PREFLIGHTED, transaction.preflight().state)
        self.assertEqual(TransactionState.SNAPSHOTTED, transaction.snapshot().state)
        self.assertEqual(TransactionState.STAGED, transaction.stage().state)
        self.assertEqual(TransactionState.VERIFIED, transaction.verify().state)
        self.assertEqual(TransactionState.ADOPTED, transaction.adopt_disabled().state)

    def test_transaction_id_cannot_replace_existing_journal(self) -> None:
        transaction, target, profile = self.transaction("duplicate-id")

        with self.assertRaisesRegex(ValidationError, "already exists"):
            AdoptionTransaction.begin(
                AdoptionOperation.ADOPT,
                target,
                profile,
                LocalAdoptionStore.open(profile),
                ArtifactPolicy(()),
                transaction.journal.transaction_id,
                self.bundle("duplicate-id-second", "0.2.0"),
            )

    def test_adopt_rejects_existing_entry_and_upgrade_requires_one(self) -> None:
        upgrade, _, _ = self.transaction(
            "upgrade-without-entry", AdoptionOperation.UPGRADE
        )
        with self.assertRaisesRegex(ValidationError, "existing ProjectOS"):
            upgrade.preflight()

        adopted, target, profile = self.transaction("adopt-existing-source")
        self.adopt(adopted)
        replacement = AdoptionTransaction.begin(
            AdoptionOperation.ADOPT,
            target,
            profile,
            LocalAdoptionStore.open(profile),
            ArtifactPolicy(()),
            "tx-adopt-existing-replacement",
            self.bundle("adopt-existing-replacement", "0.2.0"),
        )
        with self.assertRaisesRegex(ValidationError, "already registered"):
            replacement.preflight()

    def test_phase3b_upgrade_rollback_and_uninstall_refuse_enabled_registry(self) -> None:
        adopted, target, profile = self.transaction("enabled-guard")
        self.adopt(adopted)
        registry = ExtensionRegistry.load(target.registry_path)
        target.registry_path.write_bytes(
            registry.with_projectos(
                registry.projectos_entry().with_enabled(True)
            ).canonical_bytes()
        )

        upgrade = AdoptionTransaction.begin(
            AdoptionOperation.UPGRADE,
            target,
            profile,
            LocalAdoptionStore.open(profile),
            ArtifactPolicy(()),
            "tx-enabled-upgrade",
            self.bundle("enabled-upgrade", "0.2.0"),
        )
        uninstall = AdoptionTransaction.begin(
            AdoptionOperation.UNINSTALL,
            target,
            profile,
            LocalAdoptionStore.open(profile),
            ArtifactPolicy(()),
            "tx-enabled-uninstall",
        )

        for action in (upgrade.preflight, adopted.rollback, uninstall.preflight):
            with self.subTest(action=action.__name__), self.assertRaisesRegex(
                ValidationError, "deactivation"
            ):
                action()

    def test_adopt_atomically_switches_only_disabled_projectos_registry_entry(self) -> None:
        transaction, target, _ = self.transaction("switch")
        original = {"registry_version": 1, "extensions": {"other": {"shape": [1, 2]}}}
        target.registry_path.write_text(json.dumps(original), encoding="utf-8")

        self.adopt(transaction)

        registry = ExtensionRegistry.load(target.registry_path)
        self.assertEqual({"shape": [1, 2]}, registry.to_mapping()["extensions"]["other"])
        entry = registry.projectos_entry()
        self.assertIsNotNone(entry)
        self.assertFalse(entry.enabled)
        self.assertTrue((target.extensions_root / entry.manifest).is_file())
        self.assertEqual([], list(target.registry_path.parent.glob("*.tmp")))

    def test_failure_before_registry_replace_leaves_previous_registry_exact(self) -> None:
        transaction, target, _ = self.transaction("before-replace")
        original = b'{ "registry_version" : 1, "extensions" : {"other":{}} }\n'
        target.registry_path.write_bytes(original)
        self.run_to_verified(transaction)

        with patch(
            "projectos.adoption.transaction._boundary",
            side_effect=lambda name: (_ for _ in ()).throw(RuntimeError(name))
            if name == "before_registry_replace"
            else None,
        ), self.assertRaises(RuntimeError):
            transaction.adopt_disabled()

        self.assertEqual(original, target.registry_path.read_bytes())

    def test_failure_after_registry_replace_restores_exact_snapshot(self) -> None:
        transaction, target, profile = self.transaction("after-replace")
        original = b'{ "registry_version" : 1, "extensions" : {"other":{"x":1}} }\n'
        target.registry_path.write_bytes(original)
        self.run_to_verified(transaction)
        with patch(
            "projectos.adoption.transaction._boundary",
            side_effect=lambda name: (_ for _ in ()).throw(RuntimeError(name))
            if name == "after_registry_replace"
            else None,
        ), self.assertRaises(RuntimeError):
            transaction.adopt_disabled()

        resumed = AdoptionTransaction.resume(
            target,
            profile,
            LocalAdoptionStore.open(profile),
            ArtifactPolicy(()),
            "tx-after-replace",
        )
        self.assertEqual(TransactionState.ROLLED_BACK, resumed.recover().state)
        self.assertEqual(original, target.registry_path.read_bytes())

    def test_recovery_removes_only_hash_matching_transaction_owned_version(self) -> None:
        transaction, target, profile = self.transaction("owned")
        self.run_to_verified(transaction)
        with patch(
            "projectos.adoption.transaction._boundary",
            side_effect=lambda name: (_ for _ in ()).throw(RuntimeError(name))
            if name == "before_registry_replace"
            else None,
        ), self.assertRaises(RuntimeError):
            transaction.adopt_disabled()
        installed = next((target.extensions_root / "projectos/versions").iterdir())
        (installed / "projectos.whl").write_bytes(b"not-transaction-owned-anymore")

        resumed = AdoptionTransaction.resume(
            target,
            profile,
            LocalAdoptionStore.open(profile),
            ArtifactPolicy(()),
            "tx-owned",
        )
        with self.assertRaisesRegex(ValidationError, "inventory"):
            resumed.recover()
        self.assertTrue(installed.exists())

    def test_upgrade_retains_previous_version_and_rollback_switches_back(self) -> None:
        first, target, profile = self.transaction("upgrade", version="0.1.0")
        self.adopt(first)
        original_registry = target.registry_path.read_bytes()
        old_entry = ExtensionRegistry.load(target.registry_path).projectos_entry()

        second = AdoptionTransaction.begin(
            AdoptionOperation.UPGRADE,
            target,
            profile,
            LocalAdoptionStore.open(profile),
            ArtifactPolicy(()),
            "tx-upgrade-2",
            self.bundle("upgrade-2", "0.2.0"),
        )
        self.adopt(second)
        new_entry = ExtensionRegistry.load(target.registry_path).projectos_entry()
        self.assertNotEqual(old_entry.manifest, new_entry.manifest)
        self.assertTrue((target.extensions_root / old_entry.manifest).is_file())

        self.assertEqual(TransactionState.ROLLED_BACK, second.rollback().state)
        self.assertEqual(original_registry, target.registry_path.read_bytes())
        self.assertTrue((target.extensions_root / old_entry.manifest).is_file())
        self.assertFalse((target.extensions_root / new_entry.manifest).exists())

    def test_uninstall_removes_only_projectos_and_archives_managed_versions(self) -> None:
        adopted, target, profile = self.transaction("uninstall-source")
        self.adopt(adopted)
        unrelated = target.extensions_root / "other/keep.txt"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("keep", encoding="utf-8")
        uninstall = AdoptionTransaction.begin(
            AdoptionOperation.UNINSTALL,
            target,
            profile,
            LocalAdoptionStore.open(profile),
            ArtifactPolicy(()),
            "tx-uninstall",
        )
        uninstall.preflight()
        uninstall.snapshot()

        result = uninstall.uninstall()

        self.assertEqual(TransactionState.UNINSTALLED, result.state)
        self.assertIsNone(ExtensionRegistry.load(target.registry_path).projectos_entry())
        self.assertTrue(unrelated.is_file())
        self.assertFalse((target.extensions_root / "projectos/versions").exists())
        archives = Path(profile.runtime_root) / "adoption/archives/tx-uninstall"
        self.assertTrue(any(path.is_file() for path in archives.rglob("manifest.json")))

    def test_uninstall_preserves_database_profile_journals_and_unrelated_contextos_state(self) -> None:
        adopted, target, profile = self.transaction("uninstall-preserve")
        self.adopt(adopted)
        database = Path(profile.database_path)
        database.parent.mkdir(parents=True, exist_ok=True)
        database.write_bytes(b"sqlite-data")
        profile_path = LocalAdoptionStore.open(profile).save_profile(profile)
        unrelated = target.root / "unrelated.txt"
        unrelated.write_text("unrelated", encoding="utf-8")
        uninstall = AdoptionTransaction.begin(
            AdoptionOperation.UNINSTALL,
            target,
            profile,
            LocalAdoptionStore.open(profile),
            ArtifactPolicy(()),
            "tx-uninstall-preserve-remove",
        )
        uninstall.preflight()
        uninstall.snapshot()
        uninstall.uninstall()

        self.assertEqual(b"sqlite-data", database.read_bytes())
        self.assertTrue(profile_path.is_file())
        self.assertTrue(unrelated.is_file())
        self.assertTrue(
            (
                LocalAdoptionStore.open(profile).transaction_root(
                    "tx-uninstall-preserve-remove"
                )
                / "journal.json"
            ).is_file()
        )

    def test_interrupted_multiversion_uninstall_restores_archived_versions(self) -> None:
        first, target, profile = self.transaction("uninstall-recovery-v1")
        self.adopt(first)
        second = AdoptionTransaction.begin(
            AdoptionOperation.UPGRADE,
            target,
            profile,
            LocalAdoptionStore.open(profile),
            ArtifactPolicy(()),
            "tx-uninstall-recovery-upgrade",
            self.bundle("uninstall-recovery-v2", "0.2.0"),
        )
        self.adopt(second)
        original_registry = target.registry_path.read_bytes()
        original_versions = self.target_bytes(target.extensions_root / "projectos/versions")
        uninstall = AdoptionTransaction.begin(
            AdoptionOperation.UNINSTALL,
            target,
            profile,
            LocalAdoptionStore.open(profile),
            ArtifactPolicy(()),
            "tx-uninstall-recovery",
        )
        uninstall.preflight()
        uninstall.snapshot()

        with patch(
            "projectos.adoption.transaction._boundary",
            side_effect=lambda name: (_ for _ in ()).throw(RuntimeError(name))
            if name == "after_uninstall_version_remove"
            else None,
        ), self.assertRaises(RuntimeError):
            uninstall.uninstall()

        resumed = AdoptionTransaction.resume(
            target,
            profile,
            LocalAdoptionStore.open(profile),
            ArtifactPolicy(()),
            "tx-uninstall-recovery",
        )
        self.assertEqual(TransactionState.ROLLED_BACK, resumed.recover().state)
        self.assertEqual(original_registry, target.registry_path.read_bytes())
        self.assertEqual(
            original_versions,
            self.target_bytes(target.extensions_root / "projectos/versions"),
        )

    def test_failure_injection_at_every_boundary_is_resumable(self) -> None:
        boundaries = (
            "after_preflight",
            "after_snapshot",
            "after_stage",
            "after_verify",
            "after_version_copy",
            "before_registry_replace",
            "after_registry_replace",
        )
        for index, boundary in enumerate(boundaries):
            with self.subTest(boundary=boundary):
                suffix = f"boundary-{index}"
                transaction, target, profile = self.transaction(suffix)
                actions = (
                    transaction.preflight,
                    transaction.snapshot,
                    transaction.stage,
                    transaction.verify,
                    transaction.adopt_disabled,
                )
                with patch(
                    "projectos.adoption.transaction._boundary",
                    side_effect=lambda name, selected=boundary: (
                        (_ for _ in ()).throw(RuntimeError(name))
                        if name == selected
                        else None
                    ),
                ), self.assertRaises(RuntimeError):
                    for action in actions:
                        action()
                resumed = AdoptionTransaction.resume(
                    target,
                    profile,
                    LocalAdoptionStore.open(profile),
                    ArtifactPolicy(()),
                    f"tx-{suffix}",
                )
                self.assertEqual(TransactionState.ROLLED_BACK, resumed.recover().state)
                self.assertEqual(TransactionState.ROLLED_BACK, resumed.recover().state)

    @staticmethod
    def target_bytes(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
