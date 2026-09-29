from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path, PurePath
from typing import Any, Mapping

from projectos.acceptance.authority import AcceptanceTarget
from projectos.acceptance.model import ACCEPTANCE_TASKS, REQUIRED_ACCEPTANCE_CASES
from projectos.adoption.profile import (
    MachineProfile,
    machine_profile_from_mapping,
    machine_profile_mapping,
)
from projectos.errors import ValidationError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def acceptance_machine_profile(profile: MachineProfile) -> MachineProfile:
    executable = str(profile.python_executable)
    return replace(
        profile,
        projectos_entrypoint=(executable, "-m", "projectos.acceptance_probe"),
        scheduler_task_id=ACCEPTANCE_TASKS[profile.host_family.value],
    )


def _safe_id(value: str, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValidationError(f"{field} is invalid")
    return value


def _digest(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValidationError(f"{field} is invalid")
    return value


@dataclass(frozen=True)
class AcceptanceProfile:
    target: AcceptanceTarget
    machine_profile: MachineProfile
    source_revision: str
    release_sha256: str
    wheel_sha256: str
    extension_bundle_sha256: str
    preparation_id: str
    definition_transaction_id: str
    activation_id: str
    required_cases: tuple[str, ...]
    evidence_spool: PurePath
    max_probe_seconds: int

    @classmethod
    def from_machine_profile(
        cls,
        machine_profile: MachineProfile,
        target: AcceptanceTarget,
        *,
        source_revision: str,
        release_sha256: str,
        wheel_sha256: str,
        extension_bundle_sha256: str | None = None,
        preparation_id: str = "legacy-preparation",
        definition_transaction_id: str,
        activation_id: str,
        max_probe_seconds: int = 120,
    ) -> AcceptanceProfile:
        production_entrypoint = (
            str(machine_profile.python_executable), "-m", "projectos.cli"
        )
        production_task = (
            r"ContextOS\ProjectOS\Sync"
            if machine_profile.host_family.value == "windows"
            else "com.contextos.projectos.sync"
        )
        acceptance_entrypoint = (
            str(machine_profile.python_executable), "-m", "projectos.acceptance_probe"
        )
        acceptance_task = ACCEPTANCE_TASKS[machine_profile.host_family.value]
        pair = (machine_profile.projectos_entrypoint, machine_profile.scheduler_task_id)
        if pair == (production_entrypoint, production_task):
            selected = acceptance_machine_profile(machine_profile)
        elif pair == (acceptance_entrypoint, acceptance_task):
            selected = machine_profile
        else:
            raise ValidationError("machine profile must use a matched acceptance task and entrypoint")
        if selected.host_family is not target.host_family:
            raise ValidationError("acceptance profile host family does not match target")
        if str(selected.runtime_root) != str(target.runtime_root):
            raise ValidationError("machine profile runtime does not match acceptance runtime")
        for value in (
            selected.database_path,
            selected.config_path,
            selected.lock_path,
            selected.log_root,
            selected.staging_root,
        ):
            target.assert_runtime_path(value)
        if _REVISION.fullmatch(source_revision) is None:
            raise ValidationError("source revision is invalid")
        if type(max_probe_seconds) is not int or not 1 <= max_probe_seconds <= 600:
            raise ValidationError("maximum probe duration is invalid")
        path_type = type(selected.runtime_root)
        evidence_spool = path_type(str(selected.runtime_root)) / "acceptance/evidence-spool"
        return cls(
            target,
            selected,
            source_revision,
            _digest(release_sha256, "release sha256"),
            _digest(wheel_sha256, "wheel sha256"),
            _digest(
                extension_bundle_sha256 or wheel_sha256,
                "extension bundle sha256",
            ),
            _safe_id(preparation_id, "preparation id"),
            _safe_id(definition_transaction_id, "definition transaction id"),
            _safe_id(activation_id, "activation id"),
            REQUIRED_ACCEPTANCE_CASES,
            evidence_spool,
            max_probe_seconds,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "acceptance_id": self.target.acceptance_id,
            "acceptance_root": str(self.target.root),
            "activation_id": self.activation_id,
            "definition_transaction_id": self.definition_transaction_id,
            "evidence_spool": str(self.evidence_spool),
            "extension_bundle_sha256": self.extension_bundle_sha256,
            "format": "projectos-acceptance-profile-v2",
            "machine_profile": machine_profile_mapping(self.machine_profile),
            "max_probe_seconds": self.max_probe_seconds,
            "preparation_id": self.preparation_id,
            "receipt_id": self.target.receipt_id,
            "release_sha256": self.release_sha256,
            "required_cases": list(self.required_cases),
            "source_revision": self.source_revision,
            "wheel_sha256": self.wheel_sha256,
        }

    def canonical_bytes(self) -> bytes:
        return (json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], target: AcceptanceTarget) -> AcceptanceProfile:
        expected = {
            "acceptance_id", "acceptance_root", "activation_id", "definition_transaction_id",
            "evidence_spool", "format", "machine_profile", "max_probe_seconds",
            "preparation_id", "receipt_id", "release_sha256", "required_cases", "source_revision",
            "extension_bundle_sha256",
            "wheel_sha256",
        }
        if set(value) != expected or value.get("format") != "projectos-acceptance-profile-v2":
            raise ValidationError("acceptance profile fields are invalid")
        if value.get("acceptance_id") != target.acceptance_id or value.get("receipt_id") != target.receipt_id:
            raise ValidationError("acceptance profile target does not match")
        if value.get("acceptance_root") != str(target.root):
            raise ValidationError("acceptance profile root does not match")
        raw_profile = value.get("machine_profile")
        if not isinstance(raw_profile, dict):
            raise ValidationError("acceptance machine profile is invalid")
        production_mapping = dict(raw_profile)
        family = production_mapping.get("host_family")
        python = production_mapping.get("python_executable")
        production_mapping["projectos_entrypoint"] = [python, "-m", "projectos.cli"]
        production_mapping["scheduler_task_id"] = (
            r"ContextOS\ProjectOS\Sync" if family == "windows" else "com.contextos.projectos.sync"
        )
        production = machine_profile_from_mapping(production_mapping)
        result = cls.from_machine_profile(
            acceptance_machine_profile(production),
            target,
            source_revision=value["source_revision"],
            release_sha256=value["release_sha256"],
            wheel_sha256=value["wheel_sha256"],
            extension_bundle_sha256=value["extension_bundle_sha256"],
            preparation_id=value["preparation_id"],
            definition_transaction_id=value["definition_transaction_id"],
            activation_id=value["activation_id"],
            max_probe_seconds=value["max_probe_seconds"],
        )
        if value.get("required_cases") != list(REQUIRED_ACCEPTANCE_CASES):
            raise ValidationError("acceptance profile cases are invalid")
        if value.get("evidence_spool") != str(result.evidence_spool):
            raise ValidationError("acceptance evidence spool is invalid")
        return result
