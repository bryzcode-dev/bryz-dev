from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from projectos.audit import AuditLog
from projectos.database import ProjectOSDatabase, utc_now
from projectos.errors import ValidationError
from projectos.google.types import UserRole
from projectos.sync.types import AuthorizationContext
from projectos.validation import canonical_json, reject_secret_material, require_text

from .repository import LookerRepository


DIMENSIONS = ("asset_counts", "relationships", "findings", "dashboards", "tracker_mappings", "validation", "refresh", "credential_usage")
_MISSING = object()


def _id(*parts: object) -> str:
    return str(UUID(hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()[:32]))


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _flatten(value: object, prefix: str = "") -> dict[str, object]:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key in sorted(value):
            name = f"{prefix}.{key}" if prefix else str(key)
            nested = value[key]
            if isinstance(nested, Mapping):
                result.update(_flatten(nested, name))
            else:
                result[name] = nested
        return result
    raise ValidationError("reconciliation dimension must be an object")


def _snapshot_dimension(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return _flatten(value)
    if not isinstance(value, list):
        raise ValidationError("reconciliation dimension must be an object or item list")
    result: dict[str, object] = {}
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"key", "value"}:
            raise ValidationError("reconciliation snapshot item is invalid")
        key = require_text(str(item["key"]), "item key")
        if key in result:
            raise ValidationError("reconciliation snapshot contains a duplicate item")
        result[key] = item["value"]
    return result


@dataclass(frozen=True)
class ReconciliationPolicy:
    required_dimensions: tuple[str, ...]
    optional_dimensions: tuple[str, ...]

    def __post_init__(self) -> None:
        dimensions = (*self.required_dimensions, *self.optional_dimensions)
        if not self.required_dimensions or len(dimensions) != len(set(dimensions)) or set(dimensions) != set(DIMENSIONS):
            raise ValidationError("reconciliation policy dimensions are invalid or duplicated")

    @classmethod
    def default(cls) -> "ReconciliationPolicy":
        return cls(DIMENSIONS, ())

    @classmethod
    def from_mapping(cls, value: object) -> "ReconciliationPolicy":
        if not isinstance(value, Mapping) or set(value) != {"required_dimensions", "optional_dimensions"}:
            raise ValidationError("reconciliation policy is invalid")
        return cls(tuple(value["required_dimensions"]), tuple(value["optional_dimensions"]))

    def to_mapping(self) -> dict[str, list[str]]:
        return {"optional_dimensions": list(self.optional_dimensions), "required_dimensions": list(self.required_dimensions)}


@dataclass(frozen=True)
class ReconciliationItem:
    dimension: str
    item_key: str
    outcome: str
    source: object
    target: object
    waiver_reason: str | None = None
    waived_by: str | None = None
    waived_at: str | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    reconciliation_id: str
    project_id: str
    intake_run_id: str
    analytic_version: int
    policy_sha256: str
    legacy_sha256: str
    status: str
    ready: bool
    items: tuple[ReconciliationItem, ...]
    parent_reconciliation_id: str | None = None


