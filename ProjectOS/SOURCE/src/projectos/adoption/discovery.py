from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from projectos.adoption.bundle import ArtifactPolicy
from projectos.adoption.fixture import FixtureInstallationTarget
from projectos.adoption.manifest import ExtensionManifest
from projectos.adoption.profile import MachineProfile, machine_profile_mapping
from projectos.adoption.registry import ExtensionRegistry, ProjectOSExtensionEntry
from projectos.adoption.scheduler import (
    SchedulerAction,
    SchedulerRunner,
    SchedulerState,
    adapter_for,
)
from projectos.adoption.skill import effective_capabilities, verify_projectos_skill
from projectos.adoption.staging import (
    check_extension_compatibility,
    expected_extension_inventory,
    inventory_extension,
)
from projectos.adoption.store import LocalAdoptionStore, SnapshotEntry
from projectos.bindings import GoogleBindingRepository
from projectos.database import ProjectOSDatabase
from projectos.errors import MigrationError, ValidationError
from projectos.google.config import ProjectOSGoogleConfig
from projectos.health import ProjectOSDoctor


class SkillContractError(ValidationError):
    pass


@dataclass(frozen=True)
class InstalledProjectOSExtension:
    root: Path
    manifest_path: Path
    skill_path: Path
    bundle_sha256: str
    registry_entry: ProjectOSExtensionEntry
    manifest: ExtensionManifest
    inventory: tuple[SnapshotEntry, ...]


@dataclass(frozen=True)
class DiscoveryDiagnostic:
    code: str
    gate: str


@dataclass(frozen=True)
class AdapterInvocation:
    entrypoint: tuple[str, ...]
    triggers: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveredSkill:
    skill_id: str
    version: str
    path: Path
    capabilities: tuple[str, ...]
    adapter: AdapterInvocation


@dataclass(frozen=True)
class SkillDiscoveryResult:
    skill: DiscoveredSkill | None
    diagnostic: DiscoveryDiagnostic | None

    @property
    def ok(self) -> bool:
        return self.skill is not None and self.diagnostic is None


def _failure(code: str, gate: str) -> SkillDiscoveryResult:
    return SkillDiscoveryResult(None, DiscoveryDiagnostic(code, gate))


