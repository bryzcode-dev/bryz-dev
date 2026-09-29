from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.bundle import ArtifactPolicy, ExtensionBundleBuilder
from projectos.adoption.contextos import ContextOSLocator
from projectos.adoption.discovery import (
    SkillDiscoveryService,
    load_installed_extension,
)
from projectos.adoption.fixture import FixtureInstallationTarget, issue_empty_fixture
from projectos.adoption.host import HostFamily
from projectos.adoption.manifest import (
    CommandDeclaration,
    CompatibilityDeclaration,
    ExtensionManifest,
    SkillDeclaration,
)
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.adoption.registry import ExtensionRegistry, plan_projectos_entry
from projectos.adoption.scheduler import SchedulerAction, adapter_for
from projectos.adoption.scheduler_fixture import FixtureSchedulerRunner
from projectos.adoption.skill import render_projectos_skill
from projectos.adoption.staging import copy_verified_version, stage_extension
from projectos.adoption.store import LocalAdoptionStore
from projectos.bindings import GoogleBindingRepository
from projectos.credentials import CredentialReferenceCreate, CredentialReferenceService
from projectos.database import ProjectOSDatabase
from projectos.google.types import GoogleBindingCreate
from projectos.users import UserRepository


class SkillDiscoveryTests(TemporaryDirectoryMixin, unittest.TestCase):
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
                ("sync", "status", "inspect-project"),
            ),
            (
                CommandDeclaration("health", ("projectos", "doctor"), False),
                CommandDeclaration("sync", ("projectos", "sync", "run"), True),
            ),
            2,
            "CURRENT",
            "machine-profile.json",
            True,
            (),
            "STAGED",
            (),
        )

    def _profile(self, runtime: Path, contextos: Path) -> MachineProfile:
        return MachineProfile(
            1,
            "77777777-7777-7777-7777-777777777777",
            "fixture-discovery",
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
            Path(sys.executable),
            (sys.executable, "-m", "projectos.cli"),
            SchedulerKind.LAUNCHD,
            "com.contextos.projectos.sync",
            "ADOPTED",
            None,
        )

    def _database_and_config(self, profile: MachineProfile) -> None:
        database = ProjectOSDatabase(Path(profile.database_path)).initialize()
        owner = "owner@example.com"
        UserRepository(database, owner).seed_owner(owner, "Owner")
        credential = CredentialReferenceService(database).create(
            CredentialReferenceCreate(
                "GOOGLE", "discovery", "ADC", "sync", "KEYCHAIN", "projectos/discovery"
            ),
            owner,
        )
        binding = GoogleBindingRepository(database).create(
            GoogleBindingCreate(
                "DEV",
                "sheet-discovery",
                "ProjectOS",
                1,
                credential.credential_id,
                enabled=True,
                write_enabled=True,
            ),
            owner,
        )
        database.close()
        Path(profile.config_path).write_text(
            "\n".join(
                (
                    "contract_version = 1",
                    f'machine_id = "{profile.machine_id}"',
                    'environment = "DEV"',
                    f'binding_id = "{binding.binding_id}"',
                    'spreadsheet_id = "sheet-discovery"',
                    'expected_owner_email = "owner@example.com"',
                    f'credential_reference_id = "{credential.credential_id}"',
                    "google_enabled = true",
                    "google_write_enabled = true",
                    "",
                )
            ),
            encoding="utf-8",
        )

    def system(
        self,
        name: str,
        *,
        canonical_skill: bool = True,
        enable_registry: bool = True,
        enable_scheduler: bool = True,
    ):
        root = self.temp_path / name
        runtime = (root / "runtime").resolve()
        contextos = (root / "contextos").resolve()
        profile = self._profile(runtime, contextos)
        issue_empty_fixture(
            contextos,
            runtime,
            profile.host_family,
            profile.machine_id,
            profile.contextos_version,
        )
        installation = ContextOSLocator(
            HostFamily.MACOS, {}, root / "home"
        ).inspect(contextos)
        target = FixtureInstallationTarget.open(installation, runtime, "FIXTURE_ONLY")
        store = LocalAdoptionStore.open(profile)
        policy = ArtifactPolicy(())
        payload = root / "payload"
        skill_path = payload / "skills/projectos/SKILL.md"
        skill_path.parent.mkdir(parents=True)
        skill_path.write_bytes(
            render_projectos_skill(self.manifest())
            if canonical_skill
            else b"# Noncanonical ProjectOS skill\n"
        )
        (payload / "projectos.whl").write_bytes(b"fixture-wheel")
        bundle = root / "bundle.zip"
        ExtensionBundleBuilder().build(self.manifest(), payload, bundle, policy)
        staged = stage_extension(bundle, profile, store, f"tx-{name}", policy)
        installed_root = copy_verified_version(staged, target)
        entry = plan_projectos_entry(
            staged.manifest,
            staged.bundle_sha256,
            staged.relative_manifest_path,
            "2026-09-27T01:00:00Z",
            enabled=enable_registry,
        )
        target.registry_path.parent.mkdir(parents=True, exist_ok=True)
        target.registry_path.write_bytes(
            ExtensionRegistry.empty().with_projectos(entry).canonical_bytes()
        )
        profile_path = store.save_profile(profile)
        self._database_and_config(profile)
        runner = FixtureSchedulerRunner.open(target, profile, store)
        definition = adapter_for(profile).render(profile, profile_path)
        if enable_scheduler:
            runner.perform(SchedulerAction.INSTALL, definition)
            runner.perform(SchedulerAction.ENABLE, definition)
        return {
            "profile": profile,
            "target": target,
            "store": store,
            "policy": policy,
            "profile_path": profile_path,
            "runner": runner,
            "definition": definition,
            "installed_root": installed_root,
            "staged": staged,
        }

    def test_installed_extension_verifies_manifest_payload_and_bundle_hash_prefix(self) -> None:
        system = self.system("inventory")

        installed = load_installed_extension(
            system["target"], system["profile"], system["policy"]
        )

        self.assertEqual(system["installed_root"], installed.root)
        self.assertEqual(system["staged"].bundle_sha256, installed.bundle_sha256)
        self.assertTrue(installed.root.name.endswith(installed.bundle_sha256[:12]))
        self.assertEqual(
            {"manifest.json", "projectos.whl", "skills/projectos/SKILL.md"},
            {entry.path for entry in installed.inventory},
        )

    def test_discovery_is_read_only_and_never_calls_google(self) -> None:
        system = self.system("readonly")
        target_before = self.inventory(system["target"].root)
        runtime_before = self.inventory(system["store"].root)

        result = SkillDiscoveryService().resolve(
            system["target"],
            system["profile_path"],
            system["store"],
            system["runner"],
            system["policy"],
        )

        self.assertTrue(result.ok)
        self.assertEqual(target_before, self.inventory(system["target"].root))
        self.assertEqual(runtime_before, self.inventory(system["store"].root))

    def test_discovery_returns_verified_skill_only_after_every_gate(self) -> None:
        system = self.system("success")

        result = SkillDiscoveryService().resolve(
            system["target"],
            system["profile_path"],
            system["store"],
            system["runner"],
            system["policy"],
        )

        self.assertTrue(result.ok)
        self.assertIsNone(result.diagnostic)
        self.assertEqual("projectos", result.skill.skill_id)
        self.assertEqual(
            ("inspect-project", "status", "sync"), result.skill.capabilities
        )

    def test_schema_and_manifest_gate_looker_capability_discovery(self) -> None:
        from projectos.adoption.skill import effective_capabilities
        looker = ("looker-status", "looker-assets", "looker-dependencies", "looker-findings", "looker-impact", "looker-reconciliation")
        declared = replace(self.manifest(), database_schema_version=3, skill=replace(self.manifest().skill, capabilities=("status", *looker)))
        self.assertEqual(("status",), effective_capabilities(declared, 2))
        self.assertEqual(tuple(sorted(("status", *looker))), effective_capabilities(declared, 3))
        old_extension = replace(self.manifest(), database_schema_version=2)
        self.assertNotIn("looker-status", effective_capabilities(old_extension, 3))

    def test_discovery_fails_in_order_for_disabled_registry_inventory_skill_profile_database_and_scheduler(self) -> None:
        cases = []
        disabled = self.system("disabled", enable_registry=False)
        cases.append((disabled, "REGISTRY_DISABLED"))
        inventory = self.system("bad-inventory")
        (inventory["installed_root"] / "projectos.whl").write_bytes(b"changed")
        cases.append((inventory, "INVENTORY_MISMATCH"))
        skill = self.system("bad-skill", canonical_skill=False)
        cases.append((skill, "SKILL_CONTRACT_INVALID"))
        profile = self.system("missing-profile")
        profile["profile_path"].unlink()
        cases.append((profile, "PROFILE_UNAVAILABLE"))
        database = self.system("missing-database")
        Path(database["profile"].database_path).unlink()
        cases.append((database, "DATABASE_UNHEALTHY"))
        scheduler = self.system("inactive-scheduler", enable_scheduler=False)
        cases.append((scheduler, "SCHEDULER_INACTIVE"))

        for system, code in cases:
            with self.subTest(code=code):
                result = SkillDiscoveryService().resolve(
                    system["target"],
                    system["profile_path"],
                    system["store"],
                    system["runner"],
                    system["policy"],
                )
                self.assertFalse(result.ok)
                self.assertIsNone(result.skill)
                self.assertEqual(code, result.diagnostic.code)

    def test_discovery_rejects_modified_payload_symlink_profile_or_config(self) -> None:
        payload = self.system("changed-payload")
        (payload["installed_root"] / "projectos.whl").write_bytes(b"changed")
        linked = self.system("linked-payload")
        wheel = linked["installed_root"] / "projectos.whl"
        wheel.unlink()
        wheel.symlink_to(self.temp_path / "outside-wheel")
        profile = self.system("changed-profile")
        mapping = json.loads(profile["profile_path"].read_text(encoding="utf-8"))
        mapping["machine_id"] = "changed-machine"
        profile["profile_path"].write_text(json.dumps(mapping), encoding="utf-8")
        config = self.system("changed-config")
        config_path = Path(config["profile"].config_path)
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                'expected_owner_email = "owner@example.com"',
                'expected_owner_email = "other@example.com"',
            ),
            encoding="utf-8",
        )

        for system in (payload, linked, profile, config):
            with self.subTest(root=system["target"].root):
                result = SkillDiscoveryService().resolve(
                    system["target"],
                    system["profile_path"],
                    system["store"],
                    system["runner"],
                    system["policy"],
                )
                self.assertFalse(result.ok)
                self.assertIsNone(result.skill)

    def test_discovery_read_only_database_check_creates_no_wal_shm_or_migration(self) -> None:
        system = self.system("database-readonly")
        database_path = Path(system["profile"].database_path)
        for suffix in ("-wal", "-shm"):
            Path(f"{database_path}{suffix}").unlink(missing_ok=True)
        before = database_path.read_bytes()

        result = SkillDiscoveryService().resolve(
            system["target"],
            system["profile_path"],
            system["store"],
            system["runner"],
            system["policy"],
        )

        self.assertTrue(result.ok)
        self.assertEqual(before, database_path.read_bytes())
        self.assertFalse(Path(f"{database_path}-wal").exists())
        self.assertFalse(Path(f"{database_path}-shm").exists())

        database_path.unlink()
        connection = sqlite3.connect(database_path)
        connection.executescript(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT);"
            "INSERT INTO schema_migrations VALUES(1,'0001.sql','t');"
        )
        connection.close()
        outdated_before = database_path.read_bytes()
        outdated = SkillDiscoveryService().resolve(
            system["target"],
            system["profile_path"],
            system["store"],
            system["runner"],
            system["policy"],
        )
        self.assertEqual("DATABASE_UNHEALTHY", outdated.diagnostic.code)
        self.assertEqual(outdated_before, database_path.read_bytes())

    def test_discovered_adapter_descriptor_contains_no_resolved_path_or_private_identifier(self) -> None:
        system = self.system("descriptor")
        result = SkillDiscoveryService().resolve(
            system["target"],
            system["profile_path"],
            system["store"],
            system["runner"],
            system["policy"],
        )
        serialized = json.dumps(asdict(result.skill.adapter), sort_keys=True)

        self.assertEqual(("projectos", "runtime", "sync"), result.skill.adapter.entrypoint)
        self.assertNotIn(str(system["profile"].runtime_root), serialized)
        self.assertNotIn(system["profile"].machine_id, serialized)
        self.assertNotIn("sheet-discovery", serialized)
        self.assertNotIn("owner@example.com", serialized)

    @staticmethod
    def inventory(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes().hex()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
