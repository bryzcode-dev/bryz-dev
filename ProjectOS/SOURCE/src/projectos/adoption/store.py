from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

from projectos.adoption.fixture import (
    FixtureInstallationTarget,
    assert_fixture_separation,
)
from projectos.adoption.profile import (
    MachineProfile,
    machine_profile_from_mapping,
    machine_profile_mapping,
)
from projectos.database import utc_now
from projectos.errors import ValidationError
from projectos.validation import reject_secret_material


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AdoptionOperation(str, Enum):
    ADOPT = "ADOPT"
    UPGRADE = "UPGRADE"
    ROLLBACK = "ROLLBACK"
    UNINSTALL = "UNINSTALL"


class TransactionState(str, Enum):
    DISCOVERED = "DISCOVERED"
    PREFLIGHTED = "PREFLIGHTED"
    SNAPSHOTTED = "SNAPSHOTTED"
    STAGED = "STAGED"
    VERIFIED = "VERIFIED"
    ADOPTED = "ADOPTED"
    ROLLED_BACK = "ROLLED_BACK"
    UNINSTALLED = "UNINSTALLED"
    FAILED = "FAILED"


_TRANSITIONS = {
    TransactionState.DISCOVERED: {TransactionState.PREFLIGHTED, TransactionState.FAILED},
    TransactionState.PREFLIGHTED: {TransactionState.SNAPSHOTTED, TransactionState.FAILED},
    TransactionState.SNAPSHOTTED: {
        TransactionState.STAGED,
        TransactionState.ROLLED_BACK,
        TransactionState.UNINSTALLED,
        TransactionState.FAILED,
    },
    TransactionState.STAGED: {TransactionState.VERIFIED, TransactionState.FAILED},
    TransactionState.VERIFIED: {TransactionState.ADOPTED, TransactionState.FAILED},
    TransactionState.ADOPTED: {
        TransactionState.ROLLED_BACK,
        TransactionState.UNINSTALLED,
        TransactionState.FAILED,
    },
    TransactionState.FAILED: {TransactionState.ROLLED_BACK},
    TransactionState.ROLLED_BACK: set(),
    TransactionState.UNINSTALLED: set(),
}


def _canonical(value: object) -> bytes:
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


def _safe_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValidationError(f"{field} is invalid")
    return value


def _portable_relative(value: str, field: str) -> str:
    if not isinstance(value, str) or "\\" in value:
        raise ValidationError(f"{field} must be portable and relative")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationError(f"{field} must be portable and relative")
    return path.as_posix()


