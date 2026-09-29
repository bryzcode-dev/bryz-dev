from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from projectos.acceptance.native import NativeProcessExecutor
from projectos.errors import ValidationError
from projectos.looker.cutover import CutoverPackage, CutoverTarget, verify_cutover_package
from projectos.validation import canonical_json, require_text


_APPROVAL_FORMAT = "projectos-looker-cutover-approval-v1"


@dataclass(frozen=True)
class CutoverApproval:
    format: str
    package_sha256: str
    cutover_id: str
    targets_sha256: str
    owner_email: str
    approved_at: str
    nonce: str
    signature: str

    def _payload(self) -> dict[str, str]:
        return {
            "approved_at": self.approved_at,
            "cutover_id": self.cutover_id,
            "format": self.format,
            "nonce": self.nonce,
            "owner_email": self.owner_email,
            "package_sha256": self.package_sha256,
            "targets_sha256": self.targets_sha256,
        }

    def to_mapping(self) -> dict[str, str]:
        return {**self._payload(), "signature": self.signature}

    @classmethod
    def issue(cls, package: CutoverPackage, owner_email: str, approved_at: str, nonce: str, signing_key: bytes) -> "CutoverApproval":
        if package.support_state != "REAL":
            raise ValidationError("REAL cutover package is required for Owner approval")
        key = _approval_key(signing_key)
        values = {
            "approved_at": require_text(approved_at, "approved_at"),
            "cutover_id": package.cutover_id,
            "format": _APPROVAL_FORMAT,
            "nonce": require_text(nonce, "approval nonce"),
            "owner_email": require_text(owner_email, "owner_email").lower(),
            "package_sha256": package.sha256,
            "targets_sha256": package.targets_sha256,
        }
        signature = hmac.new(key, canonical_json(values).encode(), hashlib.sha256).hexdigest()
        return cls(**values, signature=signature)

    @classmethod
    def from_mapping(cls, value: object) -> "CutoverApproval":
        fields = {"approved_at", "cutover_id", "format", "nonce", "owner_email", "package_sha256", "signature", "targets_sha256"}
        if not isinstance(value, Mapping) or set(value) != fields or any(not isinstance(value[field], str) for field in fields):
            raise ValidationError("cutover approval is invalid")
        return cls(**{field: value[field] for field in fields})


