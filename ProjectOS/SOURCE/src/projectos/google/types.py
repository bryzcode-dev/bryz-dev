from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID


class UserRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    USER = "USER"


@dataclass(frozen=True)
class UserCreate:
    email: str
    display_name: str
    role: UserRole
    notes: str = ""
    active: bool = True
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UserPatch:
    email: str | None = None
    display_name: str | None = None
    role: UserRole | None = None
    notes: str | None = None
    active: bool | None = None
    provenance: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class UserRecord:
    user_id: UUID
    email: str
    display_name: str
    role: UserRole
    active: bool
    protected_owner: bool
    notes: str
    provenance: Mapping[str, Any]
    version: int
    created_at: str
    updated_at: str
    last_access_at: str | None


@dataclass(frozen=True)
class GoogleBindingCreate:
    environment: str
    spreadsheet_id: str
    display_name: str
    contract_version: int
    credential_id: UUID
    gas_script_id: str | None = None
    gas_deployment_id: str | None = None
    enabled: bool = False
    write_enabled: bool = False
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GoogleBindingPatch:
    display_name: str | None = None
    contract_version: int | None = None
    credential_id: UUID | None = None
    gas_script_id: str | None = None
    gas_deployment_id: str | None = None
    enabled: bool | None = None
    write_enabled: bool | None = None
    status: str | None = None
    provenance: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class GoogleBindingRecord:
    binding_id: UUID
    environment: str
    spreadsheet_id: str
    display_name: str
    contract_version: int
    credential_id: UUID
    gas_script_id: str | None
    gas_deployment_id: str | None
    sharing_policy: str
    enabled: bool
    write_enabled: bool
    status: str
    version: int
    created_at: str
    updated_at: str
    last_preflight_at: str | None
    last_publication_revision: str | None
