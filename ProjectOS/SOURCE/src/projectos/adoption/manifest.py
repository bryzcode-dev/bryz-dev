from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Mapping

from projectos.adoption.host import HostFamily
from projectos.errors import ValidationError
from projectos.validation import reject_secret_material, require_text


EXTENSION_MANIFEST_VERSION = 1
BUNDLE_FORMAT_VERSION = 1
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_COMMANDS = {
    "health",
    "maintenance",
    "rollback",
    "sync",
    "uninstall",
    "upgrade",
}
_ALLOWED_CAPABILITIES = {
    "conflicts",
    "credential-usage",
    "health",
    "inspect-project",
    "list-deployments",
    "locate-assets",
    "register-project",
    "status",
    "sync",
    "trace-connections",
    "looker-status",
    "looker-assets",
    "looker-dependencies",
    "looker-findings",
    "looker-impact",
    "looker-reconciliation",
}
LOOKER_CAPABILITIES = frozenset(
    {
        "looker-status",
        "looker-assets",
        "looker-dependencies",
        "looker-findings",
        "looker-impact",
        "looker-reconciliation",
    }
)


def _portable_relative(value: str, field: str) -> str:
    text = require_text(value, field)
    posix = PurePosixPath(text)
    windows = PureWindowsPath(text)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or "\\" in text
        or any(part == ".." for part in posix.parts)
    ):
        raise ValidationError(f"{field} must be a portable relative path")
    return posix.as_posix()


@dataclass(frozen=True)
class SkillDeclaration:
    skill_id: str
    version: str
    path: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class CompatibilityDeclaration:
    contextos_min_version: str
    contextos_max_exclusive: str
    extension_contract_version: int
    supported_hosts: tuple[HostFamily, ...]


@dataclass(frozen=True)
class CommandDeclaration:
    name: str
    argv: tuple[str, ...]
    state_changing: bool


