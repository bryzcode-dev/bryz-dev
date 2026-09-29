from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Mapping

from projectos.errors import ValidationError


class HostAcceptanceState(StrEnum):
    DISCOVERED = "DISCOVERED"
    PREFLIGHTED = "PREFLIGHTED"
    DEFINITION_ADOPTED = "DEFINITION_ADOPTED"
    RUNTIME_ACTIVATED = "RUNTIME_ACTIVATED"
    NATIVE_STAGED = "NATIVE_STAGED"
    NATIVE_ENABLED = "NATIVE_ENABLED"
    IMMEDIATE_PROVED = "IMMEDIATE_PROVED"
    NON_OVERLAP_PROVED = "NON_OVERLAP_PROVED"
    SCHEDULE_PROVED = "SCHEDULE_PROVED"
    DEACTIVATED = "DEACTIVATED"
    NATIVE_REMOVED = "NATIVE_REMOVED"
    DEFINITION_ROLLED_BACK = "DEFINITION_ROLLED_BACK"
    EVIDENCE_SEALED = "EVIDENCE_SEALED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class HostAcceptanceJournal:
    run_id: str
    state: HostAcceptanceState
    acceptance_id: str
    receipt_id: str
    release_sha256: str
    wheel_sha256: str
    definition_sha256: str
    completed_states: tuple[str, ...]
    proved_cases: tuple[str, ...]
    cleanup_complete: bool
    error_codes: tuple[str, ...]
    pending_effect: str | None = None

    def transition(
        self,
        state: HostAcceptanceState,
        *,
        proved_case: str | None = None,
        cleanup_complete: bool | None = None,
        error_code: str | None = None,
    ) -> HostAcceptanceJournal:
        completed = self.completed_states
        selected = HostAcceptanceState(state)
        if selected is not HostAcceptanceState.FAILED and selected.value not in completed:
            completed = (*completed, selected.value)
        cases = self.proved_cases
        if proved_case is not None and proved_case not in cases:
            cases = (*cases, proved_case)
        errors = self.error_codes
        if error_code is not None:
            errors = (*errors, error_code[:64])
        return replace(
            self,
            state=selected,
            completed_states=completed,
            proved_cases=cases,
            cleanup_complete=self.cleanup_complete if cleanup_complete is None else cleanup_complete,
            error_codes=errors,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "acceptance_id": self.acceptance_id,
            "cleanup_complete": self.cleanup_complete,
            "completed_states": list(self.completed_states),
            "definition_sha256": self.definition_sha256,
            "error_codes": list(self.error_codes),
            "format": "projectos-host-acceptance-journal-v2",
            "pending_effect": self.pending_effect,
            "proved_cases": list(self.proved_cases),
            "receipt_id": self.receipt_id,
            "release_sha256": self.release_sha256,
            "run_id": self.run_id,
            "state": self.state.value,
            "wheel_sha256": self.wheel_sha256,
        }

    def canonical_bytes(self) -> bytes:
        return (json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":")) + "\n").encode()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> HostAcceptanceJournal:
        expected = {
            "acceptance_id", "cleanup_complete", "completed_states", "definition_sha256",
            "error_codes", "format", "proved_cases", "receipt_id", "release_sha256",
            "pending_effect", "run_id", "state", "wheel_sha256",
        }
        if set(value) != expected or value.get("format") != "projectos-host-acceptance-journal-v2":
            raise ValidationError("host acceptance journal fields are invalid")
        if not isinstance(value.get("cleanup_complete"), bool):
            raise ValidationError("host acceptance journal cleanup state is invalid")
        pending = value.get("pending_effect")
        if pending is not None and (
            not isinstance(pending, str)
            or pending not in {"install", "enable", "disable", "remove"}
        ):
            raise ValidationError("host acceptance journal pending effect is invalid")
        sequence_fields = ("completed_states", "proved_cases", "error_codes")
        if any(not isinstance(value.get(field), list) or any(not isinstance(item, str) for item in value[field]) for field in sequence_fields):
            raise ValidationError("host acceptance journal sequences are invalid")
        digests = (value.get("release_sha256"), value.get("wheel_sha256"), value.get("definition_sha256"))
        if any(not isinstance(item, str) or len(item) != 64 or any(char not in "0123456789abcdef" for char in item) for item in digests):
            raise ValidationError("host acceptance journal hash is invalid")
        try:
            state = HostAcceptanceState(value["state"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("host acceptance journal state is invalid") from exc
        return cls(
            str(value["run_id"]), state, str(value["acceptance_id"]), str(value["receipt_id"]),
            str(value["release_sha256"]), str(value["wheel_sha256"]), str(value["definition_sha256"]),
            tuple(value["completed_states"]), tuple(value["proved_cases"]), value["cleanup_complete"],
            tuple(value["error_codes"]), pending,
        )
