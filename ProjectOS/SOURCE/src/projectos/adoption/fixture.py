from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Mapping
from uuid import uuid4

from projectos.adoption.contextos import ContextOSInstallation
from projectos.adoption.host import HostFamily
from projectos.adoption.path_policy import HostPathPolicy
from projectos.errors import ValidationError
from projectos.validation import require_text


FIXTURE_MARKER = ".projectos-contextos-fixture-v1"
_FIXTURE_FORMAT = "projectos-contextos-fixture-v1"
_RECEIPT_FORMAT = "projectos-contextos-fixture-receipt-v1"
_ACKNOWLEDGEMENT = "FIXTURE_ONLY"


def _canonical(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


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


def _mapping(path: Path, label: str) -> tuple[dict[str, object], bytes]:
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"fixture {label} is missing or invalid") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"fixture {label} is missing or invalid")
    return value, content


def assert_fixture_separation(
    family: HostFamily,
    target_root: str | PurePath,
    runtime_root: str | PurePath,
) -> None:
    policy = HostPathPolicy(HostFamily(family))
    try:
        target = policy.normalize(target_root)
        runtime = policy.normalize(runtime_root)
    except ValidationError as exc:
        raise ValidationError("fixture and runtime roots must be absolute") from exc
    if policy.is_within(target, runtime) or policy.is_within(runtime, target):
        raise ValidationError("fixture and runtime roots must be separate")


@dataclass(frozen=True)
class FixtureReceipt:
    fixture_id: str
    root: Path
    host_family: HostFamily
    marker_sha256: str


def _receipt_path(runtime_root: Path, fixture_id: str) -> Path:
    return (
        runtime_root
        / "adoption"
        / "fixture-receipts"
        / f"{fixture_id}.json"
    )


def issue_empty_fixture(
    root: str | Path,
    runtime_root: str | Path,
    family: HostFamily,
    machine_id: str,
    contextos_version: str = "3.0.1",
) -> FixtureReceipt:
    selected_family = HostFamily(family)
    target_input = Path(root)
    runtime = Path(runtime_root).expanduser().resolve(strict=False)
    if target_input.is_symlink():
        raise ValidationError("fixture root cannot be a symlink")
    target = target_input.expanduser().resolve(strict=False)
    assert_fixture_separation(selected_family, target, runtime)
    if target.exists():
        if not target.is_dir():
            raise ValidationError("fixture root must be a directory")
        if any(target.iterdir()):
            raise ValidationError("fixture root must be empty")
    target.mkdir(parents=True, exist_ok=True)

    fixture_id = str(uuid4())
    marker = {"format": _FIXTURE_FORMAT, "fixture_id": fixture_id}
    marker_bytes = _canonical(marker)
    marker_sha256 = hashlib.sha256(marker_bytes).hexdigest()
    machine = {"machine_id": require_text(machine_id, "machine_id")}
    contract = {
        "contract_version": 1,
        "contextos_version": require_text(contextos_version, "contextos_version"),
        "extensions_root": "context-os/extensions",
        "skills_root": "skills",
        "runtime_root_template": "fixture-local-runtime",
        "supported_hosts": [selected_family.value],
    }
    (target / "context-os/extensions").mkdir(parents=True, exist_ok=True)
    (target / "skills").mkdir(parents=True, exist_ok=True)
    _atomic_write(target / FIXTURE_MARKER, marker_bytes)
    _atomic_write(
        target / "context-os/config/extension-contract.json", _canonical(contract)
    )
    _atomic_write(target / "context-os-machine.json", _canonical(machine))

    receipt_mapping = {
        "fixture_id": fixture_id,
        "format": _RECEIPT_FORMAT,
        "host_family": selected_family.value,
        "marker_sha256": marker_sha256,
        "root": str(target),
    }
    _atomic_write(_receipt_path(runtime, fixture_id), _canonical(receipt_mapping))
    return FixtureReceipt(fixture_id, target, selected_family, marker_sha256)


def _assert_no_managed_symlink(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValidationError("managed path must stay within fixture root") from exc
    current = root
    if current.is_symlink():
        raise ValidationError("fixture managed path cannot contain a symlink")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValidationError("fixture managed path cannot contain a symlink")


@dataclass(frozen=True)
class FixtureInstallationTarget:
    fixture_id: str
    root: Path
    extensions_root: Path
    skills_root: Path
    registry_path: Path

    @classmethod
    def open(
        cls,
        installation: ContextOSInstallation,
        runtime_root: str | Path,
        acknowledgement: str,
    ) -> "FixtureInstallationTarget":
        if acknowledgement != _ACKNOWLEDGEMENT:
            raise ValidationError("fixture acknowledgement must be FIXTURE_ONLY")
        root = installation.root.resolve(strict=False)
        runtime = Path(runtime_root).expanduser().resolve(strict=False)
        family = (
            HostFamily.WINDOWS
            if HostFamily.WINDOWS in installation.contract.supported_hosts
            and HostFamily.MACOS not in installation.contract.supported_hosts
            else HostFamily.MACOS
        )
        assert_fixture_separation(family, root, runtime)
        marker, marker_bytes = _mapping(root / FIXTURE_MARKER, "marker")
        if set(marker) != {"format", "fixture_id"} or marker.get("format") != _FIXTURE_FORMAT:
            raise ValidationError("fixture marker is invalid")
        fixture_id = require_text(str(marker.get("fixture_id", "")), "fixture_id")
        if marker_bytes != _canonical(marker):
            raise ValidationError("fixture marker is not canonical")
        receipt, receipt_bytes = _mapping(
            _receipt_path(runtime, fixture_id), "receipt"
        )
        expected_receipt = {
            "fixture_id": fixture_id,
            "format": _RECEIPT_FORMAT,
            "host_family": family.value,
            "marker_sha256": hashlib.sha256(marker_bytes).hexdigest(),
            "root": str(root),
        }
        if receipt != expected_receipt or receipt_bytes != _canonical(expected_receipt):
            raise ValidationError("fixture receipt does not match marker and root")
        target = cls(
            fixture_id,
            root,
            installation.extensions_root,
            installation.skills_root,
            installation.extensions_root / "registry.json",
        )
        target.assert_managed_path(target.extensions_root)
        target.assert_managed_path(target.skills_root)
        target.assert_managed_path(target.registry_path)
        return target

    def assert_managed_path(self, path: str | Path) -> None:
        candidate = Path(path)
        _assert_no_managed_symlink(self.root, candidate)
        try:
            candidate.resolve(strict=False).relative_to(self.root.resolve(strict=False))
        except ValueError as exc:
            raise ValidationError("managed path must stay within fixture root") from exc
