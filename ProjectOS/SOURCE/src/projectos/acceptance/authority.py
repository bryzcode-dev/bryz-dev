from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Sequence
from uuid import uuid4

from projectos.adoption.fixture import FIXTURE_MARKER
from projectos.adoption.host import HostFamily, detect_host_family
from projectos.adoption.path_policy import HostPathPolicy
from projectos.errors import ValidationError


ACCEPTANCE_MARKER = ".projectos-acceptance-v1"
ACCEPTANCE_ACKNOWLEDGEMENT = "CLEAN_HOST_NATIVE_ACCEPTANCE"
_MARKER_FORMAT = "projectos-acceptance-root-v1"
_RECEIPT_FORMAT = "projectos-acceptance-receipt-v1"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256(value: str | bytes) -> str:
    content = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(content).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class HostSession:
    host_family: HostFamily
    host_fingerprint: str
    elevated: bool
    standard_user: bool

    def __post_init__(self) -> None:
        if len(self.host_fingerprint) != 64 or any(
            item not in "0123456789abcdef" for item in self.host_fingerprint
        ):
            raise ValidationError("host fingerprint is invalid")


def _is_windows_elevated() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        raise ValidationError("Windows elevation state is unavailable")


def detect_host_session() -> HostSession:
    family = detect_host_family()
    elevated = _is_windows_elevated() if family is HostFamily.WINDOWS else os.geteuid() == 0
    identity_material = "|".join(
        (family.value, platform.node(), str(uuid.getnode()), str(getattr(os, "getuid", lambda: 0)()))
    )
    return HostSession(family, _sha256(identity_material), elevated, not elevated)


def _receipt_path(runtime_root: Path, receipt_id: str) -> Path:
    return runtime_root / "acceptance" / "receipts" / f"{receipt_id}.json"


def _assert_separate(
    family: HostFamily,
    root: str | PurePath,
    runtime: str | PurePath,
    excluded_roots: Sequence[str | PurePath],
) -> None:
    policy = HostPathPolicy(family)
    root_value = policy.normalize(root)
    runtime_value = policy.normalize(runtime)
    if policy.is_within(root_value, runtime_value) or policy.is_within(runtime_value, root_value):
        raise ValidationError("acceptance and runtime roots must be separate")
    for excluded in excluded_roots:
        excluded_value: str | PurePath = excluded
        if family is HostFamily.MACOS:
            excluded_value = Path(excluded).expanduser().resolve(strict=False)
        if policy.is_within(root_value, excluded_value) or policy.is_within(excluded_value, root_value):
            raise ValidationError("acceptance root must be outside excluded roots")
        if policy.is_within(runtime_value, excluded_value) or policy.is_within(excluded_value, runtime_value):
            raise ValidationError("acceptance runtime must be outside excluded roots")


