from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from projectos.adoption.host import HostFamily
from projectos.errors import ValidationError
from projectos.validation import reject_secret_material, require_text


_MACHINE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PARSERS = {"COUNT_SUMMARY", "TEST_SUMMARY", "STATUS_ONLY"}
_SHELL_TERMS = ("|", ">", "<", ";", "&&", "||", "`", "$(", "${")
_SECRET_ARGUMENTS = ("token", "secret", "password", "private-key", "apikey", "api-key")


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(f"{label} fields are invalid")
    reject_secret_material(value)
    return value


def _strings(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValidationError(f"{field} must be a non-empty list")
    result = tuple(require_text(item, field) for item in value if isinstance(item, str))
    if len(result) != len(value) or len(set(result)) != len(result):
        raise ValidationError(f"{field} values are invalid or duplicated")
    return result


@dataclass(frozen=True)
class ValidationCommand:
    command_id: str
    executable: str
    arguments: tuple[str, ...]
    working_directory: str
    timeout_seconds: int
    expected_exit_codes: tuple[int, ...]
    parser: str

    @classmethod
    def from_mapping(cls, value: Any) -> ValidationCommand:
        item = _exact(value, {"command_id", "executable", "arguments", "working_directory", "timeout_seconds", "expected_exit_codes", "parser"}, "validation command")
        command_id = require_text(str(item["command_id"]), "command_id")
        executable = require_text(str(item["executable"]), "executable")
        arguments = _strings(item["arguments"], "arguments", allow_empty=True)
        combined = (executable, *arguments)
        if any(any(term in argument for term in _SHELL_TERMS) for argument in combined):
            raise ValidationError("validation command shell syntax is prohibited")
        if any(any(secret in argument.casefold() for secret in _SECRET_ARGUMENTS) for argument in combined):
            raise ValidationError("validation command secret arguments are prohibited")
        timeout = item["timeout_seconds"]
        if type(timeout) is not int or not 1 <= timeout <= 600:
            raise ValidationError("validation command timeout must be from 1 through 600")
        exits = item["expected_exit_codes"]
        if not isinstance(exits, list) or not exits or any(type(code) is not int or not 0 <= code <= 255 for code in exits) or len(set(exits)) != len(exits):
            raise ValidationError("validation command exit codes are invalid")
        parser = str(item["parser"])
        if parser not in _PARSERS:
            raise ValidationError("validation command parser is not allowlisted")
        return cls(command_id, executable, arguments, require_text(str(item["working_directory"]), "working_directory"), timeout, tuple(exits), parser)

    def to_mapping(self) -> dict[str, Any]:
        return {"arguments": list(self.arguments), "command_id": self.command_id, "executable": self.executable, "expected_exit_codes": list(self.expected_exit_codes), "parser": self.parser, "timeout_seconds": self.timeout_seconds, "working_directory": self.working_directory}


@dataclass(frozen=True)
class CredentialReference:
    provider: str
    label: str
    storage_system: str
    storage_reference: str

    @classmethod
    def from_mapping(cls, value: Any) -> CredentialReference:
        item = _exact(value, {"provider", "label", "storage_system", "storage_reference"}, "credential reference")
        return cls(*(require_text(str(item[field]), field) for field in ("provider", "label", "storage_system", "storage_reference")))

    def to_mapping(self) -> dict[str, str]:
        return {"label": self.label, "provider": self.provider, "storage_reference": self.storage_reference, "storage_system": self.storage_system}


@dataclass(frozen=True)
class CollectorPaths:
    repository_root: Path
    output_root: Path


@dataclass(frozen=True)
class LookerIntake:
    source_machine_id: str
    host_family: HostFamily
    repository_root: str
    output_root: str
    git: Mapping[str, Any]
    master_sheet: Mapping[str, Any]
    gas: Mapping[str, Any]
    sync_script_paths: tuple[str, ...]
    scheduler_definition_paths: tuple[str, ...]
    validation_commands: tuple[ValidationCommand, ...]
    credential_references: tuple[CredentialReference, ...]
    schema_version: int = 1

    @classmethod
    def from_mapping(cls, value: Any) -> LookerIntake:
        fields = {"schema_version", "source_machine_id", "host_family", "repository_root", "output_root", "git", "master_sheet", "gas", "sync_script_paths", "scheduler_definition_paths", "validation_commands", "credential_references"}
        item = _exact(value, fields, "Looker intake")
        if item["schema_version"] != 1 or type(item["schema_version"]) is not int:
            raise ValidationError("Looker intake schema version is unsupported")
        machine = require_text(str(item["source_machine_id"]), "source_machine_id")
        if _MACHINE_ID.fullmatch(machine) is None:
            raise ValidationError("source_machine_id is invalid")
        try:
            host = HostFamily(str(item["host_family"]))
        except ValueError as exc:
            raise ValidationError("Looker intake host family is invalid") from exc
        git = dict(_exact(item["git"], {"remote", "primary_branch", "ownership_context"}, "git"))
        sheet = dict(_exact(item["master_sheet"], {"spreadsheet_id", "url", "tabs"}, "master sheet"))
        gas = dict(_exact(item["gas"], {"script_id", "deployment_ids", "source_root"}, "gas"))
        for field in ("remote", "primary_branch", "ownership_context"):
            git[field] = require_text(str(git[field]), field)
        for field in ("spreadsheet_id", "url"):
            sheet[field] = require_text(str(sheet[field]), field)
        sheet["tabs"] = list(_strings(sheet["tabs"], "tabs"))
        gas["script_id"] = require_text(str(gas["script_id"]), "script_id")
        gas["source_root"] = require_text(str(gas["source_root"]), "source_root")
        gas["deployment_ids"] = list(_strings(gas["deployment_ids"], "deployment_ids", allow_empty=True))
        commands_value = item["validation_commands"]
        references_value = item["credential_references"]
        if not isinstance(commands_value, list) or not isinstance(references_value, list):
            raise ValidationError("Looker intake sequence fields are invalid")
        commands = tuple(ValidationCommand.from_mapping(command) for command in commands_value)
        if len({command.command_id for command in commands}) != len(commands):
            raise ValidationError("validation command identifiers are duplicated")
        references = tuple(CredentialReference.from_mapping(reference) for reference in references_value)
        return cls(machine, host, require_text(str(item["repository_root"]), "repository_root"), require_text(str(item["output_root"]), "output_root"), git, sheet, gas, _strings(item["sync_script_paths"], "sync_script_paths", allow_empty=True), _strings(item["scheduler_definition_paths"], "scheduler_definition_paths", allow_empty=True), commands, references)

    def to_mapping(self) -> dict[str, Any]:
        return {"credential_references": [item.to_mapping() for item in self.credential_references], "gas": dict(self.gas), "git": dict(self.git), "host_family": self.host_family.value, "master_sheet": dict(self.master_sheet), "output_root": self.output_root, "repository_root": self.repository_root, "scheduler_definition_paths": list(self.scheduler_definition_paths), "schema_version": self.schema_version, "source_machine_id": self.source_machine_id, "sync_script_paths": list(self.sync_script_paths), "validation_commands": [item.to_mapping() for item in self.validation_commands]}

    def canonical_bytes(self) -> bytes:
        return _canonical(self.to_mapping())
