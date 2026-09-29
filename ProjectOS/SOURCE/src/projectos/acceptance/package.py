from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import socket
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path, PurePosixPath, PureWindowsPath

from projectos import __version__
from projectos.adoption.bundle import ArtifactPolicy, verify_extension_bundle
from projectos.acceptance.model import (
    ACCEPTANCE_TASKS,
    REQUIRED_ACCEPTANCE_CASES,
    AcceptanceManifest,
    ExtensionBundleMetadata,
    PackageMember,
    WheelMetadata,
)
from projectos.adoption.host import HostFamily
from projectos.errors import ValidationError
from projectos.validation import reject_secret_material


_ASSETS = {
    "macos/run-projectos-acceptance.sh": "macos/run-projectos-acceptance.sh",
    "windows/Run-ProjectOSAcceptance.ps1": "windows/Run-ProjectOSAcceptance.ps1",
    "docs/PHASE3D_HOST_OPERATIONS.md": "docs/PHASE3D_HOST_OPERATIONS.md",
}
_EXTENSION_BUNDLE = "projectos-extension.zip"
_FIXED_NAMES = {
    "acceptance-manifest.json",
    "SHA256SUMS.txt",
    _EXTENSION_BUNDLE,
    *_ASSETS,
}
_WINDOWS_HOME = re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _portable_name(name: str) -> str:
    if not name or "\\" in name:
        raise ValidationError("acceptance archive path must be portable and relative")
    posix = PurePosixPath(name)
    windows = PureWindowsPath(name)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or any(
        part in {"", ".", ".."} for part in posix.parts
    ):
        raise ValidationError("acceptance archive path must be portable and relative")
    return posix.as_posix()


def _inspect_text(name: str, content: bytes) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return
    reject_secret_material(text)
    forbidden = {str(Path.home()), getpass.getuser(), socket.gethostname()}
    if any(value and value in text for value in forbidden):
        raise ValidationError(f"acceptance member {name} contains a private identifier")
    if "/Users/" in text or _WINDOWS_HOME.search(text) or _EMAIL.search(text):
        raise ValidationError(f"acceptance member {name} contains a private identifier")


def _wheel_metadata(path: Path, content: bytes) -> WheelMetadata:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            folded: set[str] = set()
            for member in members:
                normalized = _portable_name(member.filename)
                if normalized.casefold() in folded:
                    raise ValidationError("wheel contains duplicate member paths")
                folded.add(normalized.casefold())
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ValidationError("wheel contains a symbolic link")
            if archive.testzip() is not None:
                raise ValidationError("wheel contains a corrupt member")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValidationError("wheel is unavailable or invalid") from exc
    return WheelMetadata(path.name, len(content), len(members), _sha256(content))


def _artifact_policy() -> ArtifactPolicy:
    return ArtifactPolicy((str(Path.home()), getpass.getuser(), socket.gethostname()))


def _extension_metadata(path: Path, content: bytes) -> ExtensionBundleMetadata:
    verification = verify_extension_bundle(path, _artifact_policy())
    manifest = verification.manifest
    if (
        manifest.extension_id != "projectos"
        or manifest.product_version != __version__
        or manifest.skill.version != __version__
    ):
        raise ValidationError("extension bundle release does not match ProjectOS")
    return ExtensionBundleMetadata(
        _EXTENSION_BUNDLE,
        len(content),
        verification.entry_count,
        _sha256(content),
        manifest.extension_id,
        manifest.product_version,
        _sha256(manifest.canonical_bytes()),
    )


