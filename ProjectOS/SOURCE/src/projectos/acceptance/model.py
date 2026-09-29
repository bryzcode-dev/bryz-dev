from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from projectos.adoption.host import HostFamily
from projectos.errors import ValidationError
from projectos.validation import canonical_json, reject_secret_material, require_text


REQUIRED_ACCEPTANCE_CASES: tuple[str, ...] = (
    "package_integrity",
    "standard_user_non_elevated",
    "fixture_authority",
    "local_path_separation",
    "definition_structural_equivalence",
    "native_install_disabled",
    "native_enable",
    "immediate_trigger",
    "common_lock_contention",
    "native_non_overlap",
    "two_hour_configuration",
    "eligible_resume_configuration",
    "skill_discovery",
    "deactivation_order",
    "native_disable_remove",
    "definition_rollback",
    "retained_database_health",
    "identifier_secret_symlink_scan",
)

ACCEPTANCE_TASKS = {
    HostFamily.MACOS.value: "com.contextos.projectos.acceptance.sync",
    HostFamily.WINDOWS.value: r"ContextOS\ProjectOS\Acceptance\Sync",
}


class SupportState(str, Enum):
    SIMULATED = "SIMULATED"
    MACOS_VERIFIED = "MACOS_VERIFIED"
    WINDOWS_VERIFIED = "WINDOWS_VERIFIED"
    CROSS_PLATFORM_VERIFIED = "CROSS_PLATFORM_VERIFIED"


