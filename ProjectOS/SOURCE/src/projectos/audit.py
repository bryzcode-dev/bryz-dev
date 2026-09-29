from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from .database import utc_now
from .validation import canonical_json, redact_sensitive


class AuditLog:
    def append(
        self,
        connection: sqlite3.Connection,
        event_type: str,
        actor: str,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, Any],
    ) -> str:
        audit_id = str(uuid4())
        connection.execute(
            "INSERT INTO audit_events "
            "(audit_id,event_type,actor,entity_type,entity_id,payload_json,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                audit_id,
                event_type,
                actor,
                entity_type,
                entity_id,
                canonical_json(redact_sensitive(dict(payload))),
                utc_now(),
            ),
        )
        return audit_id
