from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .errors import ValidationError

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "privatekey",
    "apikey",
    "refreshtoken",
    "recoverycode",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
)


def require_text(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValidationError(f"{field} is required")
    return cleaned


def validate_slug(value: str) -> str:
    slug = require_text(value, "slug")
    if not SLUG_PATTERN.fullmatch(slug):
        raise ValidationError("slug must contain lowercase letters, numbers, and single hyphens")
    return slug


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"value is not JSON serializable: {exc}") from exc


def normalize_path(value: str) -> str:
    resolved = str(Path(value).resolve(strict=False))
    if sys.platform == "darwin" and resolved.startswith("/var/"):
        return "/private" + resolved
    return resolved


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _sensitive_key(value: object) -> bool:
    normalized = _normalized_key(value)
    return normalized in SENSITIVE_KEYS or any(
        normalized.endswith(item) for item in SENSITIVE_KEYS
    )


def reject_secret_material(value: Any, path: str = "$.") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if _sensitive_key(key):
                raise ValidationError(f"secret material is prohibited at {path}{key}")
            reject_secret_material(nested, f"{path}{key}.")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            reject_secret_material(nested, f"{path}{index}.")
        return
    if isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise ValidationError(f"secret material is prohibited at {path.rstrip('.')}")


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _sensitive_key(key) else redact_sensitive(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_PATTERNS):
        return "[REDACTED]"
    return value