def _created_at(value: datetime | str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValidationError("package creation timestamp must be UTC")
        if value.microsecond:
            raise ValidationError("package creation timestamp must use whole seconds")
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


@dataclass(frozen=True)
class AcceptancePackage:
    path: Path
    sha256: str
    size: int
    member_count: int
    manifest: AcceptanceManifest

    def extract_extension_bundle(self, destination: Path) -> Path:
        current = verify_acceptance_package(self.path)
        if current.sha256 != self.sha256:
            raise ValidationError("acceptance package changed after verification")
        target = Path(destination)
        if target.exists() or target.is_symlink():
            raise ValidationError("extension bundle destination must be new")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink():
            raise ValidationError("extension bundle destination parent cannot be a symlink")
        temporary_path: Path | None = None
        try:
            with zipfile.ZipFile(self.path) as archive:
                content = archive.read(_EXTENSION_BUNDLE)
            with tempfile.NamedTemporaryFile(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            metadata = _extension_metadata(temporary_path, content)
            if metadata != self.manifest.extension_bundle:
                raise ValidationError("extension bundle metadata changed after verification")
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return target


class AcceptancePackageBuilder:
    def build(
        self,
        wheel_path: Path,
        extension_bundle_path: Path,
        source_revision: str,
        created_at: datetime | str,
        output_path: Path,
    ) -> AcceptancePackage:
        wheel = Path(wheel_path)
        wheel_content = wheel.read_bytes()
        wheel_metadata = _wheel_metadata(wheel, wheel_content)
        extension_path = Path(extension_bundle_path)
        extension_content = extension_path.read_bytes()
        extension_metadata = _extension_metadata(extension_path, extension_content)
        asset_root = resources.files("projectos.acceptance").joinpath("assets")
        entries: dict[str, bytes] = {
            wheel.name: wheel_content,
            _EXTENSION_BUNDLE: extension_content,
        }
        for archive_name, resource_name in _ASSETS.items():
            resource = asset_root.joinpath(resource_name)
            if not resource.is_file():
                raise ValidationError(f"acceptance asset is missing: {archive_name}")
            content = resource.read_bytes()
            _inspect_text(archive_name, content)
            entries[archive_name] = content
        members = tuple(
            PackageMember(name, len(content), _sha256(content))
            for name, content in sorted(entries.items())
        )
        manifest = AcceptanceManifest.from_mapping(
            {
                "schema_version": 2,
                "projectos_version": __version__,
                "source_revision": source_revision,
                "wheel": wheel_metadata.to_mapping(),
                "extension_bundle": extension_metadata.to_mapping(),
                "supported_hosts": [HostFamily.MACOS.value, HostFamily.WINDOWS.value],
                "python_contract": ">=3.11",
                "contextos_contract": ">=3.0.1,<4",
                "acceptance_tasks": ACCEPTANCE_TASKS,
                "required_cases": list(REQUIRED_ACCEPTANCE_CASES),
                "created_at": _created_at(created_at),
                "members": [item.to_mapping() for item in members],
            }
        )
        entries["acceptance-manifest.json"] = manifest.canonical_bytes()
        entries["SHA256SUMS.txt"] = "".join(
            f"{_sha256(content)}  {name}\n"
            for name, content in sorted(entries.items())
        ).encode("ascii")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
            with zipfile.ZipFile(temporary_path, "w") as archive:
                for name, content in sorted(entries.items()):
                    archive.writestr(_zip_info(name), content)
            verified = verify_acceptance_package(temporary_path)
            os.replace(temporary_path, output)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return AcceptancePackage(output, verified.sha256, output.stat().st_size, verified.member_count, manifest)


def verify_acceptance_package(path: Path) -> AcceptancePackage:
    package = Path(path)
    try:
        with zipfile.ZipFile(package) as archive:
            members = archive.infolist()
            names: list[str] = []
            folded: set[str] = set()
            for member in members:
                normalized = _portable_name(member.filename)
                if normalized.casefold() in folded:
                    raise ValidationError("acceptance package contains duplicate paths")
                folded.add(normalized.casefold())
                if stat.S_ISLNK(member.external_attr >> 16) or not stat.S_ISREG(member.external_attr >> 16):
                    raise ValidationError("acceptance package members must be regular files")
                names.append(normalized)
            if names.count("acceptance-manifest.json") != 1:
                raise ValidationError("acceptance manifest is missing or duplicated")
            raw_manifest = archive.read("acceptance-manifest.json")
            try:
                mapping = json.loads(raw_manifest)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationError("acceptance manifest is invalid") from exc
            manifest = AcceptanceManifest.from_mapping(mapping)
            if raw_manifest != manifest.canonical_bytes():
                raise ValidationError("acceptance manifest is not canonical")
            expected = _FIXED_NAMES | {manifest.wheel.filename}
            if set(names) != expected or len(names) != len(expected):
                raise ValidationError("acceptance package inventory is invalid")
            inventory = {item.path: item for item in manifest.members}
            expected_inventory = _ASSETS.keys() | {
                manifest.wheel.filename,
                _EXTENSION_BUNDLE,
            }
            if set(inventory) != set(expected_inventory):
                raise ValidationError("acceptance manifest inventory is invalid")
            contents: dict[str, bytes] = {}
            for name, item in inventory.items():
                content = archive.read(name)
                contents[name] = content
                if len(content) != item.size or _sha256(content) != item.sha256:
                    raise ValidationError("acceptance package member hash or size mismatch")
                if name != manifest.wheel.filename:
                    _inspect_text(name, content)
            wheel = contents[manifest.wheel.filename]
            if len(wheel) != manifest.wheel.size or _sha256(wheel) != manifest.wheel.sha256:
                raise ValidationError("acceptance wheel hash or size mismatch")
            with tempfile.NamedTemporaryFile(suffix=".whl") as temporary:
                temporary.write(wheel)
                temporary.flush()
                actual_wheel = _wheel_metadata(Path(temporary.name), wheel)
            if actual_wheel.member_count != manifest.wheel.member_count:
                raise ValidationError("acceptance wheel member count mismatch")
            extension_content = contents[_EXTENSION_BUNDLE]
            with tempfile.NamedTemporaryFile(suffix=".zip") as temporary:
                temporary.write(extension_content)
                temporary.flush()
                actual_extension = _extension_metadata(Path(temporary.name), extension_content)
            if actual_extension != manifest.extension_bundle:
                raise ValidationError("acceptance extension bundle metadata mismatch")
            expected_sums = "".join(
                f"{_sha256(archive.read(name))}  {name}\n"
                for name in sorted(expected - {"SHA256SUMS.txt"})
            ).encode("ascii")
            if archive.read("SHA256SUMS.txt") != expected_sums:
                raise ValidationError("acceptance package checksum inventory is invalid")
            _inspect_text("acceptance-manifest.json", raw_manifest)
            _inspect_text("SHA256SUMS.txt", archive.read("SHA256SUMS.txt"))
            if archive.testzip() is not None:
                raise ValidationError("acceptance package contains a corrupt member")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValidationError("acceptance package is unavailable or invalid") from exc
    content = package.read_bytes()
    return AcceptancePackage(package, _sha256(content), len(content), len(members), manifest)
