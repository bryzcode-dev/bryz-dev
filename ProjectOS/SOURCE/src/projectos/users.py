from __future__ import annotations

import json
import re
import sqlite3
from uuid import UUID, uuid4

from .audit import AuditLog
from .database import ProjectOSDatabase, utc_now
from .errors import ValidationError, VersionConflict
from .google.types import UserCreate, UserPatch, UserRecord, UserRole
from .validation import canonical_json, reject_secret_material, require_text

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        raise ValidationError("email is invalid")
    return email


class UserRepository:
    def __init__(
        self,
        database: ProjectOSDatabase,
        protected_owner_email: str,
        audit: AuditLog | None = None,
    ):
        self.database = database
        self.protected_owner_email = normalize_email(protected_owner_email)
        self.audit = audit or AuditLog()

    def seed_owner(self, email: str, display_name: str) -> UserRecord:
        normalized = normalize_email(email)
        if normalized != self.protected_owner_email:
            raise ValidationError("owner email does not match protected onboarding identity")
        existing = self.get_by_email(normalized)
        if existing:
            if not existing.protected_owner or existing.role is not UserRole.OWNER or not existing.active:
                raise ValidationError("protected owner record is invalid")
            return existing
        owner = UserCreate(normalized, require_text(display_name, "display_name"), UserRole.OWNER)
        return self._insert(owner, actor=normalized, protected_owner=True)

    def create(self, command: UserCreate, actor: str) -> UserRecord:
        if command.role is UserRole.OWNER:
            raise ValidationError("additional owners are prohibited")
        return self._insert(command, actor, protected_owner=False)

    def _insert(self, command: UserCreate, actor: str, protected_owner: bool) -> UserRecord:
        reject_secret_material(command.provenance)
        if not isinstance(command.role, UserRole):
            raise ValidationError("role is invalid")
        email = normalize_email(command.email)
        if email == self.protected_owner_email and not protected_owner:
            raise ValidationError("protected owner must be seeded")
        user_id = str(uuid4())
        now = utc_now()
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO users(user_id,email,display_name,role,active,protected_owner,notes,"
                    "provenance_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        user_id,
                        email,
                        require_text(command.display_name, "display_name"),
                        command.role.value,
                        int(command.active),
                        int(protected_owner),
                        command.notes,
                        canonical_json(dict(command.provenance)),
                        now,
                        now,
                    ),
                )
                self.audit.append(
                    connection, "user.created", actor, "user", user_id, {"role": command.role.value}
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError("user conflicts with an existing record") from exc
        return self.get(UUID(user_id))

    def get(self, user_id: UUID) -> UserRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM users WHERE user_id=?", (str(user_id),)
        ).fetchone()
        return self._record(row) if row else None

    def get_by_email(self, email: str) -> UserRecord | None:
        normalized = normalize_email(email)
        row = self.database.connection.execute(
            "SELECT * FROM users WHERE email=? COLLATE NOCASE", (normalized,)
        ).fetchone()
        return self._record(row) if row else None

    def list(self, active_only: bool = False) -> list[UserRecord]:
        where = "WHERE active=1" if active_only else ""
        rows = self.database.connection.execute(f"SELECT * FROM users {where} ORDER BY email")
        return [self._record(row) for row in rows]

    def update(
        self, user_id: UUID, expected_version: int, patch: UserPatch, actor: str
    ) -> UserRecord:
        current = self.get(user_id)
        if current is None:
            raise ValidationError("user does not exist")
        if current.version != expected_version:
            raise VersionConflict("user version conflict")
        if current.protected_owner and (
            (patch.email is not None and normalize_email(patch.email) != current.email)
            or (patch.role is not None and patch.role is not UserRole.OWNER)
            or patch.active is False
        ):
            raise ValidationError("protected owner cannot be changed")
        if not current.protected_owner and patch.role is UserRole.OWNER:
            raise ValidationError("additional owners are prohibited")
        if patch.provenance is not None:
            reject_secret_material(patch.provenance)
        email = normalize_email(patch.email) if patch.email is not None else current.email
        if email == self.protected_owner_email and not current.protected_owner:
            raise ValidationError("protected owner identity cannot be replaced")
        now = utc_now()
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    "UPDATE users SET email=?,display_name=?,role=?,active=?,notes=?,provenance_json=?,"
                    "version=version+1,updated_at=? WHERE user_id=? AND version=?",
                    (
                        email,
                        require_text(patch.display_name, "display_name")
                        if patch.display_name is not None
                        else current.display_name,
                        (patch.role or current.role).value,
                        int(patch.active if patch.active is not None else current.active),
                        patch.notes if patch.notes is not None else current.notes,
                        canonical_json(
                            dict(patch.provenance)
                            if patch.provenance is not None
                            else dict(current.provenance)
                        ),
                        now,
                        str(user_id),
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise VersionConflict("user version conflict")
                self.audit.append(connection, "user.updated", actor, "user", str(user_id), {})
        except sqlite3.IntegrityError as exc:
            raise ValidationError("user conflicts with an existing record") from exc
        return self.get(user_id)

    def deactivate(self, user_id: UUID, expected_version: int, actor: str) -> UserRecord:
        current = self.get(user_id)
        if current and current.protected_owner:
            raise ValidationError("protected owner cannot be deactivated")
        return self.update(user_id, expected_version, UserPatch(active=False), actor)

    @staticmethod
    def _record(row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            user_id=UUID(row["user_id"]),
            email=row["email"],
            display_name=row["display_name"],
            role=UserRole(row["role"]),
            active=bool(row["active"]),
            protected_owner=bool(row["protected_owner"]),
            notes=row["notes"],
            provenance=json.loads(row["provenance_json"]),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_access_at=row["last_access_at"],
        )
