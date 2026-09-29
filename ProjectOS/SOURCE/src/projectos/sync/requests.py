from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from projectos.audit import AuditLog
from projectos.database import ProjectOSDatabase, utc_now
from projectos.errors import ValidationError, VersionConflict
from projectos.google.contract import canonical_json_bytes
from projectos.types import ProjectVisibility
from projectos.users import UserRepository, normalize_email
from projectos.validation import canonical_json, reject_secret_material

from .authorization import AuthorizationService
from .mutations import MutationRegistry
from .types import Capability, OperationRequest


class RequestResultCode(StrEnum):
    ACCEPTED = "ACCEPTED"
    CONFLICT = "CONFLICT"
    REJECTED_AUTHORIZATION = "REJECTED_AUTHORIZATION"
    REJECTED_VALIDATION = "REJECTED_VALIDATION"
    REJECTED_TAMPERED = "REJECTED_TAMPERED"
    RETRYABLE_REMOTE_FAILURE = "RETRYABLE_REMOTE_FAILURE"


@dataclass(frozen=True)
class RemoteRequest:
    request_id: UUID
    request_schema_version: int
    actor_email: str
    actor_role_claim: str
    entity_type: str
    entity_id: UUID | None
    operation: str
    base_version: int
    changes: Mapping[str, Any]
    submitted_at: str
    client_request_hash: str
    gas_deployment_id: str
    source_row: int
    observed_at: str


@dataclass(frozen=True)
class RemoteAccessEvent:
    event_id: UUID
    actor_email: str
    accessed_at: str
    payload_hash: str
    source_row: int
    observed_at: str


@dataclass(frozen=True)
class RequestResult:
    request_id: UUID
    code: RequestResultCode
    message: str
    current_version: int | None = None
    conflict_id: UUID | None = None


def _request_payload(request: RemoteRequest) -> dict[str, Any]:
    return {
        "request_id": str(request.request_id),
        "request_schema_version": request.request_schema_version,
        "actor_email": request.actor_email.strip().lower(),
        "actor_role_claim": request.actor_role_claim,
        "entity_type": request.entity_type.lower(),
        "entity_id": str(request.entity_id) if request.entity_id else None,
        "operation": request.operation.upper(),
        "base_version": request.base_version,
        "changes": dict(request.changes),
        "submitted_at": request.submitted_at,
    }


def compute_request_hash(request: RemoteRequest) -> str:
    return hashlib.sha256(canonical_json_bytes(_request_payload(request))).hexdigest()


def _access_payload(event: RemoteAccessEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "actor_email": event.actor_email.strip().lower(),
        "accessed_at": event.accessed_at,
    }


def compute_access_hash(event: RemoteAccessEvent) -> str:
    return hashlib.sha256(canonical_json_bytes(_access_payload(event))).hexdigest()


def _safe_actor_email(value: str) -> str:
    try:
        return normalize_email(value)
    except ValidationError:
        return "invalid-caller@projectos.invalid"