@dataclass(frozen=True)
class SnapshotEntry:
    path: str
    sha256: str
    size: int

    def to_mapping(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class AdoptionSnapshot:
    transaction_id: str
    registry_existed: bool
    registry_sha256: str | None
    entries: tuple[SnapshotEntry, ...]
    root: Path

    @property
    def registry_bytes_path(self) -> Path:
        return self.root / "registry.bin"

    @property
    def manifest_path(self) -> Path:
        return self.root / "snapshot.json"


@dataclass(frozen=True)
class TransactionJournal:
    transaction_id: str
    operation: AdoptionOperation
    state: TransactionState
    fixture_id: str
    bundle_sha256: str | None
    managed_paths: tuple[str, ...]
    error_codes: tuple[str, ...]
    created_at: str
    updated_at: str

    def transition(
        self,
        state: TransactionState,
        *,
        error_code: str | None = None,
        managed_paths: Sequence[str] | None = None,
    ) -> "TransactionJournal":
        selected = TransactionState(state)
        if selected not in _TRANSITIONS[self.state]:
            raise ValidationError("transaction state transition is invalid")
        paths = (
            self.managed_paths
            if managed_paths is None
            else tuple(_portable_relative(item, "managed path") for item in managed_paths)
        )
        errors = self.error_codes
        if error_code is not None:
            errors = (*errors, _safe_id(error_code, "error code"))
        return replace(
            self,
            state=selected,
            managed_paths=paths,
            error_codes=errors,
            updated_at=utc_now(),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "format": "projectos-adoption-journal-v1",
            "transaction_id": self.transaction_id,
            "operation": self.operation.value,
            "state": self.state.value,
            "fixture_id": self.fixture_id,
            "bundle_sha256": self.bundle_sha256,
            "managed_paths": list(self.managed_paths),
            "error_codes": list(self.error_codes),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _inspect_content(content: bytes) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = text
    reject_secret_material(value)


class LocalAdoptionStore:
    def __init__(self, profile: MachineProfile):
        self.profile = profile
        self.root = Path(str(profile.runtime_root)) / "adoption"

    @classmethod
    def open(cls, profile: MachineProfile) -> "LocalAdoptionStore":
        assert_fixture_separation(
            profile.host_family, profile.contextos_root, profile.runtime_root
        )
        runtime = Path(str(profile.runtime_root))
        adoption_root = runtime / "adoption"
        if runtime.is_symlink() or adoption_root.is_symlink():
            raise ValidationError("local adoption store cannot use a symlink")
        return cls(profile)

    def transaction_root(self, transaction_id: str) -> Path:
        return self.root / "transactions" / _safe_id(transaction_id, "transaction_id")

    def save_profile(self, profile: MachineProfile) -> Path:
        if profile.installation_id != self.profile.installation_id:
            raise ValidationError("machine profile installation does not match store")
        path = self.root / "machine-profile.json"
        _atomic_write(path, _canonical(machine_profile_mapping(profile)))
        return path

    def load_profile(self, path: str | Path) -> MachineProfile:
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("machine profile is unavailable or invalid") from exc
        if not isinstance(value, dict):
            raise ValidationError("machine profile is unavailable or invalid")
        profile = machine_profile_from_mapping(value)
        if profile.installation_id != self.profile.installation_id:
            raise ValidationError("machine profile installation does not match store")
        return profile

    def create_journal(
        self,
        operation: AdoptionOperation,
        target: FixtureInstallationTarget,
        bundle_sha256: str | None,
        transaction_id: str,
    ) -> TransactionJournal:
        identifier = _safe_id(transaction_id, "transaction_id")
        if bundle_sha256 is not None and not _SHA256.fullmatch(bundle_sha256):
            raise ValidationError("bundle_sha256 is invalid")
        timestamp = utc_now()
        return TransactionJournal(
            identifier,
            AdoptionOperation(operation),
            TransactionState.DISCOVERED,
            _safe_id(target.fixture_id, "fixture_id"),
            bundle_sha256,
            (),
            (),
            timestamp,
            timestamp,
        )

    def save_journal(self, journal: TransactionJournal) -> None:
        _atomic_write(
            self.transaction_root(journal.transaction_id) / "journal.json",
            _canonical(journal.to_mapping()),
        )

    def load_journal(self, transaction_id: str) -> TransactionJournal:
        identifier = _safe_id(transaction_id, "transaction_id")
        path = self.transaction_root(identifier) / "journal.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("transaction journal is unavailable or invalid") from exc
        expected = {
            "format",
            "transaction_id",
            "operation",
            "state",
            "fixture_id",
            "bundle_sha256",
            "managed_paths",
            "error_codes",
            "created_at",
            "updated_at",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValidationError("transaction journal fields are invalid")
        try:
            if value["format"] != "projectos-adoption-journal-v1":
                raise ValidationError("transaction journal format is incompatible")
            if value["transaction_id"] != identifier:
                raise ValidationError("transaction journal identifier does not match")
            bundle_sha256 = value["bundle_sha256"]
            if bundle_sha256 is not None and (
                not isinstance(bundle_sha256, str)
                or not _SHA256.fullmatch(bundle_sha256)
            ):
                raise ValidationError("transaction journal bundle hash is invalid")
            if not isinstance(value["managed_paths"], list) or not isinstance(
                value["error_codes"], list
            ):
                raise ValidationError("transaction journal list fields are invalid")
            if not isinstance(value["created_at"], str) or not isinstance(
                value["updated_at"], str
            ):
                raise ValidationError("transaction journal timestamps are invalid")
            return TransactionJournal(
                identifier,
                AdoptionOperation(value["operation"]),
                TransactionState(value["state"]),
                _safe_id(value["fixture_id"], "fixture_id"),
                bundle_sha256,
                tuple(
                    _portable_relative(item, "managed path")
                    for item in value["managed_paths"]
                ),
                tuple(_safe_id(item, "error code") for item in value["error_codes"]),
                value["created_at"],
                value["updated_at"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError("transaction journal is unavailable or invalid") from exc

    def inventory_managed_path(
        self, target: FixtureInstallationTarget, relative_path: str
    ) -> tuple[SnapshotEntry, ...]:
        relative = _portable_relative(relative_path, "managed path")
        source = target.extensions_root / relative
        target.assert_managed_path(source)
        if not source.exists():
            return ()
        if not source.is_dir() or source.is_symlink():
            raise ValidationError("managed path must be a non-symlink directory")
        entries: list[SnapshotEntry] = []
        for directory, directories, files in os.walk(source, followlinks=False):
            directory_path = Path(directory)
            for name in directories:
                if (directory_path / name).is_symlink():
                    raise ValidationError("managed definitions cannot contain symlinks")
            for name in files:
                path = directory_path / name
                if path.is_symlink():
                    raise ValidationError("managed definitions cannot contain symlinks")
                content = path.read_bytes()
                _inspect_content(content)
                entries.append(
                    SnapshotEntry(
                        path.relative_to(target.root).as_posix(),
                        hashlib.sha256(content).hexdigest(),
                        len(content),
                    )
                )
        return tuple(sorted(entries, key=lambda item: item.path))

    def snapshot_target(
        self, target: FixtureInstallationTarget, transaction_id: str
    ) -> AdoptionSnapshot:
        identifier = _safe_id(transaction_id, "transaction_id")
        snapshot_root = self.transaction_root(identifier) / "snapshot"
        target.assert_managed_path(target.registry_path)
        registry_existed = target.registry_path.is_file()
        registry_bytes = target.registry_path.read_bytes() if registry_existed else b""
        _inspect_content(registry_bytes)
        entries = self.inventory_managed_path(target, "projectos")
        if snapshot_root.exists():
            raise ValidationError("transaction snapshot already exists")
        snapshot_root.mkdir(parents=True)
        _atomic_write(snapshot_root / "registry.bin", registry_bytes)
        for entry in entries:
            source = target.root / entry.path
            destination = snapshot_root / "files" / entry.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(destination, source.read_bytes())
        registry_hash = (
            hashlib.sha256(registry_bytes).hexdigest() if registry_existed else None
        )
        mapping = {
            "format": "projectos-adoption-snapshot-v1",
            "transaction_id": identifier,
            "registry_existed": registry_existed,
            "registry_sha256": registry_hash,
            "entries": [entry.to_mapping() for entry in entries],
        }
        _atomic_write(snapshot_root / "snapshot.json", _canonical(mapping))
        return AdoptionSnapshot(
            identifier,
            registry_existed,
            registry_hash,
            entries,
            snapshot_root,
        )

    def load_snapshot(self, transaction_id: str) -> AdoptionSnapshot:
        identifier = _safe_id(transaction_id, "transaction_id")
        snapshot_root = self.transaction_root(identifier) / "snapshot"
        manifest_path = snapshot_root / "snapshot.json"
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            registry_bytes = (snapshot_root / "registry.bin").read_bytes()
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("transaction snapshot is unavailable or invalid") from exc
        expected = {
            "format",
            "transaction_id",
            "registry_existed",
            "registry_sha256",
            "entries",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValidationError("transaction snapshot fields are invalid")
        if (
            value["format"] != "projectos-adoption-snapshot-v1"
            or value["transaction_id"] != identifier
            or type(value["registry_existed"]) is not bool
            or not isinstance(value["entries"], list)
        ):
            raise ValidationError("transaction snapshot is unavailable or invalid")
        registry_hash = value["registry_sha256"]
        actual_registry_hash = hashlib.sha256(registry_bytes).hexdigest()
        if value["registry_existed"]:
            if not isinstance(registry_hash, str) or registry_hash != actual_registry_hash:
                raise ValidationError("transaction snapshot registry hash does not match")
        elif registry_hash is not None or registry_bytes:
            raise ValidationError("transaction snapshot registry state does not match")
        entries: list[SnapshotEntry] = []
        for item in value["entries"]:
            if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
                raise ValidationError("transaction snapshot entry is invalid")
            path = _portable_relative(item["path"], "snapshot path")
            sha256 = item["sha256"]
            size = item["size"]
            if (
                not isinstance(sha256, str)
                or not _SHA256.fullmatch(sha256)
                or type(size) is not int
                or size < 0
            ):
                raise ValidationError("transaction snapshot entry is invalid")
            copied = snapshot_root / "files" / path
            try:
                content = copied.read_bytes()
            except OSError as exc:
                raise ValidationError("transaction snapshot file is unavailable") from exc
            if len(content) != size or hashlib.sha256(content).hexdigest() != sha256:
                raise ValidationError("transaction snapshot file hash does not match")
            entries.append(SnapshotEntry(path, sha256, size))
        return AdoptionSnapshot(
            identifier,
            value["registry_existed"],
            registry_hash,
            tuple(sorted(entries, key=lambda entry: entry.path)),
            snapshot_root,
        )

    def archive_managed_version(
        self,
        target: FixtureInstallationTarget,
        relative_version_path: str,
        expected_inventory: Iterable[SnapshotEntry],
        transaction_id: str,
    ) -> Path:
        relative = _portable_relative(relative_version_path, "managed version path")
        parts = PurePosixPath(relative).parts
        if len(parts) != 3 or parts[:2] != ("projectos", "versions"):
            raise ValidationError("managed version path is invalid")
        current = self.inventory_managed_path(target, relative)
        expected = tuple(expected_inventory)
        if current != expected:
            raise ValidationError("managed version inventory does not match")
        source = target.extensions_root / relative
        destination = (
            self.root
            / "archives"
            / _safe_id(transaction_id, "transaction_id")
            / parts[-1]
        )
        if destination.exists():
            raise ValidationError("managed version archive already exists")
        destination.mkdir(parents=True)
        for entry in current:
            source_file = target.root / entry.path
            relative_file = source_file.relative_to(source)
            destination_file = destination / relative_file
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, destination_file)
        archived = {
            file.relative_to(destination).as_posix(): hashlib.sha256(
                file.read_bytes()
            ).hexdigest()
            for file in destination.rglob("*")
            if file.is_file()
        }
        expected_archived = {
            (target.root / entry.path).relative_to(source).as_posix(): entry.sha256
            for entry in current
        }
        if archived != expected_archived:
            raise ValidationError("managed version archive verification failed")
        return destination