def _approval_key(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise ValidationError("cutover approval key is invalid")
    return value


@dataclass(frozen=True)
class CutoverHostResult:
    cutover_id: str
    state: str
    completed_effects: tuple[tuple[str, str], ...]
    errors: tuple[str, ...]


class CutoverHostTransaction:
    """Explicitly authorized native boundary; production callers provide the executor."""

    def __init__(self, package: CutoverPackage, journal_path: Path, executor: NativeProcessExecutor, approval_key: bytes, expected_owner_email: str):
        verified = verify_cutover_package(package.path)
        if verified.sha256 != package.sha256 or verified.cutover_id != package.cutover_id:
            raise ValidationError("cutover package changed after verification")
        self.package = verified
        self.journal_path = Path(journal_path)
        self.executor = executor
        self.approval_key = _approval_key(approval_key)
        self.expected_owner_email = require_text(expected_owner_email, "expected_owner_email").lower()
        if hashlib.sha256(self.expected_owner_email.encode()).hexdigest() != self.package.owner_sha256:
            raise ValidationError("cutover approval Owner does not match package")

    def _write(self, value: Mapping[str, object]) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal_path.with_suffix(self.journal_path.suffix + ".tmp")
        temporary.write_text(canonical_json(value) + "\n", encoding="utf-8")
        os.replace(temporary, self.journal_path)

    def _load(self) -> dict[str, object]:
        try:
            content = self.journal_path.read_text(encoding="utf-8")
            value = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("cutover journal is unavailable or invalid") from exc
        expected = {"format", "cutover_id", "package_sha256", "state", "completed_effects", "pending_effect", "errors"}
        if not isinstance(value, dict) or set(value) != expected or value["format"] != "projectos-looker-cutover-journal-v1" or value["cutover_id"] != self.package.cutover_id or value["package_sha256"] != self.package.sha256:
            raise ValidationError("cutover journal is not bound to package")
        if content != canonical_json(value) + "\n" or value["state"] not in {"RUNNING", "FAILED", "COMPLETE", "ROLLED_BACK", "ROLLBACK_FAILED"} or not isinstance(value["completed_effects"], list) or not isinstance(value["errors"], list):
            raise ValidationError("cutover journal is not canonical")
        valid_actions = {"DISABLE", "REMOVE", "RESTORE"}
        if any(not isinstance(item, dict) or set(item) != {"action", "target_id"} or item["action"] not in valid_actions for item in value["completed_effects"]):
            raise ValidationError("cutover journal effects are invalid")
        pending = value["pending_effect"]
        if pending is not None and (not isinstance(pending, dict) or set(pending) != {"action", "target_id"}):
            raise ValidationError("cutover journal pending effect is invalid")
        return value

    def _authorize(self, approval: CutoverApproval) -> None:
        if self.package.support_state != "REAL":
            raise ValidationError("REAL cutover package is required for native execution")
        if not isinstance(approval, CutoverApproval) or approval.format != _APPROVAL_FORMAT:
            raise ValidationError("exact cutover approval is required")
        expected = hmac.new(self.approval_key, canonical_json(approval._payload()).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(approval.signature, expected) or approval.package_sha256 != self.package.sha256 or approval.cutover_id != self.package.cutover_id or approval.targets_sha256 != self.package.targets_sha256 or approval.owner_email.lower() != self.expected_owner_email or hashlib.sha256(approval.owner_email.lower().encode()).hexdigest() != self.package.owner_sha256:
            raise ValidationError("exact cutover approval is required")

    @staticmethod
    def _target(package: CutoverPackage, target_id: str) -> CutoverTarget:
        for target in package.targets:
            if target.target_id == target_id:
                return target
        raise ValidationError("cutover target is unavailable")

    def _intent(self, journal: dict[str, object], target: CutoverTarget, action: str) -> None:
        journal["pending_effect"] = {"action": action, "target_id": target.target_id}
        self._write(journal)

    def _ownership(self, journal: dict[str, object], target: CutoverTarget, action: str) -> None:
        self._intent(journal, target, f"inspect:{action}")
        result = self.executor.run(target.inspect_owner_argv, 30)
        if result.timed_out or result.returncode != 0 or result.stdout.strip() != target.expected_owner:
            journal["pending_effect"] = None
            journal["state"] = "FAILED"
            journal["errors"].append("ownership_changed")
            self._write(journal)
            raise ValidationError("cutover target ownership changed")

    def _run_effect(self, journal: dict[str, object], target: CutoverTarget, action: str, argv: tuple[str, ...]) -> bool:
        self._intent(journal, target, action)
        result = self.executor.run(argv, 60)
        if result.timed_out or result.returncode != 0:
            journal["pending_effect"] = None
            journal["state"] = "FAILED"
            journal["errors"].append(f"{action.lower()}_failed:{target.target_id}")
            self._write(journal)
            return False
        journal["completed_effects"].append({"action": action, "target_id": target.target_id})
        journal["pending_effect"] = None
        self._write(journal)
        return True

    def _result(self, journal: Mapping[str, object]) -> CutoverHostResult:
        return CutoverHostResult(
            self.package.cutover_id,
            str(journal["state"]),
            tuple((item["target_id"], item["action"]) for item in journal["completed_effects"]),
            tuple(journal["errors"]),
        )

    def execute(self, approval: CutoverApproval) -> CutoverHostResult:
        self._authorize(approval)
        if self.journal_path.exists():
            journal = self._load()
            if journal["state"] in {"COMPLETE", "ROLLED_BACK"}:
                return self._result(journal)
            if journal["pending_effect"] is not None:
                raise ValidationError("cutover process reconstruction is required")
        else:
            journal = {"format": "projectos-looker-cutover-journal-v1", "cutover_id": self.package.cutover_id, "package_sha256": self.package.sha256, "state": "RUNNING", "completed_effects": [], "pending_effect": None, "errors": []}
            self._write(journal)
        for action in ("DISABLE", "REMOVE"):
            for target in self.package.targets:
                if {"action": action, "target_id": target.target_id} in journal["completed_effects"]:
                    continue
                try:
                    self._ownership(journal, target, action)
                except ValidationError:
                    if journal["completed_effects"]:
                        return self._rollback(journal)
                    raise
                argv = target.disable_argv if action == "DISABLE" else target.remove_argv
                if not self._run_effect(journal, target, action, argv):
                    return self._rollback(journal)
        journal["state"] = "COMPLETE"; self._write(journal)
        return self._result(journal)

    def _rollback(self, journal: dict[str, object]) -> CutoverHostResult:
        target_ids = []
        for item in journal["completed_effects"]:
            if item["target_id"] not in target_ids:
                target_ids.append(item["target_id"])
        for target_id in reversed(target_ids):
            target = self._target(self.package, target_id)
            self._ownership(journal, target, "RESTORE")
            if not self._run_effect(journal, target, "RESTORE", target.restore_argv):
                journal["state"] = "ROLLBACK_FAILED"; self._write(journal)
                return self._result(journal)
        journal["state"] = "ROLLED_BACK"; journal["pending_effect"] = None; self._write(journal)
        return self._result(journal)

    def recover(self, approval: CutoverApproval) -> CutoverHostResult:
        self._authorize(approval)
        journal = self._load()
        if journal["state"] in {"COMPLETE", "ROLLED_BACK"}:
            return self._result(journal)
        if journal["pending_effect"] is not None:
            raise ValidationError("cutover process reconstruction is uncertain")
        return self._rollback(journal)
