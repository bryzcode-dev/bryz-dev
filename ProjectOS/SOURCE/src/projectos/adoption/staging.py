from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from projectos.adoption.bundle import (
    ArtifactPolicy,
    read_verified_bundle,
)
from projectos.adoption.fixture import FixtureInstallationTarget
from projectos.adoption.manifest import ExtensionManifest
from projectos.adoption.profile import MachineProfile, machine_profile_mapping
from projectos.adoption.store import LocalAdoptionStore, SnapshotEntry
from projectos.errors import ValidationError


def _version(value: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(item) for item in value.split("."))
    except ValueError as exc:
        raise ValidationError("version is incompatible") from exc
    if len(parts) != 3:
        raise ValidationError("version is incompatible")
    return parts


def check_extension_compatibility(
    manifest: ExtensionManifest, profile: MachineProfile
) -> None:
    compatibility = manifest.compatibility
    if (
        profile.host_family not in compatibility.supported_hosts
        or profile.extension_contract_version != compatibility.extension_contract_version
        or not (
            _version(compatibility.contextos_min_version)
            <= _version(profile.contextos_version)
            < _version(compatibility.contextos_max_exclusive)
        )
    ):
        raise ValidationError("extension manifest and machine profile are incompatible")


def inventory_extension(
    root: Path, policy: ArtifactPolicy
) -> tuple[SnapshotEntry, ...]:
    if not root.is_dir() or root.is_symlink():
        raise ValidationError("staged extension root is invalid")
    entries: list[SnapshotEntry] = []
    for directory, directories, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in directories:
            if (directory_path / name).is_symlink():
                raise ValidationError("staged extension cannot contain symlinks")
        for name in files:
            path = directory_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ValidationError("staged extension cannot contain symlinks")
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise ValidationError("staged extension inventory is unavailable") from exc
            policy.inspect(relative, path, content)
            entries.append(
                SnapshotEntry(
                    relative,
                    hashlib.sha256(content).hexdigest(),
                    len(content),
                )
            )
    return tuple(sorted(entries, key=lambda item: item.path))


def expected_extension_inventory(
    manifest: ExtensionManifest,
) -> tuple[SnapshotEntry, ...]:
    manifest_bytes = manifest.canonical_bytes()
    entries = [
        SnapshotEntry(
            "manifest.json",
            hashlib.sha256(manifest_bytes).hexdigest(),
            len(manifest_bytes),
        )
    ]
    entries.extend(
        SnapshotEntry(item.path, item.sha256, item.size) for item in manifest.payload
    )
    return tuple(sorted(entries, key=lambda item: item.path))


@dataclass(frozen=True)
class StagedExtension:
    transaction_id: str
    root: Path
    version_name: str
    bundle_sha256: str
    manifest: ExtensionManifest
    inventory: tuple[SnapshotEntry, ...]
    profile: MachineProfile
    policy: ArtifactPolicy

    @property
    def relative_version_path(self) -> str:
        return f"projectos/versions/{self.version_name}"

    @property
    def relative_manifest_path(self) -> str:
        return f"{self.relative_version_path}/manifest.json"


def load_staged_extension(
    store: LocalAdoptionStore,
    profile: MachineProfile,
    transaction_id: str,
    relative_version_path: str,
    bundle_sha256: str,
    policy: ArtifactPolicy,
) -> StagedExtension:
    parts = relative_version_path.split("/")
    if len(parts) != 3 or parts[:2] != ["projectos", "versions"]:
        raise ValidationError("staged extension path is invalid")
    root = store.transaction_root(transaction_id) / "staged" / relative_version_path
    try:
        value = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("staged extension manifest is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValidationError("staged extension manifest is unavailable or invalid")
    manifest = ExtensionManifest.from_mapping(value)
    expected_name = f"{manifest.product_version}-{bundle_sha256[:12]}"
    if parts[-1] != expected_name:
        raise ValidationError("staged extension path does not match bundle")
    staged = StagedExtension(
        transaction_id,
        root,
        expected_name,
        bundle_sha256,
        manifest,
        expected_extension_inventory(manifest),
        profile,
        policy,
    )
    return verify_staged_extension(staged, profile, policy)


def stage_extension(
    bundle_path: Path,
    profile: MachineProfile,
    store: LocalAdoptionStore,
    transaction_id: str,
    policy: ArtifactPolicy,
) -> StagedExtension:
    if machine_profile_mapping(store.profile) != machine_profile_mapping(profile):
        raise ValidationError("staging profile is incompatible with local store")
    verified = read_verified_bundle(Path(bundle_path), policy)
    manifest = verified.verification.manifest
    check_extension_compatibility(manifest, profile)
    version_name = f"{manifest.product_version}-{verified.verification.sha256[:12]}"
    root = (
        store.transaction_root(transaction_id)
        / "staged"
        / "projectos"
        / "versions"
        / version_name
    )
    staged = StagedExtension(
        transaction_id,
        root,
        version_name,
        verified.verification.sha256,
        manifest,
        expected_extension_inventory(manifest),
        profile,
        policy,
    )
    if root.exists():
        return verify_staged_extension(staged, profile, policy)
    root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{version_name}.", suffix=".tmp", dir=root.parent)
    )
    try:
        with zipfile.ZipFile(io.BytesIO(verified.content)) as archive:
            for member in archive.infolist():
                name = policy.validate_name(member.filename)
                if member.is_dir() or stat.S_ISLNK(member.external_attr >> 16):
                    raise ValidationError("extension bundle cannot contain links or directories")
                destination = temporary / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(member))
        if inventory_extension(temporary, policy) != staged.inventory:
            raise ValidationError("staged extension inventory does not match manifest")
        os.replace(temporary, root)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return verify_staged_extension(staged, profile, policy)


def verify_staged_extension(
    staged: StagedExtension,
    profile: MachineProfile,
    policy: ArtifactPolicy,
) -> StagedExtension:
    if profile.installation_id != staged.profile.installation_id:
        raise ValidationError("staged extension profile is incompatible")
    check_extension_compatibility(staged.manifest, profile)
    if inventory_extension(staged.root, policy) != staged.inventory:
        raise ValidationError("staged extension inventory does not match")
    return staged


def copy_verified_version(
    staged: StagedExtension, target: FixtureInstallationTarget
) -> Path:
    verify_staged_extension(staged, staged.profile, staged.policy)
    destination = target.extensions_root / staged.relative_version_path
    target.assert_managed_path(destination)
    if destination.exists():
        if inventory_extension(destination, staged.policy) != staged.inventory:
            raise ValidationError("existing extension version is nonidentical")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{staged.version_name}.", suffix=".tmp", dir=destination.parent
        )
    )
    try:
        for entry in staged.inventory:
            source = staged.root / entry.path
            if source.is_symlink():
                raise ValidationError("staged extension cannot contain symlinks")
            target_path = temporary / entry.path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target_path)
        if inventory_extension(temporary, staged.policy) != staged.inventory:
            raise ValidationError("copied extension inventory does not match")
        try:
            os.replace(temporary, destination)
        except FileExistsError:
            if inventory_extension(destination, staged.policy) != staged.inventory:
                raise ValidationError("existing extension version is nonidentical")
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination
