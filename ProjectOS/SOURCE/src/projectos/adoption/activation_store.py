from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from projectos.adoption.fixture import FixtureInstallationTarget
from projectos.adoption.profile import MachineProfile
from projectos.adoption.scheduler import SchedulerDefinition
from projectos.adoption.store import LocalAdoptionStore
from projectos.database import utc_now
from projectos.errors import ValidationError
from projectos.validation import reject_secret_material


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ActivationState(StrEnum):
    DISCOVERED = "DISCOVERED"
    PREFLIGHTED = "PREFLIGHTED"
    SCHEDULER_STAGED = "SCHEDULER_STAGED"
    RUNTIME_VERIFIED = "RUNTIME_VERIFIED"
    SCHEDULER_ENABLED = "SCHEDULER_ENABLED"
    SKILL_ENABLED = "SKILL_ENABLED"
    PROVED = "PROVED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    DEACTIVATED = "DEACTIVATED"


_NEXT = {
    ActivationState.DISCOVERED: ActivationState.PREFLIGHTED,
    ActivationState.PREFLIGHTED: ActivationState.SCHEDULER_STAGED,
    ActivationState.SCHEDULER_STAGED: ActivationState.RUNTIME_VERIFIED,
    ActivationState.RUNTIME_VERIFIED: ActivationState.SCHEDULER_ENABLED,
    ActivationState.SCHEDULER_ENABLED: ActivationState.SKILL_ENABLED,
    ActivationState.SKILL_ENABLED: ActivationState.PROVED,
}


def _safe_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValidationError(f"{field} is invalid")
    return value


def _bounded_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValidationError(f"{field} is invalid")
    reject_secret_material(value)
    return value


def _canonical(value: Mapping[str, object]) -> bytes:
    reject_secret_material(value)
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class ActivationProofResult:
    success: bool
    triggers: tuple[str, ...]
    statuses: tuple[str, ...]
    error_code: str | None

    def to_mapping(self) -> dict[str, object]:
        return {
            "format": "projectos-activation-proof-v1",
            "success": self.success,
            "triggers": list(self.triggers),
            "statuses": list(self.statuses),
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class ActivationJournal:
    activation_id: str
    definition_transaction_id: str
    state: ActivationState
    fixture_id: str
    installation_id: str
    scheduler_kind: str
    task_id: str
    bundle_sha256: str
    definition_sha256: str | None
    disabled_registry_sha256: str | None
    error_codes: tuple[str, ...]
    created_at: str
    updated_at: str

    def transition(
        self,
        state: ActivationState,
        *,
        definition_sha256: str | None = None,
        disabled_registry_sha256: str | None = None,
        error_code: str | None = None,
    ) -> "ActivationJournal":
        selected = ActivationState(state)
        legal = (
            _NEXT.get(self.state) is selected
            or selected is ActivationState.FAILED
            and self.state not in {
                ActivationState.PROVED,
                ActivationState.ROLLED_BACK,
                ActivationState.DEACTIVATED,
            }
            or selected is ActivationState.ROLLED_BACK
            and self.state
            not in {ActivationState.PROVED, ActivationState.DEACTIVATED}
            or selected is ActivationState.DEACTIVATED
            and self.state is ActivationState.PROVED
        )
        if not legal:
            raise ValidationError("activation state transition is invalid")
        errors = self.error_codes
        if error_code is not None:
            errors = (*errors, _safe_id(error_code, "activation error code"))
        return replace(
            self,
            state=selected,
            definition_sha256=(
                self.definition_sha256
                if definition_sha256 is None
                else definition_sha256
            ),
            disabled_registry_sha256=(
                self.disabled_registry_sha256
                if disabled_registry_sha256 is None
                else disabled_registry_sha256
            ),
            error_codes=errors,
            updated_at=utc_now(),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "format": "projectos-activation-journal-v1",
            "activation_id": self.activation_id,
            "definition_transaction_id": self.definition_transaction_id,
            "state": self.state.value,
            "fixture_id": self.fixture_id,
            "installation_id": self.installation_id,
            "scheduler_kind": self.scheduler_kind,
            "task_id": self.task_id,
            "bundle_sha256": self.bundle_sha256,
            "definition_sha256": self.definition_sha256,
            "disabled_registry_sha256": self.disabled_registry_sha256,
            "error_codes": list(self.error_codes),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class LocalActivationStore:
    def __init__(self, adoption_store: LocalAdoptionStore):
        self.adoption_store = adoption_store
        self.root = adoption_store.root / "activations"

    @classmethod
    def open(cls, adoption_store: LocalAdoptionStore) -> "LocalActivationStore":
        root = adoption_store.root / "activations"
        if adoption_store.root.is_symlink() or root.is_symlink():
            raise ValidationError("activation store cannot use a symlink")
        return cls(adoption_store)

    def activation_root(self, activation_id: str) -> Path:
        return self.root / _safe_id(activation_id, "activation_id")

    def create(
        self,
        target: FixtureInstallationTarget,
        profile: MachineProfile,
        definition_transaction_id: str,
        bundle_sha256: str,
        activation_id: str | None = None,
    ) -> ActivationJournal:
        if not _SHA256.fullmatch(bundle_sha256):
            raise ValidationError("activation bundle hash is invalid")
        activation_id = (
            str(uuid4())
            if activation_id is None
            else _safe_id(activation_id, "activation_id")
        )
        root = self.activation_root(activation_id)
        root.mkdir(parents=True, exist_ok=False)
        timestamp = utc_now()
        journal = ActivationJournal(
            activation_id,
            _safe_id(definition_transaction_id, "definition transaction id"),
            ActivationState.DISCOVERED,
            _safe_id(target.fixture_id, "fixture_id"),
            _safe_id(profile.installation_id, "installation_id"),
            profile.scheduler_kind.value,
            _bounded_text(profile.scheduler_task_id, "scheduler task id"),
            bundle_sha256,
            None,
            None,
            (),
            timestamp,
            timestamp,
        )
        self.save_journal(journal)
        return journal

    def save_journal(self, journal: ActivationJournal) -> None:
        _atomic_write(
            self.activation_root(journal.activation_id) / "journal.json",
            _canonical(journal.to_mapping()),
        )

    def load_journal(self, activation_id: str) -> ActivationJournal:
        identifier = _safe_id(activation_id, "activation_id")
        path = self.activation_root(identifier) / "journal.json"
        try:
            content = path.read_bytes()
            value = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("activation journal is unavailable or invalid") from exc
        expected = {
            "format", "activation_id", "definition_transaction_id", "state",
            "fixture_id", "installation_id", "scheduler_kind", "task_id",
            "bundle_sha256", "definition_sha256", "disabled_registry_sha256",
            "error_codes", "created_at", "updated_at",
        }
        if not isinstance(value, dict) or set(value) != expected or value.get("format") != "projectos-activation-journal-v1":
            raise ValidationError("activation journal fields are invalid")
        if content != _canonical(value) or value["activation_id"] != identifier:
            raise ValidationError("activation journal is not canonical")
        for field in ("bundle_sha256",):
            if not isinstance(value[field], str) or not _SHA256.fullmatch(value[field]):
                raise ValidationError("activation journal hash is invalid")
        for field in ("definition_sha256", "disabled_registry_sha256"):
            if value[field] is not None and (
                not isinstance(value[field], str) or not _SHA256.fullmatch(value[field])
            ):
                raise ValidationError("activation journal hash is invalid")
        if not isinstance(value["error_codes"], list):
            raise ValidationError("activation journal errors are invalid")
        try:
            return ActivationJournal(
                identifier,
                _safe_id(value["definition_transaction_id"], "definition transaction id"),
                ActivationState(value["state"]),
                _safe_id(value["fixture_id"], "fixture_id"),
                _safe_id(value["installation_id"], "installation_id"),
                _safe_id(value["scheduler_kind"], "scheduler kind"),
                _bounded_text(value["task_id"], "scheduler task id"),
                value["bundle_sha256"],
                value["definition_sha256"],
                value["disabled_registry_sha256"],
                tuple(_safe_id(item, "activation error code") for item in value["error_codes"]),
                str(value["created_at"]),
                str(value["updated_at"]),
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError("activation journal is unavailable or invalid") from exc

    def save_disabled_registry(self, activation_id: str, content: bytes) -> str:
        reject_secret_material(content.decode("utf-8"))
        _atomic_write(self.activation_root(activation_id) / "disabled-registry.bin", content)
        return hashlib.sha256(content).hexdigest()

    def load_disabled_registry(self, journal: ActivationJournal) -> bytes:
        try:
            content = (self.activation_root(journal.activation_id) / "disabled-registry.bin").read_bytes()
        except OSError as exc:
            raise ValidationError("disabled registry snapshot is unavailable") from exc
        if (
            journal.disabled_registry_sha256 is None
            or hashlib.sha256(content).hexdigest() != journal.disabled_registry_sha256
        ):
            raise ValidationError("disabled registry snapshot hash does not match")
        return content

    def save_definition(self, activation_id: str, definition: SchedulerDefinition) -> None:
        _atomic_write(
            self.activation_root(activation_id) / "scheduler-definition.bin",
            definition.content,
        )

    def load_definition_bytes(self, journal: ActivationJournal) -> bytes:
        try:
            content = (self.activation_root(journal.activation_id) / "scheduler-definition.bin").read_bytes()
        except OSError as exc:
            raise ValidationError("scheduler definition snapshot is unavailable") from exc
        if (
            journal.definition_sha256 is None
            or hashlib.sha256(content).hexdigest() != journal.definition_sha256
        ):
            raise ValidationError("scheduler definition snapshot hash does not match")
        return content

    def save_proof(self, activation_id: str, proof: ActivationProofResult) -> None:
        _atomic_write(
            self.activation_root(activation_id) / "proof.json",
            _canonical(proof.to_mapping()),
        )

    def load_proof(self, activation_id: str) -> ActivationProofResult:
        try:
            value = json.loads(
                (self.activation_root(activation_id) / "proof.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("activation proof is unavailable or invalid") from exc
        if not isinstance(value, dict) or set(value) != {"format", "success", "triggers", "statuses", "error_code"}:
            raise ValidationError("activation proof fields are invalid")
        if (
            value["format"] != "projectos-activation-proof-v1"
            or type(value["success"]) is not bool
            or not isinstance(value["triggers"], list)
            or not isinstance(value["statuses"], list)
        ):
            raise ValidationError("activation proof is invalid")
        return ActivationProofResult(
            value["success"],
            tuple(_safe_id(item, "proof trigger") for item in value["triggers"]),
            tuple(_safe_id(item, "proof status") for item in value["statuses"]),
            None if value["error_code"] is None else _safe_id(value["error_code"], "proof error code"),
        )