def load_installed_extension(
    target: FixtureInstallationTarget,
    profile: MachineProfile,
    policy: ArtifactPolicy,
) -> InstalledProjectOSExtension:
    registry = ExtensionRegistry.load(target.registry_path)
    entry = registry.projectos_entry()
    if entry is None:
        raise ValidationError("ProjectOS registry entry is unavailable")
    relative_manifest = PurePosixPath(entry.manifest)
    parts = relative_manifest.parts
    if (
        len(parts) != 4
        or parts[:2] != ("projectos", "versions")
        or parts[-1] != "manifest.json"
    ):
        raise ValidationError("installed extension manifest path is invalid")
    manifest_path = target.extensions_root / Path(*parts)
    root = manifest_path.parent
    target.assert_managed_path(manifest_path)
    if root.is_symlink() or manifest_path.is_symlink():
        raise ValidationError("installed extension cannot contain symlinks")
    try:
        manifest_content = manifest_path.read_bytes()
        value = json.loads(manifest_content)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("installed extension manifest is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValidationError("installed extension manifest is unavailable or invalid")
    manifest = ExtensionManifest.from_mapping(value)
    if manifest_content != manifest.canonical_bytes():
        raise ValidationError("installed extension manifest is not canonical")
    expected_name = f"{manifest.product_version}-{entry.bundle_sha256[:12]}"
    if (
        root.name != expected_name
        or entry.product_version != manifest.product_version
        or profile.projectos_version != manifest.product_version
    ):
        raise ValidationError("installed extension version does not match registry")
    check_extension_compatibility(manifest, profile)
    inventory = inventory_extension(root, policy)
    if inventory != expected_extension_inventory(manifest):
        raise ValidationError("installed extension inventory does not match manifest")
    skill_path = root / manifest.skill.path
    try:
        skill_content = skill_path.read_bytes()
        verify_projectos_skill(skill_content, manifest, policy)
    except (OSError, ValidationError) as exc:
        raise SkillContractError("installed ProjectOS skill contract is invalid") from exc
    if profile.last_verified_manifest_hash is not None and (
        hashlib.sha256(manifest_content).hexdigest()
        != profile.last_verified_manifest_hash
    ):
        raise ValidationError("installed extension manifest does not match profile")
    return InstalledProjectOSExtension(
        root,
        manifest_path,
        skill_path,
        entry.bundle_sha256,
        entry,
        manifest,
        inventory,
    )


class SkillDiscoveryService:
    def resolve(
        self,
        target: FixtureInstallationTarget,
        profile_path: Path,
        store: LocalAdoptionStore,
        runner: SchedulerRunner,
        policy: ArtifactPolicy,
    ) -> SkillDiscoveryResult:
        try:
            registry = ExtensionRegistry.load(target.registry_path)
            entry = registry.projectos_entry()
        except ValidationError:
            return _failure("REGISTRY_INVALID", "registry")
        if entry is None or not entry.enabled:
            return _failure("REGISTRY_DISABLED", "registry")

        try:
            installed = load_installed_extension(target, store.profile, policy)
        except SkillContractError:
            return _failure("SKILL_CONTRACT_INVALID", "skill")
        except ValidationError:
            return _failure("INVENTORY_MISMATCH", "inventory")

        selected_profile_path = Path(profile_path)
        try:
            if (
                selected_profile_path.is_symlink()
                or selected_profile_path.resolve(strict=False)
                != (store.root / "machine-profile.json").resolve(strict=False)
            ):
                raise ValidationError("machine profile path is invalid")
            profile = store.load_profile(selected_profile_path)
            if (
                machine_profile_mapping(profile)
                != machine_profile_mapping(store.profile)
                or Path(str(profile.contextos_root)).resolve(strict=False)
                != target.root.resolve(strict=False)
                or Path(str(profile.extensions_root)).resolve(strict=False)
                != target.extensions_root.resolve(strict=False)
            ):
                raise ValidationError("machine profile does not match installation")
            config = ProjectOSGoogleConfig.load(
                Path(str(profile.config_path)), family=profile.host_family
            )
            if (
                Path(config.path).is_symlink()
                or config.machine_id != profile.machine_id
                or not config.google_enabled
                or not config.google_write_enabled
            ):
                raise ValidationError("Google configuration does not match profile")
        except ValidationError:
            return _failure("PROFILE_UNAVAILABLE", "profile")

        database: ProjectOSDatabase | None = None
        actual_schema_version = 0
        try:
            database = ProjectOSDatabase.open_existing(
                Path(str(profile.database_path)), read_only=True
            )
            actual_schema_version = database.schema_version()
            if not ProjectOSDoctor(database).check().healthy:
                raise ValidationError("database health check failed")
            binding = GoogleBindingRepository(database).get(config.binding_id)
            owners = database.connection.execute(
                "SELECT email FROM users WHERE protected_owner=1 AND active=1"
            ).fetchall()
            if binding is None or (
                binding.environment != config.environment
                or binding.spreadsheet_id != config.spreadsheet_id
                or binding.contract_version != config.contract_version
                or binding.credential_id != config.credential_reference_id
                or not binding.enabled
                or not binding.write_enabled
                or len(owners) != 1
                or owners[0]["email"] != config.expected_owner_email
            ):
                raise ValidationError("database binding does not match configuration")
        except (MigrationError, ValidationError, sqlite3.DatabaseError, OSError):
            return _failure("DATABASE_UNHEALTHY", "database")
        finally:
            if database is not None:
                database.close()

        try:
            adapter = adapter_for(profile)
            definition = adapter.render(profile, selected_profile_path)
            adapter.verify(definition, profile, selected_profile_path)
            inspection = runner.perform(SchedulerAction.INSPECT, definition)
            if (
                inspection.state is not SchedulerState.ENABLED
                or inspection.definition_sha256 != definition.sha256
            ):
                raise ValidationError("scheduler is not active")
        except (TypeError, ValueError, ValidationError):
            return _failure("SCHEDULER_INACTIVE", "scheduler")

        return SkillDiscoveryResult(
            DiscoveredSkill(
                installed.manifest.skill.skill_id,
                installed.manifest.skill.version,
                installed.skill_path,
                effective_capabilities(installed.manifest, actual_schema_version),
                AdapterInvocation(
                    ("projectos", "runtime", "sync"),
                    ("scheduler", "skill"),
                ),
            ),
            None,
        )
