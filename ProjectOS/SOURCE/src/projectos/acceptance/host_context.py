from __future__ import annotations

import getpass
import json
import os
import socket
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from projectos.acceptance.commands import HostPreflightPlan
from projectos.acceptance.authority import detect_host_session
from projectos.acceptance.collector import HostEvidenceCollector
from projectos.acceptance.controllers import (
    ActivationAcceptanceController,
    DefinitionAcceptanceController,
)
from projectos.acceptance.equivalence import compare_scheduler_definitions
from projectos.acceptance.native import (
    NativeProcessExecutor,
    RecordingProcessExecutor,
    SubprocessNativeExecutor,
)
from projectos.acceptance.native_macos import MacOSNativeSchedulerRunner
from projectos.acceptance.native_probe import NativeProbeController
from projectos.acceptance.native_windows import WindowsNativeSchedulerRunner
from projectos.acceptance.preparation import (
    AcceptancePreparationRequest,
    AcceptancePreparer,
    PreparedAcceptance,
)
from projectos.acceptance.transaction import (
    HostAcceptanceContext,
    HostAcceptanceResult,
    HostAcceptanceTransaction,
)
from projectos.adoption.activation import RuntimeActivation
from projectos.adoption.activation_store import ActivationProofResult
from projectos.adoption.bundle import ArtifactPolicy
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import machine_profile_from_mapping
from projectos.adoption.scheduler import adapter_for
from projectos.adoption.scheduler import SchedulerDefinition
from projectos.adoption.scheduler_fixture import FixtureSchedulerRunner
from projectos.adoption.store import LocalAdoptionStore
from projectos.database import ProjectOSDatabase
from projectos.errors import MigrationError, ValidationError
from projectos.google.fake_gateway import FakeGoogleGateway
from projectos.health import ProjectOSDoctor
from projectos.runtime import RuntimeSyncCoordinator, RuntimeTrigger


@dataclass(frozen=True)
class PreparedHostContext:
    prepared: PreparedAcceptance
    plan: HostPreflightPlan
    definition: SchedulerDefinition
    profile_path: Path


class _AcceptanceActivationProof:
    def __init__(self, profile, profile_path: Path) -> None:
        self.profile = profile
        self.profile_path = Path(profile_path)

    def run(self, discovered, coordinator: RuntimeSyncCoordinator) -> ActivationProofResult:
        gateway = FakeGoogleGateway.from_fixture(
            {
                "contract_version": 1,
                "tabs": {},
                "requests": [],
                "access_events": [],
                "write_ready": True,
            }
        )
        statuses = tuple(
            coordinator.run(
                self.profile_path,
                Path(str(self.profile.database_path)),
                trigger,
                gateway,
                wait_seconds=0,
            ).status
            for trigger in (RuntimeTrigger.SCHEDULER, RuntimeTrigger.SKILL)
        )
        return ActivationProofResult(
            all(status == "COMPLETE" for status in statuses),
            (RuntimeTrigger.SCHEDULER.value, RuntimeTrigger.SKILL.value),
            statuses,
            None,
        )


