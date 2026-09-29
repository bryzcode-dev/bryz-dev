from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from projectos.adoption.activation_store import (
    ActivationJournal,
    ActivationProofResult,
    ActivationState,
    LocalActivationStore,
)
from projectos.adoption.bundle import ArtifactPolicy
from projectos.adoption.discovery import DiscoveredSkill, SkillDiscoveryService, load_installed_extension
from projectos.adoption.fixture import FixtureInstallationTarget
from projectos.adoption.profile import MachineProfile, machine_profile_mapping
from projectos.adoption.registry import ExtensionRegistry
from projectos.adoption.scheduler import SchedulerAction, SchedulerDefinition, SchedulerState, adapter_for
from projectos.adoption.store import LocalAdoptionStore, TransactionState
from projectos.bindings import GoogleBindingRepository
from projectos.database import ProjectOSDatabase
from projectos.errors import MigrationError, ValidationError
from projectos.google.config import ProjectOSGoogleConfig
from projectos.health import ProjectOSDoctor
from projectos.runtime import RuntimeSyncCoordinator, RuntimeTrigger, runtime_sync_argv


def noop(name: str) -> None:
    """Default activation boundary hook."""


@runtime_checkable
class ActivationProof(Protocol):
    def run(
        self,
        discovered: DiscoveredSkill,
        coordinator: RuntimeSyncCoordinator,
    ) -> ActivationProofResult: ...


@dataclass(frozen=True)
class ActivationResult:
    activation_id: str
    definition_transaction_id: str
    state: ActivationState
    error_codes: tuple[str, ...]


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


