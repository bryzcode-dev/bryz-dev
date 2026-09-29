from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable

from projectos.adoption.manifest import ExtensionManifest, PayloadEntry
from projectos.errors import ValidationError
from projectos.validation import reject_secret_material


_WINDOWS_HOME = re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE)


@dataclass(frozen=True)
class BundleResult:
    path: Path
    sha256: str
    size: int
    entry_count: int
    manifest: ExtensionManifest


@dataclass(frozen=True)
class BundleVerification:
    ok: bool
    sha256: str
    entry_count: int
    manifest: ExtensionManifest


@dataclass(frozen=True)
class VerifiedBundleContent:
    verification: BundleVerification
    content: bytes


class ArtifactPolicy:
    def __init__(self, forbidden_values: Iterable[str]):
        self.forbidden_values = tuple(
            value.encode("utf-8").lower() for value in forbidden_values if value
        )

    @staticmethod
    def validate_name(relative_name: str) -> str:
        if not relative_name or "\\" in relative_name:
            raise ValidationError("archive path must be portable and relative")
        posix = PurePosixPath(relative_name)
        windows = PureWindowsPath(relative_name)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or windows.drive
            or any(part in {"", ".", ".."} for part in posix.parts)
        ):
            raise ValidationError("archive path must be portable and relative")
        return posix.as_posix()

    def inspect(self, relative_name: str, source_path: Path, content: bytes) -> None:
        self.validate_name(relative_name)
        if source_path.is_symlink():
            raise ValidationError("bundle payload cannot contain symlinks")
        lowered = content.lower()
        if any(value in lowered for value in self.forbidden_values):
            raise ValidationError("bundle payload contains a forbidden host identifier")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return
        reject_secret_material(text)
        if "/Users/" in text or _WINDOWS_HOME.search(text):
            raise ValidationError("bundle payload contains a resolved home path")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100644 & 0xFFFF) << 16
    return info


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _payload(root: Path, policy: ArtifactPolicy) -> dict[str, bytes]:
    if not root.is_dir() or root.is_symlink():
        raise ValidationError("payload root must be a non-symlink directory")
    entries: dict[str, bytes] = {}
    folded: set[str] = set()
    for directory, directories, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in directories:
            if (directory_path / name).is_symlink():
                raise ValidationError("bundle payload cannot contain symlinks")
        for name in files:
            source = directory_path / name
            relative = source.relative_to(root).as_posix()
            normalized = policy.validate_name(relative)
            key = normalized.casefold()
            if key in folded:
                raise ValidationError("bundle payload contains duplicate paths")
            folded.add(key)
            content = source.read_bytes()
            policy.inspect(normalized, source, content)
            entries[normalized] = content
    return entries


class ExtensionBundleBuilder:
    def build(
        self,
        manifest: ExtensionManifest,
        payload_root: Path,
        output_path: Path,
        policy: ArtifactPolicy,
    ) -> BundleResult:
        manifest.validate()
        files = _payload(Path(payload_root), policy)
        payload_entries = tuple(
            PayloadEntry(name, _sha256(content), len(content))
            for name, content in sorted(files.items())
        )
        final_manifest = replace(manifest, payload=payload_entries)
        manifest_bytes = final_manifest.canonical_bytes()
        policy.inspect("manifest.json", Path("manifest.json"), manifest_bytes)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
            with zipfile.ZipFile(temporary_path, "w") as archive:
                archive.writestr(_zip_info("manifest.json"), manifest_bytes)
                for name, content in sorted(files.items()):
                    archive.writestr(_zip_info(name), content)
            verification = verify_extension_bundle(temporary_path, policy)
            os.replace(temporary_path, output)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return BundleResult(
            output,
            verification.sha256,
            output.stat().st_size,
            verification.entry_count,
            final_manifest,
        )


def verify_extension_bundle(path: Path, policy: ArtifactPolicy) -> BundleVerification:
    bundle = Path(path)
    try:
        with zipfile.ZipFile(bundle) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            folded: set[str] = set()
            for member in members:
                name = member.filename
                normalized = policy.validate_name(name)
                key = normalized.casefold()
                if key in folded:
                    raise ValidationError("bundle contains duplicate archive paths")
                folded.add(key)
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ValidationError("bundle cannot contain symlink entries")
            if names.count("manifest.json") != 1:
                raise ValidationError("bundle manifest is missing or duplicated")
            manifest_bytes = archive.read("manifest.json")
            try:
                mapping = json.loads(manifest_bytes)
            except json.JSONDecodeError as exc:
                raise ValidationError("bundle manifest is invalid") from exc
            if not isinstance(mapping, dict):
                raise ValidationError("bundle manifest is invalid")
            manifest = ExtensionManifest.from_mapping(mapping)
            if manifest_bytes != manifest.canonical_bytes():
                raise ValidationError("bundle manifest is not canonical")
            policy.inspect("manifest.json", Path("manifest.json"), manifest_bytes)
            inventory = {entry.path: entry for entry in manifest.payload}
            if set(names) - {"manifest.json"} != set(inventory):
                raise ValidationError("bundle inventory does not match archive")
            for name, entry in inventory.items():
                content = archive.read(name)
                policy.inspect(name, Path(name), content)
                if len(content) != entry.size or _sha256(content) != entry.sha256:
                    raise ValidationError("bundle payload hash or size mismatch")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValidationError("extension bundle is unavailable or invalid") from exc
    content = bundle.read_bytes()
    return BundleVerification(True, _sha256(content), len(manifest.payload), manifest)


def read_verified_bundle(
    path: Path, policy: ArtifactPolicy
) -> VerifiedBundleContent:
    verification = verify_extension_bundle(path, policy)
    try:
        content = Path(path).read_bytes()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if archive.testzip() is not None:
                raise ValidationError("extension bundle member is corrupt")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValidationError("extension bundle is unavailable or invalid") from exc
    if _sha256(content) != verification.sha256:
        raise ValidationError("extension bundle changed after verification")
    return VerifiedBundleContent(verification, content)