class RequestProcessor:
    def __init__(
        self,
        database: ProjectOSDatabase,
        binding_id: UUID,
        authorization: AuthorizationService,
        mutations: MutationRegistry,
        audit: AuditLog | None = None,
    ):
        self.database = database
        self.binding_id = binding_id
        self.authorization = authorization
        self.mutations = mutations
        self.audit = audit or AuditLog()

    def ingest(self, request: RemoteRequest) -> RequestResult:
        try:
            reject_secret_material(dict(request.changes))
        except ValidationError:
            return RequestResult(
                request.request_id,
                RequestResultCode.REJECTED_VALIDATION,
                "Request validation failed",
            )
        if request.request_schema_version != 1 or compute_request_hash(request) != request.client_request_hash:
            return RequestResult(
                request.request_id,
                RequestResultCode.REJECTED_VALIDATION,
                "Request validation failed",
            )

        receipt = self.database.connection.execute(
            "SELECT * FROM remote_request_receipts WHERE binding_id=? AND request_id=?",
            (str(self.binding_id), str(request.request_id)),
        ).fetchone()
        if receipt:
            if receipt["payload_hash"] != request.client_request_hash:
                with self.database.transaction() as connection:
                    self.audit.append(
                        connection,
                        "remote_request.tampered",
                        "projectos-sync",
                        "remote_request",
                        str(request.request_id),
                        {},
                    )
                return RequestResult(
                    request.request_id,
                    RequestResultCode.REJECTED_TAMPERED,
                    "Request integrity check failed",
                )
            return self._durable_result(request.request_id)

        receipt_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO remote_request_receipts(receipt_id,binding_id,request_id,payload_hash,"
                "payload_json,source_row,observed_at,processing_status) VALUES(?,?,?,?,?,?,?,?)",
                (
                    receipt_id,
                    str(self.binding_id),
                    str(request.request_id),
                    request.client_request_hash,
                    canonical_json(_request_payload(request)),
                    request.source_row,
                    request.observed_at,
                    "PENDING",
                ),
            )

        context = self.authorization.resolve(request.actor_email)
        visibility = self._visibility(request)
        operation = OperationRequest(
            request.entity_type.lower(),
            request.operation.upper(),
            visibility,
            frozenset(request.changes),
        )
        if not self.authorization.authorize_operation(context, operation):
            return self._reject(
                request, receipt_id, RequestResultCode.REJECTED_AUTHORIZATION, "Request not permitted"
            )

        current = None
        if request.operation.upper() != "CREATE" and request.entity_id is not None:
            current = self.mutations.current(request.entity_type.lower(), request.entity_id)
            if current is None:
                return self._reject(
                    request,
                    receipt_id,
                    RequestResultCode.REJECTED_AUTHORIZATION,
                    "Request not permitted",
                )
            if current.version != request.base_version:
                return self._conflict(request, receipt_id, current.version)

        try:
            with self.database.transaction() as connection:
                self._insert_change_request(connection, request, "PENDING", None, None)
                result = self.mutations.apply(request, context)
                connection.execute(
                    "UPDATE change_requests SET status='ACCEPTED',result_code=?,result_message=?,"
                    "current_version=?,resolved_at=? WHERE request_id=?",
                    (
                        RequestResultCode.ACCEPTED.value,
                        "Request accepted",
                        result.version,
                        utc_now(),
                        str(request.request_id),
                    ),
                )
                connection.execute(
                    "UPDATE remote_request_receipts SET processing_status='ACCEPTED',local_request_id=?,"
                    "processed_at=? WHERE receipt_id=?",
                    (str(request.request_id), utc_now(), receipt_id),
                )
            return RequestResult(
                request.request_id,
                RequestResultCode.ACCEPTED,
                "Request accepted",
                result.version,
            )
        except (ValidationError, VersionConflict, sqlite3.DatabaseError, TypeError, ValueError, KeyError):
            return self._mark_receipt_failure(request, receipt_id)

    def process(self, request: RemoteRequest) -> RequestResult:
        return self.ingest(request)

    def _visibility(self, request: RemoteRequest) -> ProjectVisibility | None:
        if request.operation.upper() == "CREATE":
            if request.entity_type.lower() == "project":
                try:
                    return ProjectVisibility(str(request.changes.get("visibility", "PUBLIC")))
                except ValueError:
                    return None
            project_id = request.changes.get("project_id")
            if project_id:
                project = self.mutations.projects.get(UUID(str(project_id)))
                return project.visibility if project else None
            return None
        if request.entity_id is None:
            return None
        return self.mutations.visibility(request.entity_type.lower(), request.entity_id)

    def _insert_change_request(
        self,
        connection: sqlite3.Connection,
        request: RemoteRequest,
        status: str,
        result_code: RequestResultCode | None,
        result_message: str | None,
    ) -> None:
        connection.execute(
            "INSERT INTO change_requests(request_id,actor_email,entity_type,entity_id,base_version,"
            "changes_json,status,reason,submitted_at,request_schema_version,operation,actor_role_claim,"
            "client_request_hash,binding_id,source_row,observed_at,result_code,result_message) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(request.request_id),
                _safe_actor_email(request.actor_email),
                request.entity_type.lower(),
                str(request.entity_id) if request.entity_id else "",
                request.base_version,
                canonical_json(dict(request.changes)),
                status,
                result_message,
                request.submitted_at,
                request.request_schema_version,
                request.operation.upper(),
                request.actor_role_claim,
                request.client_request_hash,
                str(self.binding_id),
                request.source_row,
                request.observed_at,
                result_code.value if result_code else None,
                result_message,
            ),
        )

    def _reject(
        self,
        request: RemoteRequest,
        receipt_id: str,
        code: RequestResultCode,
        message: str,
    ) -> RequestResult:
        with self.database.transaction() as connection:
            self._insert_change_request(connection, request, "REJECTED", code, message)
            connection.execute(
                "UPDATE remote_request_receipts SET processing_status=?,local_request_id=?,processed_at=? "
                "WHERE receipt_id=?",
                (code.value, str(request.request_id), utc_now(), receipt_id),
            )
        return RequestResult(request.request_id, code, message)

    def _mark_receipt_failure(self, request: RemoteRequest, receipt_id: str) -> RequestResult:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE remote_request_receipts SET processing_status=?,processed_at=? WHERE receipt_id=?",
                (RequestResultCode.REJECTED_VALIDATION.value, utc_now(), receipt_id),
            )
        return RequestResult(
            request.request_id,
            RequestResultCode.REJECTED_VALIDATION,
            "Request validation failed",
        )

    def _conflict(
        self, request: RemoteRequest, receipt_id: str, current_version: int
    ) -> RequestResult:
        conflict_id = uuid4()
        with self.database.transaction() as connection:
            self._insert_change_request(
                connection, request, "CONFLICT", RequestResultCode.CONFLICT, "Version conflict"
            )
            connection.execute(
                "UPDATE change_requests SET current_version=?,resolved_at=? WHERE request_id=?",
                (current_version, utc_now(), str(request.request_id)),
            )
            connection.execute(
                "INSERT INTO conflicts(conflict_id,request_id,current_version,current_json,proposed_json,"
                "status,created_at) VALUES(?,?,?,?,?,'OPEN',?)",
                (
                    str(conflict_id),
                    str(request.request_id),
                    current_version,
                    "{}",
                    canonical_json(dict(request.changes)),
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE remote_request_receipts SET processing_status='CONFLICT',local_request_id=?,"
                "conflict_id=?,processed_at=? WHERE receipt_id=?",
                (str(request.request_id), str(conflict_id), utc_now(), receipt_id),
            )
        return RequestResult(
            request.request_id,
            RequestResultCode.CONFLICT,
            "Version conflict",
            current_version,
            conflict_id,
        )

    def _durable_result(self, request_id: UUID) -> RequestResult:
        row = self.database.connection.execute(
            "SELECT result_code,result_message,current_version FROM change_requests WHERE request_id=?",
            (str(request_id),),
        ).fetchone()
        if row is None:
            receipt = self.database.connection.execute(
                "SELECT processing_status FROM remote_request_receipts WHERE request_id=?",
                (str(request_id),),
            ).fetchone()
            code = RequestResultCode(receipt["processing_status"])
            return RequestResult(request_id, code, "Request validation failed")
        conflict = self.database.connection.execute(
            "SELECT conflict_id FROM conflicts WHERE request_id=?", (str(request_id),)
        ).fetchone()
        return RequestResult(
            request_id,
            RequestResultCode(row["result_code"]),
            row["result_message"],
            row["current_version"],
            UUID(conflict["conflict_id"]) if conflict else None,
        )

    def verify_remote_history(self, requests: Sequence[RemoteRequest]) -> bool:
        if any(compute_request_hash(request) != request.client_request_hash for request in requests):
            raise ValueError("historical remote request payload was edited or deleted")
        observed = {str(request.request_id): request.client_request_hash for request in requests}
        rows = self.database.connection.execute(
            "SELECT request_id,payload_hash FROM remote_request_receipts WHERE binding_id=?",
            (str(self.binding_id),),
        ).fetchall()
        expected = {row["request_id"]: row["payload_hash"] for row in rows}
        if observed != expected:
            raise ValueError("historical remote request payload was edited or deleted")
        return True

    def resolve_conflict(
        self, conflict_id: UUID | None, actor_email: str, strategy: str
    ) -> RequestResult:
        if conflict_id is None:
            raise ValidationError("conflict_id is required")
        context = self.authorization.resolve(actor_email)
        if Capability.RESOLVE_CONFLICTS not in context.capabilities:
            return RequestResult(
                uuid4(), RequestResultCode.REJECTED_AUTHORIZATION, "Request not permitted"
            )
        conflict = self.database.connection.execute(
            "SELECT * FROM conflicts WHERE conflict_id=? AND status='OPEN'", (str(conflict_id),)
        ).fetchone()
        if conflict is None or strategy != "KEEP_CANONICAL":
            raise ValidationError("conflict resolution is invalid")
        resolution_id = uuid4()
        submitted_at = utc_now()
        payload = {
            "conflict_id": str(conflict_id),
            "strategy": strategy,
            "actor_email": normalize_email(actor_email),
        }
        payload_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO change_requests(request_id,actor_email,entity_type,entity_id,base_version,"
                "changes_json,status,submitted_at,request_schema_version,operation,actor_role_claim,"
                "client_request_hash,binding_id,result_code,result_message,resolved_at) "
                "VALUES(?,?,?,?,?,?, 'ACCEPTED',?,1,'UPDATE','OWNER',?,?,?,'Conflict resolved',?)",
                (
                    str(resolution_id),
                    normalize_email(actor_email),
                    "conflict_resolution",
                    str(conflict_id),
                    conflict["current_version"],
                    canonical_json({"strategy": strategy}),
                    submitted_at,
                    payload_hash,
                    str(self.binding_id),
                    RequestResultCode.ACCEPTED.value,
                    submitted_at,
                ),
            )
            connection.execute(
                "UPDATE conflicts SET status='RESOLVED',resolved_at=?,resolution_json=? WHERE conflict_id=?",
                (submitted_at, canonical_json(payload), str(conflict_id)),
            )
            self.audit.append(
                connection,
                "conflict.resolved",
                normalize_email(actor_email),
                "conflict",
                str(conflict_id),
                {"strategy": strategy, "resolution_request_id": str(resolution_id)},
            )
        return RequestResult(
            resolution_id, RequestResultCode.ACCEPTED, "Conflict resolved", conflict["current_version"]
        )


class AccessEventProcessor:
    def __init__(
        self, database: ProjectOSDatabase, binding_id: UUID, protected_owner_email: str
    ):
        self.database = database
        self.binding_id = binding_id
        self.users = UserRepository(database, protected_owner_email)

    def ingest(self, event: RemoteAccessEvent) -> str:
        if compute_access_hash(event) != event.payload_hash:
            raise ValidationError("access event hash is invalid")
        email = normalize_email(event.actor_email)
        existing = self.database.connection.execute(
            "SELECT payload_hash,processing_status FROM remote_access_receipts WHERE event_id=?",
            (str(event.event_id),),
        ).fetchone()
        if existing:
            if existing["payload_hash"] != event.payload_hash:
                raise ValidationError("access event UUID was reused with different content")
            return existing["processing_status"]
        user = self.users.get_by_email(email)
        if user is None or not user.active:
            raise ValidationError("access event actor is not active")
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO remote_access_receipts(event_id,binding_id,actor_email,accessed_at,"
                "payload_hash,source_row,observed_at,processing_status,processed_at) "
                "VALUES(?,?,?,?,?,?,?,'ACCEPTED',?)",
                (
                    str(event.event_id),
                    str(self.binding_id),
                    email,
                    event.accessed_at,
                    event.payload_hash,
                    event.source_row,
                    event.observed_at,
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE users SET last_access_at=CASE WHEN last_access_at IS NULL OR last_access_at<? "
                "THEN ? ELSE last_access_at END,updated_at=? WHERE user_id=?",
                (event.accessed_at, event.accessed_at, utc_now(), str(user.user_id)),
            )
        return "ACCEPTED"