class RuntimeActivation:
    def __init__(
        self,
        target: FixtureInstallationTarget,
        profile_path: Path,
        store: LocalAdoptionStore,
        runner,
        policy: ArtifactPolicy,
        proof: ActivationProof,
        *,
        boundary_hook=noop,
    ):
        self.target = target
        self.profile_path = Path(profile_path)
        self.store = store
        self.runner = runner
        self.policy = policy
        self.proof = proof
        self.boundary_hook = boundary_hook
        self.activation_store = LocalActivationStore.open(store)
        self.journal: ActivationJournal | None = None
        self.profile: MachineProfile | None = None

    def result(self) -> ActivationResult:
        if self.journal is None:
            raise ValidationError("activation journal is unavailable")
        return ActivationResult(
            self.journal.activation_id,
            self.journal.definition_transaction_id,
            self.journal.state,
            self.journal.error_codes,
        )

    def _definition_journal(
        self, definition_transaction_id: str, *, require_disabled: bool = True
    ):
        try:
            journal = self.store.load_journal(definition_transaction_id)
        except ValidationError as exc:
            raise ValidationError("definition transaction is unavailable") from exc
        if journal.state is not TransactionState.ADOPTED:
            raise ValidationError("definition transaction is not completed")
        if journal.fixture_id != self.target.fixture_id or journal.bundle_sha256 is None:
            raise ValidationError("definition transaction does not match fixture")
        registry = ExtensionRegistry.load(self.target.registry_path)
        entry = registry.projectos_entry()
        if (
            entry is None
            or entry.bundle_sha256 != journal.bundle_sha256
            or len(journal.managed_paths) != 1
            or not journal.managed_paths[0].endswith(entry.manifest.removesuffix("/manifest.json"))
            or require_disabled
            and entry.enabled
        ):
            raise ValidationError("definition transaction does not match disabled installation")
        return journal

    def begin(
        self,
        definition_transaction_id: str,
        activation_id: str | None = None,
    ) -> ActivationResult:
        definition = self._definition_journal(str(definition_transaction_id))
        self.journal = self.activation_store.create(
            self.target,
            self.store.profile,
            definition.transaction_id,
            definition.bundle_sha256,
            activation_id,
        )
        return self._execute_with_rollback()

    def resume(self, activation_id: str) -> ActivationResult:
        self.journal = self.activation_store.load_journal(activation_id)
        self._assert_journal_bindings()
        if self.journal.state is ActivationState.FAILED:
            return self.recover(activation_id)
        return self._execute_with_rollback()

    def _execute_with_rollback(self) -> ActivationResult:
        try:
            return self._continue()
        except Exception as exc:
            if self.journal is not None and self.journal.state not in {
                ActivationState.PROVED,
                ActivationState.ROLLED_BACK,
                ActivationState.DEACTIVATED,
            }:
                code = type(exc).__name__.casefold()[:64] or "activation_failed"
                self.journal = self.journal.transition(
                    ActivationState.FAILED, error_code=code
                )
                self.activation_store.save_journal(self.journal)
                self.recover(self.journal.activation_id)
            raise

    def _continue(self) -> ActivationResult:
        if self.journal is None:
            raise ValidationError("activation journal is unavailable")
        while True:
            state = self.journal.state
            if state is ActivationState.DISCOVERED:
                self._preflight()
            elif state is ActivationState.PREFLIGHTED:
                self._stage_scheduler()
            elif state is ActivationState.SCHEDULER_STAGED:
                self._verify_runtime()
            elif state is ActivationState.RUNTIME_VERIFIED:
                self._enable_scheduler()
            elif state is ActivationState.SCHEDULER_ENABLED:
                self._enable_skill()
            elif state is ActivationState.SKILL_ENABLED:
                self._prove()
            elif state in {
                ActivationState.PROVED,
                ActivationState.ROLLED_BACK,
                ActivationState.DEACTIVATED,
            }:
                return self.result()
            else:
                raise ValidationError("activation cannot continue from current state")

    def _load_profile(self) -> MachineProfile:
        profile = self.store.load_profile(self.profile_path)
        if machine_profile_mapping(profile) != machine_profile_mapping(self.store.profile):
            raise ValidationError("activation profile does not match local store")
        if (
            Path(str(profile.contextos_root)).resolve(strict=False)
            != self.target.root.resolve(strict=False)
        ):
            raise ValidationError("activation profile does not match fixture")
        self.profile = profile
        return profile

    def _advance(self, state: ActivationState, **changes) -> None:
        if self.journal is None:
            raise ValidationError("activation journal is unavailable")
        self.journal = self.journal.transition(state, **changes)
        self.activation_store.save_journal(self.journal)

    def _preflight(self) -> None:
        if self.journal is None:
            raise ValidationError("activation journal is unavailable")
        definition = self._definition_journal(self.journal.definition_transaction_id)
        profile = self._load_profile()
        installed = load_installed_extension(self.target, profile, self.policy)
        if installed.bundle_sha256 != definition.bundle_sha256:
            raise ValidationError("installed extension does not match definition transaction")
        disabled_bytes = self.target.registry_path.read_bytes()
        disabled_hash = self.activation_store.save_disabled_registry(
            self.journal.activation_id, disabled_bytes
        )
        self._validate_runtime(profile)
        self._advance(
            ActivationState.PREFLIGHTED,
            disabled_registry_sha256=disabled_hash,
        )
        self.boundary_hook("after_preflight")

    def _stage_scheduler(self) -> None:
        profile = self.profile or self._load_profile()
        adapter = adapter_for(profile)
        definition = adapter.render(profile, self.profile_path)
        adapter.verify(definition, profile, self.profile_path)
        self.activation_store.save_definition(self.journal.activation_id, definition)
        adapter.install(definition, self.runner)
        self._advance(
            ActivationState.SCHEDULER_STAGED,
            definition_sha256=definition.sha256,
        )
        self.boundary_hook("after_scheduler_stage")

    def _validate_runtime(self, profile: MachineProfile) -> None:
        runtime_sync_argv(profile, self.profile_path, RuntimeTrigger.SCHEDULER)
        runtime_sync_argv(profile, self.profile_path, RuntimeTrigger.SKILL)
        config = ProjectOSGoogleConfig.load(
            Path(str(profile.config_path)), family=profile.host_family
        )
        if (
            config.machine_id != profile.machine_id
            or not config.google_enabled
            or not config.google_write_enabled
        ):
            raise ValidationError("activation Google configuration is not write ready")
        database: ProjectOSDatabase | None = None
        try:
            database = ProjectOSDatabase.open_existing(
                Path(str(profile.database_path)), read_only=True
            )
            if not ProjectOSDoctor(database).check().healthy:
                raise ValidationError("activation database is unhealthy")
            binding = GoogleBindingRepository(database).get(config.binding_id)
            owners = database.connection.execute(
                "SELECT email FROM users WHERE protected_owner=1 AND active=1"
            ).fetchall()
            if binding is None or (
                binding.environment != config.environment
                or binding.spreadsheet_id != config.spreadsheet_id
                or binding.contract_version != config.contract_version
                or binding.credential_id != config.credential_reference_id
                or not binding.enabled
                or not binding.write_enabled
                or len(owners) != 1
                or owners[0]["email"] != config.expected_owner_email
            ):
                raise ValidationError("activation database binding does not match configuration")
        except (MigrationError, sqlite3.DatabaseError, OSError) as exc:
            raise ValidationError("activation database is unavailable") from exc
        finally:
            if database is not None:
                database.close()

    def _verify_runtime(self) -> None:
        profile = self.profile or self._load_profile()
        self._validate_runtime(profile)
        self._advance(ActivationState.RUNTIME_VERIFIED)
        self.boundary_hook("after_runtime_verify")

    def _definition(self) -> SchedulerDefinition:
        if self.journal is None:
            raise ValidationError("activation journal is unavailable")
        profile = self.profile or self._load_profile()
        definition = adapter_for(profile).render(profile, self.profile_path)
        content = self.activation_store.load_definition_bytes(self.journal)
        if content != definition.content:
            raise ValidationError("activation scheduler definition has changed")
        return definition

    def _enable_scheduler(self) -> None:
        definition = self._definition()
        adapter = adapter_for(self.profile)
        inspection = adapter.enable(definition, self.runner)
        if inspection.state is not SchedulerState.ENABLED:
            raise ValidationError("activation scheduler did not enable")
        self._advance(ActivationState.SCHEDULER_ENABLED)
        self.boundary_hook("after_scheduler_enable")

    def _enabled_registry_bytes(self, disabled_bytes: bytes) -> bytes:
        try:
            value = json.loads(disabled_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("disabled registry snapshot is invalid") from exc
        registry = ExtensionRegistry.from_mapping(value)
        entry = registry.projectos_entry()
        if entry is None or entry.enabled:
            raise ValidationError("disabled registry snapshot is invalid")
        return registry.with_projectos(entry.with_enabled(True)).canonical_bytes()

    def _enable_skill(self) -> None:
        if self.journal is None:
            raise ValidationError("activation journal is unavailable")
        disabled = self.activation_store.load_disabled_registry(self.journal)
        enabled = self._enabled_registry_bytes(disabled)
        current = self.target.registry_path.read_bytes()
        if current not in {disabled, enabled}:
            raise ValidationError("activation registry ownership changed")
        self.boundary_hook("before_registry_replace")
        if current == disabled:
            _atomic_replace(self.target.registry_path, enabled)
        self.boundary_hook("after_registry_replace")
        self._advance(ActivationState.SKILL_ENABLED)
        self.boundary_hook("after_skill_enable")

    def _prove(self) -> None:
        if self.journal is None:
            raise ValidationError("activation journal is unavailable")
        discovery = SkillDiscoveryService().resolve(
            self.target,
            self.profile_path,
            self.store,
            self.runner,
            self.policy,
        )
        if not discovery.ok or discovery.skill is None:
            raise ValidationError("activation skill discovery proof failed")
        proof = self.proof.run(discovery.skill, RuntimeSyncCoordinator())
        if (
            not proof.success
            or proof.triggers != ("scheduler", "skill")
            or len(proof.statuses) != 2
        ):
            raise ValidationError("activation runtime proof failed")
        self.activation_store.save_proof(self.journal.activation_id, proof)
        self._advance(ActivationState.PROVED)
        self.boundary_hook("after_proof")

    def _assert_journal_bindings(self) -> None:
        if self.journal is None:
            raise ValidationError("activation journal is unavailable")
        profile = self._load_profile()
        if (
            self.journal.fixture_id != self.target.fixture_id
            or self.journal.installation_id != profile.installation_id
            or self.journal.scheduler_kind != profile.scheduler_kind.value
            or self.journal.task_id != profile.scheduler_task_id
        ):
            raise ValidationError("activation journal does not match fixture")
        self._definition_journal(
            self.journal.definition_transaction_id, require_disabled=False
        )

    def recover(self, activation_id: str) -> ActivationResult:
        self.journal = self.activation_store.load_journal(activation_id)
        profile = self._load_profile()
        if self.journal.state in {
            ActivationState.PROVED,
            ActivationState.ROLLED_BACK,
            ActivationState.DEACTIVATED,
        }:
            return self.result()
        if (
            self.journal.fixture_id != self.target.fixture_id
            or self.journal.installation_id != profile.installation_id
        ):
            raise ValidationError("activation journal does not match fixture")
        self._definition_journal(
            self.journal.definition_transaction_id, require_disabled=False
        )
        disabled_path = (
            self.activation_store.activation_root(activation_id)
            / "disabled-registry.bin"
        )
        if disabled_path.exists():
            disabled = self.activation_store.load_disabled_registry(self.journal)
            enabled = self._enabled_registry_bytes(disabled)
            current = self.target.registry_path.read_bytes()
            if current not in {disabled, enabled}:
                raise ValidationError("activation registry ownership changed")
            if current != disabled:
                _atomic_replace(self.target.registry_path, disabled)
        definition_path = (
            self.activation_store.activation_root(activation_id)
            / "scheduler-definition.bin"
        )
        if definition_path.exists():
            definition = self._definition()
            adapter = adapter_for(profile)
            inspection = adapter.inspect(definition, self.runner)
            if inspection.state is SchedulerState.ENABLED:
                adapter.disable(definition, self.runner)
                inspection = adapter.inspect(definition, self.runner)
            if inspection.state is SchedulerState.INSTALLED_DISABLED:
                adapter.remove(definition, self.runner)
        self.journal = self.journal.transition(ActivationState.ROLLED_BACK)
        self.activation_store.save_journal(self.journal)
        return self.result()

    def deactivate(self, activation_id: str) -> ActivationResult:
        self.journal = self.activation_store.load_journal(activation_id)
        if self.journal.state is ActivationState.DEACTIVATED:
            return self.result()
        if self.journal.state is not ActivationState.PROVED:
            raise ValidationError("activation must be proved before deactivation")
        profile = self._load_profile()
        disabled = self.activation_store.load_disabled_registry(self.journal)
        enabled = self._enabled_registry_bytes(disabled)
        if self.target.registry_path.read_bytes() != enabled:
            raise ValidationError("activation registry ownership changed")
        _atomic_replace(self.target.registry_path, disabled)
        discovery = SkillDiscoveryService().resolve(
            self.target,
            self.profile_path,
            self.store,
            self.runner,
            self.policy,
        )
        if (
            discovery.ok
            or discovery.diagnostic is None
            or discovery.diagnostic.code != "REGISTRY_DISABLED"
        ):
            raise ValidationError("skill remained discoverable during deactivation")
        self.boundary_hook("before_scheduler_disable")
        definition = self._definition()
        adapter = adapter_for(profile)
        inspection = adapter.inspect(definition, self.runner)
        if inspection.state is SchedulerState.ENABLED:
            adapter.disable(definition, self.runner)
        inspection = adapter.inspect(definition, self.runner)
        if inspection.state is SchedulerState.INSTALLED_DISABLED:
            adapter.remove(definition, self.runner)
        self.journal = self.journal.transition(ActivationState.DEACTIVATED)
        self.activation_store.save_journal(self.journal)
        return self.result()