@dataclass(frozen=True)
class AcceptanceTarget:
    acceptance_id: str
    receipt_id: str
    root: Path
    runtime_root: Path
    host_family: HostFamily
    host_fingerprint: str

    @classmethod
    def issue(
        cls,
        root: str | Path,
        runtime_root: str | Path,
        host_family: HostFamily,
        *,
        excluded_roots: Sequence[str | PurePath] = (),
    ) -> AcceptanceTarget:
        family = HostFamily(host_family)
        session = detect_host_session()
        if session.host_family is not family:
            raise ValidationError("acceptance host family does not match current host")
        if session.elevated or not session.standard_user:
            raise ValidationError("acceptance authority requires a non-elevated standard user")
        root_input = Path(root)
        runtime_input = Path(runtime_root)
        if root_input.is_symlink() or runtime_input.is_symlink():
            raise ValidationError("acceptance roots cannot use a symlink")
        selected_root = root_input.expanduser().resolve(strict=False)
        selected_runtime = runtime_input.expanduser().resolve(strict=False)
        _assert_separate(family, selected_root, selected_runtime, excluded_roots)
        if selected_root.exists():
            if not selected_root.is_dir():
                raise ValidationError("acceptance root must be a directory")
            if any(selected_root.iterdir()):
                raise ValidationError("acceptance root must be empty")
        if (selected_root / FIXTURE_MARKER).exists() or (selected_root / "context-os").exists():
            raise ValidationError("acceptance root cannot be a ContextOS or fixture root")
        selected_root.mkdir(parents=True, exist_ok=True)
        acceptance_id = str(uuid4())
        receipt_id = str(uuid4())
        marker = {
            "acceptance_id": acceptance_id,
            "format": _MARKER_FORMAT,
            "receipt_id": receipt_id,
        }
        marker_bytes = _canonical(marker)
        receipt = {
            "acceptance_id": acceptance_id,
            "format": _RECEIPT_FORMAT,
            "host_family": family.value,
            "host_fingerprint_sha256": session.host_fingerprint,
            "marker_sha256": _sha256(marker_bytes),
            "receipt_id": receipt_id,
            "root_sha256": _sha256(str(selected_root)),
            "runtime_sha256": _sha256(str(selected_runtime)),
        }
        _atomic_write(selected_root / ACCEPTANCE_MARKER, marker_bytes)
        _atomic_write(_receipt_path(selected_runtime, receipt_id), _canonical(receipt))
        return cls(
            acceptance_id,
            receipt_id,
            selected_root,
            selected_runtime,
            family,
            session.host_fingerprint,
        )

    @classmethod
    def open(
        cls,
        root: str | Path,
        runtime_root: str | Path,
        acknowledgement: str,
        session: HostSession,
        *,
        excluded_roots: Sequence[str | PurePath] = (),
    ) -> AcceptanceTarget:
        if acknowledgement != ACCEPTANCE_ACKNOWLEDGEMENT:
            raise ValidationError("acceptance acknowledgement is invalid")
        if session.elevated or not session.standard_user:
            raise ValidationError("acceptance authority rejects an elevated session")
        selected_root = Path(root).expanduser().resolve(strict=False)
        selected_runtime = Path(runtime_root).expanduser().resolve(strict=False)
        if Path(root).is_symlink() or Path(runtime_root).is_symlink():
            raise ValidationError("acceptance roots cannot use a symlink")
        try:
            marker_bytes = (selected_root / ACCEPTANCE_MARKER).read_bytes()
            marker = json.loads(marker_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("acceptance marker is missing or invalid") from exc
        if not isinstance(marker, dict) or set(marker) != {"acceptance_id", "format", "receipt_id"}:
            raise ValidationError("acceptance marker is invalid")
        if marker.get("format") != _MARKER_FORMAT or marker_bytes != _canonical(marker):
            raise ValidationError("acceptance marker is invalid")
        receipt_id = str(marker["receipt_id"])
        try:
            receipt_bytes = _receipt_path(selected_runtime, receipt_id).read_bytes()
            receipt = json.loads(receipt_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("acceptance receipt is missing or invalid") from exc
        family_value = receipt.get("host_family") if isinstance(receipt, dict) else None
        try:
            family = HostFamily(family_value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("acceptance receipt is invalid") from exc
        if session.host_family is not family:
            raise ValidationError("acceptance host family does not match receipt")
        _assert_separate(family, selected_root, selected_runtime, excluded_roots)
        expected = {
            "acceptance_id": marker["acceptance_id"],
            "format": _RECEIPT_FORMAT,
            "host_family": family.value,
            "host_fingerprint_sha256": session.host_fingerprint,
            "marker_sha256": _sha256(marker_bytes),
            "receipt_id": receipt_id,
            "root_sha256": _sha256(str(selected_root)),
            "runtime_sha256": _sha256(str(selected_runtime)),
        }
        if receipt != expected or receipt_bytes != _canonical(expected):
            if isinstance(receipt, dict) and receipt.get("host_fingerprint_sha256") != session.host_fingerprint:
                raise ValidationError("acceptance receipt does not match this host")
            raise ValidationError("acceptance receipt does not match root and runtime")
        return cls(
            str(marker["acceptance_id"]), receipt_id, selected_root, selected_runtime,
            family, session.host_fingerprint,
        )

    def assert_runtime_path(self, path: str | PurePath) -> None:
        policy = HostPathPolicy(self.host_family)
        if not policy.is_within(path, self.runtime_root):
            raise ValidationError("acceptance path must stay within the isolated runtime")
