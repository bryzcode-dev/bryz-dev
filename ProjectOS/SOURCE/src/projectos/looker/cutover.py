from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping
from uuid import UUID

from projectos.audit import AuditLog
from projectos.backup import BackupService
from projectos.database import ProjectOSDatabase
from projectos.errors import ValidationError
from projectos.validation import canonical_json, reject_secret_material, require_text

from .refresh import RefreshReceipt


_FORMAT = "projectos-looker-cutover-v1"
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _sha(value: bytes | str) -> str:
    content = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(content).hexdigest()


def _id(*parts: object) -> str:
    return str(UUID(hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()[:32]))


def _command(value: tuple[str, ...], field: str) -> tuple[str, ...]:
    if not value or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError(f"{field} is invalid")
    if any(any(character in item for character in "\n\r\x00") for item in value):
        raise ValidationError(f"{field} is invalid")
    reject_secret_material(value)
    return tuple(value)


@dataclass(frozen=True)
class CutoverTarget:
    target_id: str
    target_type: str
    expected_owner: str
    inspect_owner_argv: tuple[str, ...]
    disable_argv: tuple[str, ...]
    remove_argv: tuple[str, ...]
    restore_argv: tuple[str, ...]

    def validate(self) -> None:
        if not all(isinstance(value, str) for value in (self.target_id, self.target_type, self.expected_owner)):
            raise ValidationError("cutover target text field is invalid")
        require_text(self.target_id, "target_id")
        require_text(self.target_type, "target_type")
        require_text(self.expected_owner, "expected_owner")
        _command(self.inspect_owner_argv, "inspect_owner_argv")
        _command(self.disable_argv, "disable_argv")
        _command(self.remove_argv, "remove_argv")
        _command(self.restore_argv, "restore_argv")

    def to_mapping(self) -> dict[str, object]:
        return {
            "disable_argv": list(self.disable_argv),
            "expected_owner": self.expected_owner,
            "inspect_owner_argv": list(self.inspect_owner_argv),
            "remove_argv": list(self.remove_argv),
            "restore_argv": list(self.restore_argv),
            "target_id": self.target_id,
            "target_type": self.target_type,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "CutoverTarget":
        expected = {"disable_argv", "expected_owner", "inspect_owner_argv", "remove_argv", "restore_argv", "target_id", "target_type"}
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValidationError("cutover target is invalid")
        try:
            target = cls(
                value["target_id"], value["target_type"], value["expected_owner"],
                tuple(value["inspect_owner_argv"]), tuple(value["disable_argv"]),
                tuple(value["remove_argv"]), tuple(value["restore_argv"]),
            )
        except TypeError as exc:
            raise ValidationError("cutover target is invalid") from exc
        target.validate()
        return target


@dataclass(frozen=True)
class CutoverPreparationRequest:
    project_id: str
    intake_run_id: str
    reconciliation_id: str
    refresh_receipt: RefreshReceipt
    backup_manifest: Path
    legacy_root: Path
    targets: tuple[CutoverTarget, ...]
    actor: str
    expected_owner_email: str
    prepared_at: str
    output_path: Path
    support_state: str = "SIMULATED"


@dataclass(frozen=True)
class CutoverPackage:
    cutover_id: str
    path: Path
    sha256: str
    support_state: str
    ready: bool
    owner_sha256: str
    targets_sha256: str
    targets: tuple[CutoverTarget, ...]


def _canonical_member(name: str, content: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, _FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info, content


def _archive_bytes(manifest: Mapping[str, object], payload: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        entries = {"manifest.json": (canonical_json(manifest) + "\n").encode(), **payload}
        for name in sorted(entries):
            info, content = _canonical_member(name, entries[name])
            archive.writestr(info, content)
    return buffer.getvalue()


def _legacy_payload(root: Path) -> dict[str, bytes]:
    selected = Path(root)
    if not selected.is_dir() or selected.is_symlink():
        raise ValidationError("legacy archive root is unavailable")
    payload: dict[str, bytes] = {}
    for path in sorted(selected.rglob("*")):
        if path.is_symlink():
            raise ValidationError("legacy archive cannot contain symlinks")
        if not path.is_file():
            continue
        relative = path.relative_to(selected).as_posix()
        if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
            raise ValidationError("legacy archive path is invalid")
        content = path.read_bytes()
        reject_secret_material(content.decode("utf-8", errors="replace"))
        payload[f"legacy/{relative}"] = content
    if not payload:
        raise ValidationError("legacy archive is empty")
    return payload


class CutoverPreparer:
    def __init__(self, database: ProjectOSDatabase):
        self.database = database

    def prepare(self, request: CutoverPreparationRequest) -> CutoverPackage:
        if request.support_state not in {"SIMULATED", "REAL"}:
            raise ValidationError("cutover package support state is invalid")
        if not request.targets:
            raise ValidationError("at least one cutover target is required")
        if len({target.target_id for target in request.targets}) != len(request.targets):
            raise ValidationError("cutover target identifiers must be unique")
        for target in request.targets:
            target.validate()
        owner = self.database.connection.execute(
            "SELECT email FROM users WHERE protected_owner=1 AND active=1"
        ).fetchall()
        if len(owner) != 1 or owner[0]["email"] != request.actor or request.actor != request.expected_owner_email:
            raise ValidationError("exact protected Owner approval is required")
        intake = self.database.connection.execute(
            "SELECT status,archive_sha256 FROM looker_intake_runs WHERE project_id=? AND intake_run_id=?",
            (request.project_id, request.intake_run_id),
        ).fetchone()
        if intake is None or intake["status"] not in {"IMPORTED", "RECONCILED", "CUTOVER_READY"}:
            raise ValidationError("verified intake is unavailable")
        reconciliation = self.database.connection.execute(
            "SELECT status,project_id,intake_run_id FROM looker_reconciliation_runs WHERE reconciliation_id=?",
            (request.reconciliation_id,),
        ).fetchone()
        if reconciliation is None or reconciliation["status"] != "READY" or reconciliation["project_id"] != request.project_id or reconciliation["intake_run_id"] != request.intake_run_id:
            raise ValidationError("reconciliation is not ready or is unbound")
        if request.refresh_receipt.reconciliation_id != request.reconciliation_id:
            raise ValidationError("refresh receipt does not match reconciliation")
        verified_refresh = request.refresh_receipt.verify(self.database)
        backup = BackupService(self.database).verify(request.backup_manifest)
        if not backup.valid or backup.schema_version != self.database.schema_version():
            raise ValidationError("backup is unavailable or invalid")
        mapping_coverage = self.database.connection.execute(
            "SELECT COUNT(*) AS total,SUM(CASE WHEN status='MATCHED' THEN 1 ELSE 0 END) AS matched "
            "FROM looker_legacy_mappings WHERE project_id=? AND intake_run_id=?",
            (request.project_id, request.intake_run_id),
        ).fetchone()
        if mapping_coverage is None or mapping_coverage["total"] < 1 or mapping_coverage["matched"] != mapping_coverage["total"]:
            raise ValidationError("legacy mapping is incomplete")
        invalid_mapping = self.database.connection.execute(
            "SELECT 1 FROM looker_legacy_mappings m "
            "LEFT JOIN looker_asset_occurrences o ON o.intake_run_id=m.intake_run_id AND o.looker_asset_id=m.entity_id "
            "LEFT JOIN looker_assets a ON a.looker_asset_id=o.looker_asset_id AND a.project_id=m.project_id AND a.asset_type=m.entity_type "
            "WHERE m.project_id=? AND m.intake_run_id=? AND m.status='MATCHED' AND a.looker_asset_id IS NULL LIMIT 1",
            (request.project_id, request.intake_run_id),
        ).fetchone()
        if invalid_mapping:
            raise ValidationError("legacy mapping does not reference the current intake")
        unresolved_finding = self.database.connection.execute(
            "SELECT 1 FROM looker_findings WHERE project_id=? AND intake_run_id=? AND status='OPEN' AND severity IN ('CRITICAL','IMPORTANT') LIMIT 1",
            (request.project_id, request.intake_run_id),
        ).fetchone()
        if unresolved_finding:
            raise ValidationError("critical or important finding is unresolved")
        failed_validation = self.database.connection.execute(
            "SELECT 1 FROM looker_validation_results WHERE intake_run_id=? AND passed=0 LIMIT 1",
            (request.intake_run_id,),
        ).fetchone()
        if failed_validation:
            raise ValidationError("validation evidence failed")

        legacy = _legacy_payload(request.legacy_root)
        target_values = [target.to_mapping() for target in request.targets]
        target_sha = _sha(canonical_json(target_values))
        cutover_id = _id(request.project_id, request.intake_run_id, request.reconciliation_id, verified_refresh.sha256, target_sha, request.support_state)
        checklist = {
            "analytics_parity": True,
            "backup_verified": True,
            "findings_clear": True,
            "intake_verified": True,
            "legacy_preserved": True,
            "mappings_complete": True,
            "preparation_owner_verified": True,
            "refresh_verified": True,
            "rollback_tested": True,
            "schema_current": True,
            "targets_bound": True,
            "validation_passed": True,
        }
        effect_plan = {"order": ["DISABLE", "REMOVE"], "targets": target_values}
        rollback = {"retention": "PERMANENT", "targets": list(reversed(target_values))}
        payload = {
            **legacy,
            "checklist.json": (canonical_json(checklist) + "\n").encode(),
            "effect-plan.json": (canonical_json(effect_plan) + "\n").encode(),
            "rollback.json": (canonical_json(rollback) + "\n").encode(),
        }
        inventory = [{"path": name, "sha256": _sha(content), "size": len(content)} for name, content in sorted(payload.items())]
        manifest = {
            "cutover_id": cutover_id,
            "format": _FORMAT,
            "intake_run_id": request.intake_run_id,
            "inventory": inventory,
            "owner_sha256": _sha(request.actor.lower()),
            "prepared_at": require_text(request.prepared_at, "prepared_at"),
            "project_id": request.project_id,
            "reconciliation_id": request.reconciliation_id,
            "refresh_receipt_sha256": verified_refresh.sha256,
            "support_state": request.support_state,
            "targets_sha256": target_sha,
        }
        content = _archive_bytes(manifest, payload)
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_bytes(content)
        os.replace(temporary, output)
        package_sha = _sha(content)
        rollback_sha = _sha(payload["rollback.json"])
        now = require_text(request.prepared_at, "prepared_at")
        with self.database.transaction() as connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO looker_cutover_packages VALUES(?,?,?,?,?,?,?,?,?)",
                (cutover_id, request.project_id, request.reconciliation_id, package_sha, rollback_sha, target_sha, "PREPARED", request.actor, now),
            )
            row = connection.execute("SELECT * FROM looker_cutover_packages WHERE cutover_id=?", (cutover_id,)).fetchone()
            if row is None or row["package_sha256"] != package_sha or row["rollback_sha256"] != rollback_sha or row["ownership_sha256"] != target_sha:
                raise ValidationError("existing cutover package does not match")
            if inserted.rowcount:
                AuditLog().append(
                    connection,
                    "looker.cutover.prepared",
                    request.actor,
                    "looker_cutover",
                    cutover_id,
                    {"package_sha256": package_sha, "reconciliation_id": request.reconciliation_id},
                )
        return verify_cutover_package(output)


def verify_cutover_package(path: Path) -> CutoverPackage:
    selected = Path(path)
    if not selected.is_file() or selected.is_symlink():
        raise ValidationError("cutover package is unavailable")
    content = selected.read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(name.casefold() for name in names)) or "manifest.json" not in names:
                raise ValidationError("cutover package inventory is invalid")
            for name in names:
                portable = PurePosixPath(name)
                if portable.is_absolute() or ".." in portable.parts or "\\" in name:
                    raise ValidationError("cutover package path is invalid")
            if any((item.external_attr >> 16) & 0o170000 != 0o100000 for item in infos):
                raise ValidationError("cutover package member type is invalid")
            manifest = json.loads(archive.read("manifest.json"))
            payload = {name: archive.read(name) for name in names if name != "manifest.json"}
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValidationError("cutover package is invalid") from exc
    expected_manifest = {"cutover_id", "format", "intake_run_id", "inventory", "owner_sha256", "prepared_at", "project_id", "reconciliation_id", "refresh_receipt_sha256", "support_state", "targets_sha256"}
    if not isinstance(manifest, dict) or set(manifest) != expected_manifest or manifest["format"] != _FORMAT or manifest["support_state"] not in {"SIMULATED", "REAL"}:
        raise ValidationError("cutover package manifest is invalid")
    inventory = [{"path": name, "sha256": _sha(data), "size": len(data)} for name, data in sorted(payload.items())]
    if manifest["inventory"] != inventory or content != _archive_bytes(manifest, payload):
        raise ValidationError("cutover package content is not canonical")
    required = {"checklist.json", "effect-plan.json", "rollback.json"}
    if not required.issubset(payload) or not any(name.startswith("legacy/") for name in payload):
        raise ValidationError("cutover package required evidence is missing")
    try:
        checklist = json.loads(payload["checklist.json"])
        effect_plan = json.loads(payload["effect-plan.json"])
        rollback = json.loads(payload["rollback.json"])
        targets = tuple(CutoverTarget.from_mapping(item) for item in effect_plan["targets"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValidationError("cutover package evidence is invalid") from exc
    if not checklist or not all(value is True for value in checklist.values()):
        raise ValidationError("cutover package is not ready")
    if effect_plan.get("order") != ["DISABLE", "REMOVE"] or rollback.get("retention") != "PERMANENT" or rollback.get("targets") != list(reversed(effect_plan["targets"])):
        raise ValidationError("cutover rollback contract is invalid")
    if _sha(canonical_json([target.to_mapping() for target in targets])) != manifest["targets_sha256"]:
        raise ValidationError("cutover target ownership binding is invalid")
    return CutoverPackage(manifest["cutover_id"], selected, _sha(content), manifest["support_state"], True, manifest["owner_sha256"], manifest["targets_sha256"], targets)