class LookerReconciler:
    def __init__(self, database: ProjectOSDatabase):
        self.database = database
        self.repository = LookerRepository(database)

    def _source(self, project_id: object, intake_run_id: str, version: int) -> dict[str, dict[str, object]]:
        if not self.repository.intake(project_id, intake_run_id):
            raise ValidationError("Looker intake run does not exist")
        rows = self.database.connection.execute(
            "SELECT analytic_type,value_json,source_run_id FROM looker_analytics WHERE project_id=? ORDER BY analytic_type,created_at,analytic_id",
            (str(project_id),),
        ).fetchall()
        selected: dict[str, Mapping[str, Any]] = {}
        provenance: dict[str, str] = {}
        for row in rows:
            value = json.loads(row["value_json"])
            if int(value.get("version", 0)) == version:
                selected[row["analytic_type"]] = value.get("data", {})
                provenance[row["analytic_type"]] = row["source_run_id"]
        if set(selected) != {"LOOKER_GRAPH", "LOOKER_SUMMARY"}:
            raise ValidationError("Looker analytic version is unavailable or mixed")
        if set(provenance.values()) != {intake_run_id}:
            raise ValidationError("Looker analytic provenance does not match intake")
        summary = selected["LOOKER_SUMMARY"]
        graph = selected["LOOKER_GRAPH"]
        relationship_values = {f"{source}->{target}": True for source, targets in graph.get("forward", {}).items() for target in targets}
        finding_values: dict[str, object] = {"duplicate_count": summary.get("duplicate_count", 0), "unresolved_count": summary.get("unresolved_count", 0)}
        for values in summary.get("orphans", {}).values():
            for node in values:
                finding_values[f"orphan:{node}"] = True
        validation = dict(summary.get("validation", {})); validation["code_status"] = summary.get("code_status", "UNKNOWN")
        return {
            "asset_counts": _flatten(summary.get("asset_counts", {})),
            "relationships": relationship_values,
            "findings": finding_values,
            "dashboards": {"count": summary.get("asset_counts", {}).get("dashboard", 0)},
            "tracker_mappings": _flatten(summary.get("legacy", {})),
            "validation": _flatten(validation),
            "refresh": {"status": summary.get("refresh_status", "UNAVAILABLE")},
            "credential_usage": _flatten(summary.get("credential_usage", {})),
        }

    @staticmethod
    def _items(source: Mapping[str, Mapping[str, object]], target: Mapping[str, Mapping[str, object]]) -> tuple[ReconciliationItem, ...]:
        result = []
        for dimension in DIMENSIONS:
            keys = sorted(set(source[dimension]) | set(target[dimension]))
            if not keys:
                result.append(ReconciliationItem(dimension, "__empty__", "MATCH", None, None))
                continue
            for key in keys:
                left = source[dimension].get(key, _MISSING); right = target[dimension].get(key, _MISSING)
                if left is _MISSING: outcome = "MISSING_SOURCE"
                elif right is _MISSING: outcome = "MISSING_TARGET"
                elif canonical_json(left) == canonical_json(right): outcome = "MATCH"
                else: outcome = "MISMATCH"
                result.append(ReconciliationItem(dimension, key, outcome, None if left is _MISSING else left, None if right is _MISSING else right))
        return tuple(result)

    @staticmethod
    def _ready(items: tuple[ReconciliationItem, ...], policy: ReconciliationPolicy) -> bool:
        return all(item.outcome in {"MATCH", "WAIVED"} for item in items if item.dimension in policy.required_dimensions)

    def stage(self, project_id: object, intake_run_id: str, analytic_version: int, legacy_snapshot: object, policy: ReconciliationPolicy, actor: str) -> ReconciliationReport:
        actor = require_text(actor, "actor")
        if type(analytic_version) is not int or analytic_version < 1:
            raise ValidationError("Looker analytic version is invalid")
        if not isinstance(policy, ReconciliationPolicy) or not isinstance(legacy_snapshot, Mapping) or set(legacy_snapshot) != set(DIMENSIONS):
            raise ValidationError("reconciliation input is invalid")
        reject_secret_material(legacy_snapshot)
        target = {dimension: _snapshot_dimension(legacy_snapshot[dimension]) for dimension in DIMENSIONS}
        source = self._source(project_id, intake_run_id, analytic_version)
        policy_json = canonical_json(policy.to_mapping()); policy_sha = _sha(policy.to_mapping()); legacy_sha = _sha(legacy_snapshot)
        reconciliation_id = _id(project_id, intake_run_id, analytic_version, policy_sha, legacy_sha)
        existing = self.repository.reconciliation(reconciliation_id)
        if existing:
            return self.report(reconciliation_id)
        items = self._items(source, target); ready = self._ready(items, policy); now = utc_now()
        with self.database.transaction() as connection:
            connection.execute("INSERT INTO looker_reconciliation_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (reconciliation_id, str(project_id), intake_run_id, intake_run_id, analytic_version, legacy_sha, policy_sha, policy_json, None, "READY" if ready else "BLOCKED", actor if ready else None, now))
            for item in items:
                connection.execute("INSERT INTO looker_reconciliation_items VALUES(?,?,?,?,?,?,?,?,?)", (reconciliation_id, item.dimension, item.item_key, item.outcome, canonical_json(item.source), canonical_json(item.target), None, None, None))
            AuditLog().append(connection, "looker.reconciliation.staged", actor, "looker_reconciliation", reconciliation_id, {"analytic_version": analytic_version, "project_id": str(project_id), "ready": ready})
        return self.report(reconciliation_id)

    def report(self, reconciliation_id: str) -> ReconciliationReport:
        row = self.repository.reconciliation(reconciliation_id)
        if not row:
            raise ValidationError("Looker reconciliation is unavailable")
        items = tuple(ReconciliationItem(item["dimension"], item["item_key"], item["outcome"], json.loads(item["source_json"]), json.loads(item["target_json"]), item["waiver_reason"], item["waived_by"], item["waived_at"]) for item in self.repository.reconciliation_items(reconciliation_id))
        return ReconciliationReport(row["reconciliation_id"], row["project_id"], row["intake_run_id"], row["analytic_version"], row["policy_sha256"], row["legacy_sha256"], row["status"], row["status"] == "READY", items, row["parent_reconciliation_id"])

    def waive(self, reconciliation_id: str, dimension: str, item_key: str, reason: str, context: AuthorizationContext) -> ReconciliationReport:
        if not context.authorized or context.role is not UserRole.OWNER or not context.email:
            raise ValidationError("Owner authorization is required")
        reason = require_text(reason, "waiver reason")
        original = self.report(reconciliation_id); policy_row = self.repository.reconciliation(reconciliation_id); policy = ReconciliationPolicy.from_mapping(json.loads(policy_row["policy_json"]))
        if not any(item.dimension == dimension and item.item_key == item_key and item.outcome not in {"MATCH", "WAIVED"} for item in original.items):
            raise ValidationError("reconciliation item cannot be waived")
        waived_id = _id(reconciliation_id, dimension, item_key, reason, context.email); existing = self.repository.reconciliation(waived_id)
        if existing:
            return self.report(waived_id)
        now = utc_now(); items = tuple(ReconciliationItem(item.dimension, item.item_key, "WAIVED" if item.dimension == dimension and item.item_key == item_key else item.outcome, item.source, item.target, reason if item.dimension == dimension and item.item_key == item_key else item.waiver_reason, context.email if item.dimension == dimension and item.item_key == item_key else item.waived_by, now if item.dimension == dimension and item.item_key == item_key else item.waived_at) for item in original.items); ready = self._ready(items, policy)
        with self.database.transaction() as connection:
            connection.execute("INSERT INTO looker_reconciliation_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (waived_id, original.project_id, original.intake_run_id, original.intake_run_id, original.analytic_version, original.legacy_sha256, original.policy_sha256, policy_row["policy_json"], reconciliation_id, "READY" if ready else "BLOCKED", context.email if ready else None, now))
            for item in items:
                connection.execute("INSERT INTO looker_reconciliation_items VALUES(?,?,?,?,?,?,?,?,?)", (waived_id, item.dimension, item.item_key, item.outcome, canonical_json(item.source), canonical_json(item.target), item.waiver_reason, item.waived_by, item.waived_at))
            AuditLog().append(connection, "looker.reconciliation.waived", context.email, "looker_reconciliation", waived_id, {"dimension": dimension, "item_key": item_key, "parent_reconciliation_id": reconciliation_id})
        return self.report(waived_id)
