from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

from projectos.adoption.bundle import ArtifactPolicy
from projectos.adoption.fixture import FixtureInstallationTarget
from projectos.adoption.profile import (
    MachineProfile,
    machine_profile_mapping,
)
from projectos.adoption.registry import ExtensionRegistry, plan_disabled_entry
from projectos.adoption.staging import (
    StagedExtension,
    copy_verified_version,
    load_staged_extension,
    stage_extension,
    verify_staged_extension,
)
from projectos.adoption.store import (
    AdoptionOperation,
    AdoptionSnapshot,
    LocalAdoptionStore,
    SnapshotEntry,
    TransactionJournal,
    TransactionState,
)
from projectos.database import utc_now
from projectos.errors import ValidationError


_T = TypeVar("_T")


def _boundary(name: str) -> None:
    """Named crash boundary used by deterministic recovery tests."""


def _atomic_replace(path: Path, content: bytes) -> None:
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
class TransactionResult:
    transaction_id: str
    operation: AdoptionOperation
    state: TransactionState
    bundle_sha256: str | None
    managed_paths: tuple[str, ...]


class AdoptionTransaction:
    def __init__(
        self,
        target: FixtureInstallationTarget,
        profile: MachineProfile,
        store: LocalAdoptionStore,
        policy: ArtifactPolicy,
        journal: TransactionJournal,
        bundle_path: Path | None,
    ):
        self.target = target
        self.profile = profile
        self.store = store
        self.policy = policy
        self.journal = journal
        self.bundle_path = bundle_path
        self._staged: StagedExtension | None = None
        self._snapshot: AdoptionSnapshot | None = None

    @classmethod
    def begin(
        cls,
        operation: AdoptionOperation,
        target: FixtureInstallationTarget,
        profile: MachineProfile,
        store: LocalAdoptionStore,
        policy: ArtifactPolicy,
        transaction_id: str,
        bundle_path: Path | None = None,
    ) -> "AdoptionTransaction":
        selected = AdoptionOperation(operation)
        if selected in {AdoptionOperation.ADOPT, AdoptionOperation.UPGRADE}:
            if bundle_path is None:
                raise ValidationError("adoption and upgrade require an extension bundle")
            try:
                bundle_sha256 = hashlib.sha256(Path(bundle_path).read_bytes()).hexdigest()
            except OSError as exc:
                raise ValidationError("extension bundle is unavailable") from exc
        else:
            if bundle_path is not None:
                raise ValidationError("operation does not accept an extension bundle")
            bundle_sha256 = None
        try:
            store.transaction_root(transaction_id).mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise ValidationError("transaction identifier already exists") from exc
        journal = store.create_journal(
            selected, target, bundle_sha256, transaction_id
        )
        store.save_journal(journal)
        return cls(
            target,
            profile,
            store,
            policy,
            journal,
            Path(bundle_path) if bundle_path is not None else None,
        )

    @classmethod
    def resume(
        cls,
        target: FixtureInstallationTarget,
        profile: MachineProfile,
        store: LocalAdoptionStore,
        policy: ArtifactPolicy,
        transaction_id: str,
    ) -> "AdoptionTransaction":
        journal = store.load_journal(transaction_id)
        if journal.fixture_id != target.fixture_id:
            raise ValidationError("transaction fixture does not match target")
        return cls(target, profile, store, policy, journal, None)

    def result(self) -> TransactionResult:
        return TransactionResult(
            self.journal.transaction_id,
            self.journal.operation,
            self.journal.state,
            self.journal.bundle_sha256,
            self.journal.managed_paths,
        )

    def _require(self, state: TransactionState) -> None:
        if self.journal.state is not state:
            raise ValidationError(
                f"transaction must be {state.value} before this operation"
            )

    def _advance(
        self,
        state: TransactionState,
        *,
        managed_paths: tuple[str, ...] | None = None,
    ) -> None:
        self.journal = self.journal.transition(
            state, managed_paths=managed_paths
        )
        self.store.save_journal(self.journal)

    def _fail(self, code: str) -> None:
        if self.journal.state in {
            TransactionState.FAILED,
            TransactionState.ROLLED_BACK,
            TransactionState.UNINSTALLED,
        }:
            return
        self.journal = self.journal.transition(
            TransactionState.FAILED, error_code=code
        )
        self.store.save_journal(self.journal)

    def _step(
        self,
        expected: TransactionState,
        failure_code: str,
        action: Callable[[], _T],
    ) -> _T:
        self._require(expected)
        try:
            return action()
        except Exception:
            self._fail(failure_code)
            raise

    def _assert_bindings(self) -> None:
        if machine_profile_mapping(self.store.profile) != machine_profile_mapping(
            self.profile
        ):
            raise ValidationError("transaction profile does not match local store")
        if Path(self.profile.contextos_root) != self.target.root:
            raise ValidationError("transaction profile does not match fixture target")
        if Path(self.profile.extensions_root) != self.target.extensions_root:
            raise ValidationError("transaction extensions root does not match fixture target")

    def _require_runtime_deactivated(self) -> None:
        entry = ExtensionRegistry.load(self.target.registry_path).projectos_entry()
        if entry is not None and entry.enabled:
            raise ValidationError("ProjectOS runtime deactivation is required")

    def preflight(self) -> TransactionResult:
        if self.journal.operation in {
            AdoptionOperation.UPGRADE,
            AdoptionOperation.UNINSTALL,
        }:
            self._require_runtime_deactivated()

        def action() -> TransactionResult:
            self._assert_bindings()
            registry = ExtensionRegistry.load(self.target.registry_path)
            existing = registry.projectos_entry()
            if self.journal.operation is AdoptionOperation.ADOPT and existing is not None:
                raise ValidationError("ProjectOS is already registered; use upgrade")
            if self.journal.operation is AdoptionOperation.UPGRADE and existing is None:
                raise ValidationError("upgrade requires an existing ProjectOS entry")
            if self.journal.operation in {
                AdoptionOperation.ADOPT,
                AdoptionOperation.UPGRADE,
            }:
                if self.bundle_path is None or self.journal.bundle_sha256 is None:
                    raise ValidationError("transaction extension bundle is unavailable")
                actual = hashlib.sha256(self.bundle_path.read_bytes()).hexdigest()
                if actual != self.journal.bundle_sha256:
                    raise ValidationError("transaction extension bundle hash changed")
            self.store.save_profile(self.profile)
            self._advance(TransactionState.PREFLIGHTED)
            _boundary("after_preflight")
            return self.result()

        return self._step(TransactionState.DISCOVERED, "preflight_failed", action)

    def snapshot(self) -> TransactionResult:
        def action() -> TransactionResult:
            self._snapshot = self.store.snapshot_target(
                self.target, self.journal.transaction_id
            )
            self._advance(TransactionState.SNAPSHOTTED)
            _boundary("after_snapshot")
            return self.result()

        return self._step(TransactionState.PREFLIGHTED, "snapshot_failed", action)

    def stage(self) -> TransactionResult:
        def action() -> TransactionResult:
            if self.bundle_path is None:
                raise ValidationError("transaction extension bundle is unavailable")
            self._staged = stage_extension(
                self.bundle_path,
                self.profile,
                self.store,
                self.journal.transaction_id,
                self.policy,
            )
            managed_path = (
                self.target.extensions_root
                / self._staged.relative_version_path
            ).relative_to(self.target.root).as_posix()
            self._advance(TransactionState.STAGED, managed_paths=(managed_path,))
            _boundary("after_stage")
            return self.result()

        return self._step(TransactionState.SNAPSHOTTED, "stage_failed", action)

    def verify(self) -> TransactionResult:
        def action() -> TransactionResult:
            staged = self._load_staged()
            self._staged = verify_staged_extension(
                staged, self.profile, self.policy
            )
            self._advance(TransactionState.VERIFIED)
            _boundary("after_verify")
            return self.result()

        return self._step(TransactionState.STAGED, "verify_failed", action)

    def adopt_disabled(self) -> TransactionResult:
        def action() -> TransactionResult:
            staged = self._load_staged()
            copy_verified_version(staged, self.target)
            _boundary("after_version_copy")
            registry = ExtensionRegistry.load(self.target.registry_path)
            entry = plan_disabled_entry(
                staged.manifest,
                staged.bundle_sha256,
                staged.relative_manifest_path,
                utc_now(),
            )
            replacement = registry.with_projectos(entry).canonical_bytes()
            _boundary("before_registry_replace")
            _atomic_replace(self.target.registry_path, replacement)
            _boundary("after_registry_replace")
            self._advance(TransactionState.ADOPTED)
            return self.result()

        return self._step(TransactionState.VERIFIED, "adopt_failed", action)

    def rollback(self) -> TransactionResult:
        self._require_runtime_deactivated()

        def action() -> TransactionResult:
            snapshot = self._load_snapshot()
            staged = self._load_staged()
            self._assert_owned_version(staged)
            self._restore_registry(snapshot)
            self._remove_staged_version(staged)
            self._advance(TransactionState.ROLLED_BACK)
            return self.result()

        return self._step(TransactionState.ADOPTED, "rollback_failed", action)

    def uninstall(self) -> TransactionResult:
        self._require_runtime_deactivated()

        def action() -> TransactionResult:
            snapshot = self._load_snapshot()
            versions = self._snapshot_versions(snapshot)
            for relative, entries in versions.items():
                self.store.archive_managed_version(
                    self.target,
                    relative,
                    entries,
                    self.journal.transaction_id,
                )
            _boundary("after_uninstall_archive")
            registry = ExtensionRegistry.load(self.target.registry_path)
            _atomic_replace(
                self.target.registry_path,
                registry.without_projectos().canonical_bytes(),
            )
            _boundary("after_uninstall_registry_replace")
            for relative, entries in versions.items():
                if self.store.inventory_managed_path(self.target, relative) != entries:
                    raise ValidationError("managed version inventory does not match")
                shutil.rmtree(self.target.extensions_root / relative)
                _boundary("after_uninstall_version_remove")
            self._remove_empty_version_parents()
            self._advance(TransactionState.UNINSTALLED)
            return self.result()

        return self._step(TransactionState.SNAPSHOTTED, "uninstall_failed", action)

    def recover(self) -> TransactionResult:
        if self.journal.state is TransactionState.ROLLED_BACK:
            return self.result()
        self._require(TransactionState.FAILED)
        snapshot_path = (
            self.store.transaction_root(self.journal.transaction_id)
            / "snapshot"
            / "snapshot.json"
        )
        staged: StagedExtension | None = None
        if self.journal.managed_paths:
            staged = self._load_staged()
            destination = self.target.extensions_root / staged.relative_version_path
            if destination.exists():
                self._assert_owned_version(staged)
        snapshot = self.store.load_snapshot(self.journal.transaction_id) if snapshot_path.exists() else None
        if (
            snapshot is not None
            and self.journal.operation is AdoptionOperation.UNINSTALL
        ):
            self._restore_uninstall_versions(snapshot)
            self._restore_registry(snapshot)
            self._advance(TransactionState.ROLLED_BACK)
            return self.result()
        if snapshot is not None:
            self._restore_registry(snapshot)
        if staged is not None:
            self._remove_staged_version(staged)
        self._advance(TransactionState.ROLLED_BACK)
        return self.result()

    def _load_snapshot(self) -> AdoptionSnapshot:
        if self._snapshot is None:
            self._snapshot = self.store.load_snapshot(self.journal.transaction_id)
        return self._snapshot

    def _load_staged(self) -> StagedExtension:
        if self._staged is not None:
            return self._staged
        if self.journal.bundle_sha256 is None or len(self.journal.managed_paths) != 1:
            raise ValidationError("transaction staged extension is unavailable")
        target_prefix = self.target.extensions_root.relative_to(self.target.root).as_posix()
        managed = self.journal.managed_paths[0]
        prefix = f"{target_prefix}/"
        if not managed.startswith(prefix):
            raise ValidationError("transaction managed path is invalid")
        self._staged = load_staged_extension(
            self.store,
            self.profile,
            self.journal.transaction_id,
            managed[len(prefix) :],
            self.journal.bundle_sha256,
            self.policy,
        )
        return self._staged

    def _expected_target_inventory(
        self, staged: StagedExtension
    ) -> tuple[SnapshotEntry, ...]:
        root = self.target.extensions_root / staged.relative_version_path
        return tuple(
            SnapshotEntry(
                (root / entry.path).relative_to(self.target.root).as_posix(),
                entry.sha256,
                entry.size,
            )
            for entry in staged.inventory
        )

    def _assert_owned_version(self, staged: StagedExtension) -> None:
        current = self.store.inventory_managed_path(
            self.target, staged.relative_version_path
        )
        if current != self._expected_target_inventory(staged):
            raise ValidationError("transaction-owned version inventory does not match")

    def _restore_registry(self, snapshot: AdoptionSnapshot) -> None:
        if snapshot.registry_existed:
            _atomic_replace(
                self.target.registry_path, snapshot.registry_bytes_path.read_bytes()
            )
        else:
            self.target.registry_path.unlink(missing_ok=True)

    def _remove_staged_version(self, staged: StagedExtension) -> None:
        destination = self.target.extensions_root / staged.relative_version_path
        if destination.exists():
            shutil.rmtree(destination)
        self._remove_empty_version_parents()

    def _remove_empty_version_parents(self) -> None:
        for path in (
            self.target.extensions_root / "projectos/versions",
            self.target.extensions_root / "projectos",
        ):
            try:
                path.rmdir()
            except (FileNotFoundError, OSError):
                pass

    def _restore_uninstall_versions(self, snapshot: AdoptionSnapshot) -> None:
        for relative, entries in self._snapshot_versions(snapshot).items():
            destination = self.target.extensions_root / relative
            if destination.exists():
                if self.store.inventory_managed_path(self.target, relative) != entries:
                    raise ValidationError("managed version inventory does not match")
                continue
            version = relative.rsplit("/", 1)[-1]
            archive = (
                self.store.root
                / "archives"
                / self.journal.transaction_id
                / version
            )
            expected = {
                (self.target.root / entry.path)
                .relative_to(destination)
                .as_posix(): (entry.sha256, entry.size)
                for entry in entries
            }
            actual = self._directory_hashes(archive)
            if actual != expected:
                raise ValidationError("managed version archive inventory does not match")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(
                tempfile.mkdtemp(
                    prefix=f".{version}.", suffix=".restore.tmp", dir=destination.parent
                )
            )
            try:
                for relative_file in sorted(expected):
                    source = archive / relative_file
                    target_file = temporary / relative_file
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target_file)
                if self._directory_hashes(temporary) != expected:
                    raise ValidationError("managed version restore verification failed")
                os.replace(temporary, destination)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            if self.store.inventory_managed_path(self.target, relative) != entries:
                raise ValidationError("restored managed version inventory does not match")

    @staticmethod
    def _directory_hashes(root: Path) -> dict[str, tuple[str, int]]:
        if not root.is_dir() or root.is_symlink():
            raise ValidationError("managed version archive is unavailable")
        hashes: dict[str, tuple[str, int]] = {}
        for directory, directories, files in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            if any((directory_path / name).is_symlink() for name in directories):
                raise ValidationError("managed version archive cannot contain symlinks")
            for name in files:
                path = directory_path / name
                if path.is_symlink():
                    raise ValidationError("managed version archive cannot contain symlinks")
                content = path.read_bytes()
                hashes[path.relative_to(root).as_posix()] = (
                    hashlib.sha256(content).hexdigest(),
                    len(content),
                )
        return hashes

    def _snapshot_versions(
        self, snapshot: AdoptionSnapshot
    ) -> dict[str, tuple[SnapshotEntry, ...]]:
        extension_prefix = self.target.extensions_root.relative_to(self.target.root).as_posix()
        prefix = f"{extension_prefix}/projectos/versions/"
        grouped: dict[str, list[SnapshotEntry]] = {}
        for entry in snapshot.entries:
            if not entry.path.startswith(prefix):
                continue
            remainder = entry.path[len(prefix) :]
            version, separator, _ = remainder.partition("/")
            if not version or not separator:
                raise ValidationError("snapshot managed version path is invalid")
            grouped.setdefault(f"projectos/versions/{version}", []).append(entry)
        return {
            path: tuple(sorted(entries, key=lambda entry: entry.path))
            for path, entries in grouped.items()
        }