def _read_machine_profile(path: Path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("machine profile is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValidationError("machine profile is unavailable or invalid")
    return machine_profile_from_mapping(value)


def _database_healthy(path: Path) -> bool:
    database: ProjectOSDatabase | None = None
    try:
        database = ProjectOSDatabase.open_existing(Path(path), read_only=True)
        return ProjectOSDoctor(database).check().healthy
    except (MigrationError, sqlite3.DatabaseError, OSError, ValidationError):
        return False
    finally:
        if database is not None:
            database.close()


def _policy(fixture_root: Path) -> ArtifactPolicy:
    return ArtifactPolicy(
        (str(Path.home()), getpass.getuser(), socket.gethostname(), str(fixture_root))
    )


class HostAcceptanceContextFactory:
    def preflight(
        self,
        request: AcceptancePreparationRequest,
        *,
        session=None,
        executor_factory: Callable[[], NativeProcessExecutor] | None = None,
    ) -> PreparedHostContext:
        del executor_factory
        session = session or detect_host_session()
        prepared = AcceptancePreparer().open(request, session=session)
        production = _read_machine_profile(request.machine_profile)
        profile_path = Path(str(prepared.profile.machine_profile.runtime_root)) / "adoption/machine-profile.json"
        portable_profile_path = type(production.runtime_root)(str(profile_path))
        production_definition = adapter_for(production).render(
            production, portable_profile_path
        )
        definition = adapter_for(prepared.profile.machine_profile).render(
            prepared.profile.machine_profile,
            type(prepared.profile.machine_profile.runtime_root)(str(portable_profile_path)),
        )
        comparison = compare_scheduler_definitions(production_definition, definition)
        if not comparison.equivalent:
            raise ValidationError("acceptance scheduler definition differs from production structure")
        if not _database_healthy(Path(str(prepared.profile.machine_profile.database_path))):
            raise ValidationError("disposable acceptance database is unavailable or unhealthy")
        recorder = RecordingProcessExecutor()
        if prepared.target.host_family is HostFamily.MACOS:
            runner = MacOSNativeSchedulerRunner(
                prepared.target.runtime_root, os.getuid(), recorder, elevated=session.elevated
            )
        else:
            runner = WindowsNativeSchedulerRunner(
                prepared.target.runtime_root, recorder, elevated=session.elevated
            )
        plan = HostPreflightPlan(
            prepared.target.host_family,
            definition.sha256,
            runner.planned_actions(definition),
            True,
        )
        return PreparedHostContext(prepared, plan, definition, profile_path)

    def execution(
        self,
        request: AcceptancePreparationRequest,
        executor_factory: Callable[[], NativeProcessExecutor],
        *,
        session=None,
    ) -> HostAcceptanceContext:
        session = session or detect_host_session()
        prepared_context = self.preflight(request, session=session)
        executor = executor_factory()
        prepared = prepared_context.prepared
        profile = prepared.profile.machine_profile
        adoption_store = LocalAdoptionStore.open(profile)
        policy = _policy(prepared.fixture_target.root)
        fixture_runner = FixtureSchedulerRunner.open(
            prepared.fixture_target, profile, adoption_store
        )
        activation = RuntimeActivation(
            prepared.fixture_target,
            prepared_context.profile_path,
            adoption_store,
            fixture_runner,
            policy,
            _AcceptanceActivationProof(profile, prepared_context.profile_path),
        )
        definition_controller = DefinitionAcceptanceController(
            prepared.fixture_target,
            profile,
            adoption_store,
            policy,
            prepared.profile.definition_transaction_id,
            prepared.staged_extension_bundle,
        )
        activation_controller = ActivationAcceptanceController(
            activation,
            prepared.profile.definition_transaction_id,
            prepared.profile.activation_id,
        )
        if prepared.target.host_family is HostFamily.MACOS:
            native_runner = MacOSNativeSchedulerRunner(
                prepared.target.runtime_root, os.getuid(), executor, elevated=session.elevated
            )
        else:
            native_runner = WindowsNativeSchedulerRunner(
                prepared.target.runtime_root, executor, elevated=session.elevated
            )
        probe = NativeProbeController(
            prepared.profile,
            prepared_context.definition,
            native_runner,
            "unbound",
        )
        holder: dict[str, HostAcceptanceContext] = {}

        def seal(result: HostAcceptanceResult) -> None:
            HostEvidenceCollector().seal(
                holder["context"],
                result,
                prepared.evidence_root / f"projectos-{result.run_id}-evidence.zip",
            )

        context = HostAcceptanceContext(
            prepared.target,
            prepared.profile,
            prepared.store,
            prepared_context.definition,
            native_runner,
            definition_controller,
            activation_controller,
            probe,
            lambda: _database_healthy(Path(str(profile.database_path))),
            seal,
            True,
            prepared.record,
            prepared.record.canonical_bytes(),
            prepared.evidence_root,
            session.standard_user,
            not session.elevated,
            True,
        )
        holder["context"] = context
        return context


def run_prepared_acceptance(
    request: AcceptancePreparationRequest,
    *,
    session=None,
    executor_factory: Callable[[], NativeProcessExecutor] = SubprocessNativeExecutor,
    boundary_hook: Callable[[str], None] = lambda name: None,
) -> HostAcceptanceResult:
    session = session or detect_host_session()
    context = HostAcceptanceContextFactory().execution(
        request, executor_factory, session=session
    )
    transaction = HostAcceptanceTransaction(context)
    try:
        return transaction.begin(boundary_hook=boundary_hook)
    except Exception:
        if transaction.run_id:
            return transaction.recover(transaction.run_id)
        raise


def recover_prepared_acceptance(
    request: AcceptancePreparationRequest,
    run_id: str,
    *,
    session=None,
    executor_factory: Callable[[], NativeProcessExecutor] = SubprocessNativeExecutor,
) -> HostAcceptanceResult:
    session = session or detect_host_session()
    context = HostAcceptanceContextFactory().execution(
        request, executor_factory, session=session
    )
    return HostAcceptanceTransaction(context).recover(run_id)
