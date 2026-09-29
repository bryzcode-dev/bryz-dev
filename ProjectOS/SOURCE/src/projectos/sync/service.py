from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID, uuid4

from projectos.bindings import GoogleBindingRepository
from projectos.database import ProjectOSDatabase, utc_now
from projectos.google.bootstrap import WorkbookBootstrapPlanner
from projectos.google.contract import WorkbookContract
from projectos.google.gateway import GoogleGateway
from projectos.health import ProjectOSDoctor
from projectos.errors import ValidationError

from .authorization import AuthorizationService
from .lock import LockOwner, LockUnavailable, ProjectOSFileLock
from .mutations import MutationRegistry
from .projection import ProjectionBuilder, ProjectionPublisher, safe_result_rows
from .requests import (
    AccessEventProcessor,
    RemoteAccessEvent,
    RemoteRequest,
    RequestProcessor,
)


@dataclass(frozen=True)
class SyncPlan:
    ready: bool
    codes: tuple[str, ...]
    action_count: int
    blocked: bool


@dataclass(frozen=True)
class SyncRunResult:
    run_id: UUID
    status: str
    request_count: int = 0
    access_count: int = 0
    projection_count: int = 0
    error_code: str | None = None
    lock_owner: LockOwner | None = None


@dataclass(frozen=True)
class SyncStatus:
    binding_id: UUID
    checkpoint: str | None
    last_run_id: UUID | None
    last_status: str | None
    active_revision: UUID | None