def _exact_fields(mapping: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(mapping) != expected:
        raise ValidationError(f"{label} fields are invalid")


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValidationError(f"{field} is invalid")
    return value


def _sha256(value: Any, field: str) -> str:
    text = require_text(str(value), field)
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise ValidationError(f"{field} must be a lowercase SHA-256 digest")
    return text


@dataclass(frozen=True)
class WheelMetadata:
    filename: str
    size: int
    member_count: int
    sha256: str

    @classmethod
    def from_mapping(cls, value: Any) -> WheelMetadata:
        if not isinstance(value, dict):
            raise ValidationError("wheel is invalid")
        _exact_fields(value, {"filename", "size", "member_count", "sha256"}, "wheel")
        filename = require_text(str(value["filename"]), "wheel filename")
        if "/" in filename or "\\" in filename or not filename.endswith(".whl"):
            raise ValidationError("wheel filename is invalid")
        return cls(
            filename,
            _integer(value["size"], "wheel size", 1),
            _integer(value["member_count"], "wheel member count", 1),
            _sha256(value["sha256"], "wheel sha256"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "member_count": self.member_count,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True)
class ExtensionBundleMetadata:
    filename: str
    size: int
    member_count: int
    sha256: str
    extension_id: str
    product_version: str
    manifest_sha256: str

    @classmethod
    def from_mapping(cls, value: Any) -> ExtensionBundleMetadata:
        if not isinstance(value, dict):
            raise ValidationError("extension bundle is invalid")
        _exact_fields(
            value,
            {
                "filename",
                "size",
                "member_count",
                "sha256",
                "extension_id",
                "product_version",
                "manifest_sha256",
            },
            "extension bundle",
        )
        filename = require_text(str(value["filename"]), "extension bundle filename")
        if filename != "projectos-extension.zip":
            raise ValidationError("extension bundle filename is invalid")
        extension_id = require_text(str(value["extension_id"]), "extension id")
        if extension_id != "projectos":
            raise ValidationError("extension bundle namespace is invalid")
        return cls(
            filename,
            _integer(value["size"], "extension bundle size", 1),
            _integer(value["member_count"], "extension bundle member count", 1),
            _sha256(value["sha256"], "extension bundle sha256"),
            extension_id,
            require_text(str(value["product_version"]), "extension product version"),
            _sha256(value["manifest_sha256"], "extension manifest sha256"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "extension_id": self.extension_id,
            "filename": self.filename,
            "manifest_sha256": self.manifest_sha256,
            "member_count": self.member_count,
            "product_version": self.product_version,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True)
class PackageMember:
    path: str
    size: int
    sha256: str

    @classmethod
    def from_mapping(cls, value: Any) -> PackageMember:
        if not isinstance(value, dict):
            raise ValidationError("package member is invalid")
        _exact_fields(value, {"path", "size", "sha256"}, "package member")
        path = require_text(str(value["path"]), "package member path")
        return cls(path, _integer(value["size"], "package member size"), _sha256(value["sha256"], "package member sha256"))

    def to_mapping(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class AcceptanceManifest:
    schema_version: int
    projectos_version: str
    source_revision: str
    wheel: WheelMetadata
    extension_bundle: ExtensionBundleMetadata
    supported_hosts: tuple[str, ...]
    python_contract: str
    contextos_contract: str
    acceptance_tasks: Mapping[str, str]
    required_cases: tuple[str, ...]
    created_at: str
    members: tuple[PackageMember, ...]

    @classmethod
    def from_mapping(cls, value: Any) -> AcceptanceManifest:
        if not isinstance(value, dict):
            raise ValidationError("acceptance manifest is invalid")
        _exact_fields(
            value,
            {
                "schema_version", "projectos_version", "source_revision", "wheel",
                "extension_bundle",
                "supported_hosts", "python_contract", "contextos_contract",
                "acceptance_tasks", "required_cases", "created_at", "members",
            },
            "acceptance manifest",
        )
        supported_hosts = value["supported_hosts"]
        acceptance_tasks = value["acceptance_tasks"]
        required_cases = value["required_cases"]
        members = value["members"]
        if supported_hosts != [HostFamily.MACOS.value, HostFamily.WINDOWS.value]:
            raise ValidationError("supported hosts are invalid")
        if acceptance_tasks != ACCEPTANCE_TASKS:
            raise ValidationError("acceptance task identifiers are invalid")
        if required_cases != list(REQUIRED_ACCEPTANCE_CASES):
            raise ValidationError("required acceptance cases are invalid")
        if not isinstance(members, list):
            raise ValidationError("package members are invalid")
        parsed_members = tuple(PackageMember.from_mapping(item) for item in members)
        paths = [item.path for item in parsed_members]
        if paths != sorted(paths) or len({item.casefold() for item in paths}) != len(paths):
            raise ValidationError("package members must be sorted and unique")
        source_revision = require_text(str(value["source_revision"]), "source revision")
        if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", source_revision) is None:
            raise ValidationError("source revision is invalid")
        created_at = require_text(str(value["created_at"]), "created at")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", created_at) is None:
            raise ValidationError("created at must be canonical UTC seconds")
        schema_version = _integer(value["schema_version"], "schema version", 1)
        if schema_version != 2:
            raise ValidationError("acceptance manifest schema version is unsupported")
        extension_bundle = ExtensionBundleMetadata.from_mapping(value["extension_bundle"])
        projectos_version = require_text(str(value["projectos_version"]), "ProjectOS version")
        if extension_bundle.product_version != projectos_version:
            raise ValidationError("extension bundle release does not match ProjectOS")
        manifest = cls(
            schema_version,
            projectos_version,
            source_revision,
            WheelMetadata.from_mapping(value["wheel"]),
            extension_bundle,
            tuple(supported_hosts),
            require_text(str(value["python_contract"]), "Python contract"),
            require_text(str(value["contextos_contract"]), "ContextOS contract"),
            dict(acceptance_tasks),
            tuple(required_cases),
            created_at,
            parsed_members,
        )
        reject_secret_material(manifest.to_mapping())
        return manifest

    def to_mapping(self) -> dict[str, Any]:
        return {
            "acceptance_tasks": dict(self.acceptance_tasks),
            "contextos_contract": self.contextos_contract,
            "created_at": self.created_at,
            "extension_bundle": self.extension_bundle.to_mapping(),
            "members": [item.to_mapping() for item in self.members],
            "projectos_version": self.projectos_version,
            "python_contract": self.python_contract,
            "required_cases": list(self.required_cases),
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "supported_hosts": list(self.supported_hosts),
            "wheel": self.wheel.to_mapping(),
        }

    def canonical_bytes(self) -> bytes:
        return (canonical_json(self.to_mapping()) + "\n").encode("utf-8")