@dataclass(frozen=True)
class PayloadEntry:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ExtensionManifest:
    manifest_version: int
    bundle_format_version: int
    extension_id: str
    product_version: str
    created_at: str
    compatibility: CompatibilityDeclaration
    skill: SkillDeclaration
    commands: tuple[CommandDeclaration, ...]
    database_schema_version: int
    migration_status: str
    machine_profile_reference: str
    scheduler_required: bool
    safe_google_references: tuple[tuple[str, str], ...]
    adoption_state: str
    payload: tuple[PayloadEntry, ...]

    def validate(self) -> None:
        if (
            type(self.manifest_version) is not int
            or type(self.bundle_format_version) is not int
            or type(self.database_schema_version) is not int
            or type(self.scheduler_required) is not bool
        ):
            raise ValidationError("extension manifest field type is invalid")
        if self.manifest_version != EXTENSION_MANIFEST_VERSION:
            raise ValidationError("manifest_version is incompatible")
        if self.bundle_format_version != BUNDLE_FORMAT_VERSION:
            raise ValidationError("bundle_format_version is incompatible")
        if self.extension_id != "projectos":
            raise ValidationError("extension_id must be projectos")
        if not _VERSION.fullmatch(self.product_version):
            raise ValidationError("product_version is invalid")
        require_text(self.created_at, "created_at")
        compatibility = self.compatibility
        if not _VERSION.fullmatch(compatibility.contextos_min_version) or not _VERSION.fullmatch(
            compatibility.contextos_max_exclusive
        ):
            raise ValidationError("ContextOS compatibility versions are invalid")
        if (
            type(compatibility.extension_contract_version) is not int
            or compatibility.extension_contract_version != 1
        ):
            raise ValidationError("extension contract version is incompatible")
        if set(compatibility.supported_hosts) != {HostFamily.MACOS, HostFamily.WINDOWS}:
            raise ValidationError("supported_hosts must include macos and windows")
        if self.skill.skill_id != "projectos" or not _VERSION.fullmatch(self.skill.version):
            raise ValidationError("skill declaration is invalid")
        _portable_relative(self.skill.path, "skill path")
        if not self.skill.capabilities or any(
            item not in _ALLOWED_CAPABILITIES for item in self.skill.capabilities
        ):
            raise ValidationError("skill capability is not allowlisted")
        if LOOKER_CAPABILITIES.intersection(self.skill.capabilities) and self.database_schema_version < 3:
            raise ValidationError("Looker capabilities require database schema 3")
        command_names: set[str] = set()
        for command in self.commands:
            if type(command.state_changing) is not bool:
                raise ValidationError("command type is invalid")
            if command.name not in _ALLOWED_COMMANDS or command.name in command_names:
                raise ValidationError("command is not allowlisted or is duplicated")
            command_names.add(command.name)
            if not command.argv or command.argv[0] != "projectos" or any(
                not isinstance(item, str) or not item.strip() for item in command.argv
            ):
                raise ValidationError("command arguments are invalid")
        if self.database_schema_version < 1:
            raise ValidationError("database_schema_version is invalid")
        if self.migration_status not in {"CURRENT", "PENDING"}:
            raise ValidationError("migration_status is invalid")
        _portable_relative(self.machine_profile_reference, "machine_profile_reference")
        if type(self.scheduler_required) is not bool:
            raise ValidationError("scheduler_required is invalid")
        if self.adoption_state not in {"STAGED", "ADOPTED", "DISABLED"}:
            raise ValidationError("adoption_state is invalid")
        references = dict(self.safe_google_references)
        reject_secret_material(references)
        seen: set[str] = set()
        for entry in self.payload:
            name = _portable_relative(entry.path, "payload path")
            folded = name.casefold()
            if folded in seen:
                raise ValidationError("payload contains duplicate paths")
            seen.add(folded)
            if type(entry.size) is not int or not _SHA256.fullmatch(entry.sha256) or entry.size < 0:
                raise ValidationError("payload entry is invalid")
        if self.payload:
            paths = {entry.path for entry in self.payload}
            if self.skill.path not in paths:
                raise ValidationError("skill path is missing from payload")

    def to_mapping(self) -> dict[str, object]:
        return {
            "manifest_version": self.manifest_version,
            "bundle_format_version": self.bundle_format_version,
            "extension_id": self.extension_id,
            "product_version": self.product_version,
            "created_at": self.created_at,
            "compatibility": {
                "contextos_min_version": self.compatibility.contextos_min_version,
                "contextos_max_exclusive": self.compatibility.contextos_max_exclusive,
                "extension_contract_version": self.compatibility.extension_contract_version,
                "supported_hosts": [item.value for item in self.compatibility.supported_hosts],
            },
            "skill": {
                "skill_id": self.skill.skill_id,
                "version": self.skill.version,
                "path": self.skill.path,
                "capabilities": list(self.skill.capabilities),
            },
            "commands": [
                {
                    "name": item.name,
                    "argv": list(item.argv),
                    "state_changing": item.state_changing,
                }
                for item in self.commands
            ],
            "database_schema_version": self.database_schema_version,
            "migration_status": self.migration_status,
            "machine_profile_reference": self.machine_profile_reference,
            "scheduler_required": self.scheduler_required,
            "safe_google_references": dict(self.safe_google_references),
            "adoption_state": self.adoption_state,
            "payload": [
                {"path": item.path, "sha256": item.sha256, "size": item.size}
                for item in self.payload
            ],
        }

    def canonical_bytes(self) -> bytes:
        self.validate()
        return (
            json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        ).encode("utf-8")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ExtensionManifest":
        reject_secret_material(value)
        expected = {
            "manifest_version",
            "bundle_format_version",
            "extension_id",
            "product_version",
            "created_at",
            "compatibility",
            "skill",
            "commands",
            "database_schema_version",
            "migration_status",
            "machine_profile_reference",
            "scheduler_required",
            "safe_google_references",
            "adoption_state",
            "payload",
        }
        if set(value) != expected:
            raise ValidationError("extension manifest fields are invalid")
        try:
            compatibility_value = value["compatibility"]
            skill_value = value["skill"]
            commands_value = value["commands"]
            references_value = value["safe_google_references"]
            payload_value = value["payload"]
            if not isinstance(compatibility_value, Mapping) or not isinstance(skill_value, Mapping):
                raise TypeError
            if not isinstance(commands_value, list) or not isinstance(payload_value, list):
                raise TypeError
            if not isinstance(references_value, Mapping):
                raise TypeError
            if any(
                type(value[field]) is not int
                for field in (
                    "manifest_version",
                    "bundle_format_version",
                    "database_schema_version",
                )
            ) or type(value["scheduler_required"]) is not bool:
                raise ValidationError("extension manifest field type is invalid")
            if type(compatibility_value.get("extension_contract_version")) is not int:
                raise ValidationError("extension manifest field type is invalid")
            for item in commands_value:
                if not isinstance(item, Mapping) or type(item.get("state_changing")) is not bool:
                    raise ValidationError("extension manifest command type is invalid")
            for item in payload_value:
                if not isinstance(item, Mapping) or type(item.get("size")) is not int:
                    raise ValidationError("extension manifest payload type is invalid")
            manifest = cls(
                int(value["manifest_version"]),
                int(value["bundle_format_version"]),
                str(value["extension_id"]),
                str(value["product_version"]),
                str(value["created_at"]),
                CompatibilityDeclaration(
                    str(compatibility_value["contextos_min_version"]),
                    str(compatibility_value["contextos_max_exclusive"]),
                    int(compatibility_value["extension_contract_version"]),
                    tuple(
                        HostFamily(str(item))
                        for item in compatibility_value["supported_hosts"]
                    ),
                ),
                SkillDeclaration(
                    str(skill_value["skill_id"]),
                    str(skill_value["version"]),
                    str(skill_value["path"]),
                    tuple(str(item) for item in skill_value["capabilities"]),
                ),
                tuple(
                    CommandDeclaration(
                        str(item["name"]),
                        tuple(str(argument) for argument in item["argv"]),
                        bool(item["state_changing"]),
                    )
                    for item in commands_value
                ),
                int(value["database_schema_version"]),
                str(value["migration_status"]),
                str(value["machine_profile_reference"]),
                bool(value["scheduler_required"]),
                tuple(sorted((str(key), str(nested)) for key, nested in references_value.items())),
                str(value["adoption_state"]),
                tuple(
                    PayloadEntry(str(item["path"]), str(item["sha256"]), int(item["size"]))
                    for item in payload_value
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("extension manifest is invalid") from exc
        manifest.validate()
        return manifest