class GoogleSyncService:
    def __init__(
        self,
        database: ProjectOSDatabase,
        protected_owner_email: str,
        gateway: GoogleGateway,
        lock_path: Path,
    ):
        self.database = database
        self.protected_owner_email = protected_owner_email
        self.gateway = gateway
        self.lock_path = Path(lock_path)
        self.bindings = GoogleBindingRepository(database)

    def plan(self, binding_id: UUID) -> SyncPlan:
        binding = self.bindings.get(binding_id)
        if binding is None:
            return SyncPlan(False, ("BINDING_NOT_FOUND",), 0, True)
        preflight = self.gateway.preflight(binding)
        if not preflight.ok:
            return SyncPlan(False, preflight.codes, 0, True)
        snapshot = self.gateway.read_contract(binding)
        bootstrap = WorkbookBootstrapPlanner().plan(snapshot, WorkbookContract.current())
        return SyncPlan(not bootstrap.blocked, (), len(bootstrap.actions), bootstrap.blocked)

    def status(self, binding_id: UUID) -> SyncStatus:
        checkpoint = self.database.connection.execute(
            "SELECT checkpoint_value FROM sync_checkpoints WHERE checkpoint_key=?",
            (self._checkpoint_key(binding_id),),
        ).fetchone()
        run = self.database.connection.execute(
            "SELECT run_id,status FROM sync_runs WHERE binding_id=? ORDER BY started_at DESC,run_id DESC LIMIT 1",
            (str(binding_id),),
        ).fetchone()
        active = self.database.connection.execute(
            "SELECT revision_id FROM projection_revisions WHERE binding_id=? AND state='ACTIVE'",
            (str(binding_id),),
        ).fetchone()
        return SyncStatus(
            binding_id,
            checkpoint["checkpoint_value"] if checkpoint else None,
            UUID(run["run_id"]) if run else None,
            run["status"] if run else None,
            UUID(active["revision_id"]) if active else None,
        )

    def run(
        self,
        binding_id: UUID,
        trigger: str,
        *,
        wait_seconds: float = 0.0,
        monotonic=time.monotonic,
        sleeper=time.sleep,
    ) -> SyncRunResult:
        if (
            isinstance(wait_seconds, bool)
            or not isinstance(wait_seconds, (int, float))
            or not 0 <= wait_seconds <= 30
        ):
            raise ValidationError("sync lock wait must be between zero and thirty seconds")
        run_id = uuid4()
        deadline = monotonic() + float(wait_seconds)
        while True:
            try:
                with ProjectOSFileLock(self.lock_path, trigger, str(run_id)):
                    return self._run_locked(run_id, binding_id, trigger)
            except LockUnavailable:
                owner = ProjectOSFileLock.read_owner(self.lock_path)
                remaining = deadline - monotonic()
                if owner is None or remaining <= 0:
                    return SyncRunResult(
                        run_id,
                        "LOCKED",
                        error_code="SYNC_LOCKED",
                        lock_owner=owner,
                    )
                sleeper(remaining)

    def _run_locked(self, run_id: UUID, binding_id: UUID, trigger: str) -> SyncRunResult:
        checkpoint = self.status(binding_id).checkpoint or "0"
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO sync_runs(run_id,trigger,status,started_at,summary_json,binding_id,"
                "starting_checkpoint) VALUES(?,?, 'RUNNING',?,'{}',?,?)",
                (str(run_id), trigger, utc_now(), str(binding_id), checkpoint),
            )
        try:
            report = ProjectOSDoctor(self.database).check()
            if not report.healthy:
                return self._finish_failed(run_id, "HEALTH_FAILED", "HEALTH_FAILED")
            binding = self.bindings.assert_write_ready(binding_id)
            preflight = self.gateway.preflight(binding)
            if not preflight.ok:
                return self._finish_failed(
                    run_id, "PREFLIGHT_FAILED", preflight.codes[0] if preflight.codes else "PREFLIGHT_FAILED"
                )
            snapshot = self.gateway.read_contract(binding)
            bootstrap = WorkbookBootstrapPlanner().plan(snapshot, WorkbookContract.current())
            if bootstrap.blocked:
                return self._finish_failed(run_id, "PREFLIGHT_FAILED", "WORKBOOK_DRIFT")

            request_batch = self.gateway.pull_requests(binding, checkpoint)
            access_batch = self.gateway.pull_access_events(binding, checkpoint)
            authorization = AuthorizationService(self.database, self.protected_owner_email)
            mutations = MutationRegistry(self.database, self.protected_owner_email)
            request_processor = RequestProcessor(
                self.database, binding_id, authorization, mutations
            )
            access_processor = AccessEventProcessor(
                self.database, binding_id, self.protected_owner_email
            )
            requests = [self._remote_request(row) for row in request_batch.rows]
            events = [self._remote_access(row) for row in access_batch.rows]
            results = [request_processor.ingest(request) for request in requests]
            for event in events:
                access_processor.ingest(event)

            self.gateway.publish_results(binding, safe_result_rows(results))
            bundle = ProjectionBuilder().build(self.database.connection, uuid4())
            publication = ProjectionPublisher(self.database).stage_and_activate(
                binding, bundle, self.gateway
            )
            if not publication.verified:
                return self._finish_failed(run_id, "FAILED", "PROJECTION_VERIFY_FAILED")
            ending_checkpoint = str(
                max(int(request_batch.cursor or "0"), int(access_batch.cursor or "0"))
            )
            summary = {
                "request_count": len(results),
                "access_count": len(events),
                "projection_count": 1,
            }
            now = utc_now()
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO sync_checkpoints(checkpoint_key,checkpoint_value,updated_at,binding_id) "
                    "VALUES(?,?,?,?) ON CONFLICT(checkpoint_key) DO UPDATE SET "
                    "checkpoint_value=excluded.checkpoint_value,updated_at=excluded.updated_at,"
                    "binding_id=excluded.binding_id",
                    (self._checkpoint_key(binding_id), ending_checkpoint, now, str(binding_id)),
                )
                connection.execute(
                    "UPDATE sync_runs SET status='COMPLETE',finished_at=?,summary_json=?,"
                    "ending_checkpoint=? WHERE run_id=?",
                    (
                        now,
                        json.dumps(summary, sort_keys=True, separators=(",", ":")),
                        ending_checkpoint,
                        str(run_id),
                    ),
                )
            return SyncRunResult(run_id, "COMPLETE", len(results), len(events), 1)
        except BaseException as exc:
            return self._finish_failed(run_id, "FAILED", self._safe_error_code(exc))

    def _finish_failed(self, run_id: UUID, status: str, error_code: str) -> SyncRunResult:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE sync_runs SET status=?,finished_at=?,summary_json=?,error_code=? WHERE run_id=?",
                (
                    status,
                    utc_now(),
                    json.dumps({"error_code": error_code}, separators=(",", ":")),
                    error_code,
                    str(run_id),
                ),
            )
        return SyncRunResult(run_id, status, error_code=error_code)

    @staticmethod
    def _safe_error_code(exc: BaseException) -> str:
        name = type(exc).__name__.upper()
        return name[:64] if name else "SYNC_FAILED"

    @staticmethod
    def _checkpoint_key(binding_id: UUID) -> str:
        return f"google:{binding_id}"

    @staticmethod
    def _remote_request(row: Mapping[str, Any]) -> RemoteRequest:
        return RemoteRequest(
            request_id=UUID(str(row["request_id"])),
            request_schema_version=int(row["request_schema_version"]),
            actor_email=str(row["actor_email"]),
            actor_role_claim=str(row["actor_role_claim"]),
            entity_type=str(row["entity_type"]),
            entity_id=UUID(str(row["entity_id"])) if row.get("entity_id") else None,
            operation=str(row["operation"]),
            base_version=int(row["base_version"]),
            changes=dict(row["changes"]),
            submitted_at=str(row["submitted_at"]),
            client_request_hash=str(row["client_request_hash"]),
            gas_deployment_id=str(row["gas_deployment_id"]),
            source_row=int(row["source_row"]),
            observed_at=str(row["observed_at"]),
        )

    @staticmethod
    def _remote_access(row: Mapping[str, Any]) -> RemoteAccessEvent:
        return RemoteAccessEvent(
            event_id=UUID(str(row["event_id"])),
            actor_email=str(row["actor_email"]),
            accessed_at=str(row["accessed_at"]),
            payload_hash=str(row["payload_hash"]),
            source_row=int(row["source_row"]),
            observed_at=str(row["observed_at"]),
        )
