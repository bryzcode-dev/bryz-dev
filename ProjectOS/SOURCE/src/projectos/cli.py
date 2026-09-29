from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import sqlite3
import traceback
import zipfile
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path, PurePath
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from .backup import BackupService
from . import __version__
from .adoption.bundle import ArtifactPolicy, ExtensionBundleBuilder, verify_extension_bundle
from .adoption.activation import RuntimeActivation
from .adoption.activation_store import ActivationProofResult
from .adoption.contextos import ContextOSLocator
from .adoption.discovery import SkillDiscoveryService
from .adoption.fixture import FixtureInstallationTarget, issue_empty_fixture
from .adoption.host import HostFamily, HostIdentity, detect_host_family
from .adoption.manifest import ExtensionManifest
from .adoption.paths import PlatformPathOverrides, default_database_path, resolve_platform_paths
from .adoption.profile import (
    MachineProfile,
    SchedulerKind,
    machine_profile_from_mapping,
    plan_machine_profile,
)
from .adoption.scheduler import adapter_for
from .adoption.scheduler_fixture import FixtureSchedulerRunner
from .adoption.store import AdoptionOperation, LocalAdoptionStore
from .adoption.transaction import AdoptionTransaction
from .bindings import GoogleBindingRepository
from .contextos_adapter import ContextOSManifestAdapter
from .credentials import CredentialReferenceCreate, CredentialReferenceService
from .database import SCHEMA_VERSION, ProjectOSDatabase
from .discovery import DiscoveryService
from .errors import HealthError, MigrationError, ProjectOSError, ValidationError, VersionConflict
from .health import ProjectOSDoctor
from .google.bootstrap import WorkbookBootstrapPlanner
from .google.config import ProjectOSGoogleConfig
from .google.contract import WorkbookContract, WorkbookSnapshot
from .google.diagnostics import DiagnosticBundleService
from .google.fake_gateway import FakeGoogleGateway
from .google.real_gateway import GoogleIntegrationError, RealGoogleGateway
from .google.types import (
    GoogleBindingCreate,
    GoogleBindingPatch,
    UserCreate,
    UserPatch,
    UserRole,
)
from .looker.analytics import LookerAnalyticsService
from .looker.cutover import (
    CutoverPreparationRequest,
    CutoverPreparer,
    CutoverTarget,
    verify_cutover_package,
)
from .looker.evidence import verify_intake_archive
from .looker.importer import LookerImporter
from .looker.reconcile import LookerReconciler, ReconciliationPolicy
from .looker.refresh import RefreshReceipt
from .repositories import (
    ConnectionRepository,
    DeploymentRepository,
    LocationRepository,
    ProjectRepository,
    ResourceRepository,
)
from .types import (
    ConnectionDirection,
    ConnectionUpsert,
    DeploymentEnvironment,
    DeploymentUpsert,
    LocationUpsert,
    ProjectCreate,
    ProjectPatch,
    ProjectStatus,
    ProjectType,
    ProjectVisibility,
    ResourceUpsert,
)
from .sync.authorization import AuthorizationService
from .sync.mutations import MutationRegistry
from .sync.requests import RequestProcessor, RequestResultCode
from .sync.service import GoogleSyncService
from .runtime import RuntimeSyncCoordinator, RuntimeTrigger, load_runtime_profile
from .users import UserRepository


DATABASE_FREE_COMMANDS = frozenset(
    {
        "adoption inspect",
        "adoption profile plan",
        "adoption manifest validate",
        "adoption bundle build",
        "adoption bundle verify",
        "adoption fixture init",
        "adoption fixture preflight",
        "adoption fixture adopt",
        "adoption fixture upgrade",
        "adoption fixture rollback",
        "adoption fixture uninstall",
        "adoption fixture recover",
        "adoption fixture scheduler render",
        "adoption fixture activate",
        "adoption fixture deactivate",
        "adoption fixture activation-recover",
        "adoption fixture skill inspect",
        "acceptance package build",
        "acceptance package verify",
        "acceptance evidence verify",
        "acceptance reconcile",
        "looker intake verify",
        "looker intake preview",
        "looker cutover verify",
    }
)

LOOKER_DATABASE_COMMANDS = frozenset(
    {"looker intake import", "looker analytics build", "looker analytics show", "looker reconcile stage", "looker reconcile report", "looker reconcile waive", "looker cutover prepare"}
)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValidationError("invalid command arguments")


def _uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValidationError("identifier must be a UUID") from exc


def _mapping(value: str | None, field: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{field} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValidationError(f"{field} must be a JSON object")
    return parsed


def _json_file(path: Path, field: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{field} file is invalid") from exc
    if not isinstance(parsed, dict):
        raise ValidationError(f"{field} must be a JSON object")
    return parsed


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (UUID, PurePath)):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _add_actor(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--actor", required=True)


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(prog="projectos", add_help=True)
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
    )
    commands = parser.add_subparsers(dest="group", required=True)
    commands.add_parser("init").set_defaults(command="init")
    commands.add_parser("doctor").set_defaults(command="doctor")

    project = commands.add_parser("project").add_subparsers(dest="action", required=True)
    create = project.add_parser("create")
    create.add_argument("--slug", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--type", choices=[item.value for item in ProjectType], required=True)
    create.add_argument(
        "--visibility", choices=[item.value for item in ProjectVisibility], required=True
    )
    create.add_argument("--description", default="")
    create.add_argument("--status", choices=[item.value for item in ProjectStatus], default="ACTIVE")
    create.add_argument("--context-os-registered", action="store_true")
    create.add_argument("--context-os-project-id")
    create.add_argument("--tag", action="append", default=[])
    create.add_argument("--source-key")
    _add_actor(create)
    create.set_defaults(command="project create")
    get = project.add_parser("get")
    get.add_argument("project_id")
    get.set_defaults(command="project get")
    listing = project.add_parser("list")
    listing.add_argument("--include-archived", action="store_true")
    listing.set_defaults(command="project list")
    update = project.add_parser("update")
    update.add_argument("project_id")
    update.add_argument("--expected-version", required=True, type=int)
    update.add_argument("--name")
    update.add_argument("--description")
    update.add_argument("--type", choices=[item.value for item in ProjectType])
    update.add_argument("--status", choices=[item.value for item in ProjectStatus])
    update.add_argument("--visibility", choices=[item.value for item in ProjectVisibility])
    update.add_argument("--context-os-project-id")
    update.add_argument("--tag", action="append")
    _add_actor(update)
    update.set_defaults(command="project update")
    archive = project.add_parser("archive")
    archive.add_argument("project_id")
    archive.add_argument("--expected-version", required=True, type=int)
    _add_actor(archive)
    archive.set_defaults(command="project archive")

    location = commands.add_parser("location").add_subparsers(dest="action", required=True)
    location_upsert = location.add_parser("upsert")
    location_upsert.add_argument("project_id")
    location_upsert.add_argument("--machine-id", required=True)
    location_upsert.add_argument("--location-type", required=True)
    location_upsert.add_argument("--path")
    location_upsert.add_argument("--repository-root")
    location_upsert.add_argument("--drive-folder-id")
    location_upsert.add_argument("--drive-folder-url")
    location_upsert.add_argument("--environment", default="")
    _add_actor(location_upsert)
    location_upsert.set_defaults(command="location upsert")

    resource = commands.add_parser("resource").add_subparsers(dest="action", required=True)
    resource_upsert = resource.add_parser("upsert")
    resource_upsert.add_argument("project_id")
    resource_upsert.add_argument("--resource-type", required=True)
    resource_upsert.add_argument("--provider", required=True)
    resource_upsert.add_argument("--name", required=True)
    resource_upsert.add_argument("--external-id")
    resource_upsert.add_argument("--url")
    resource_upsert.add_argument("--environment", default="")
    resource_upsert.add_argument("--role", default="USES")
    resource_upsert.add_argument("--metadata")
    _add_actor(resource_upsert)
    resource_upsert.set_defaults(command="resource upsert")

    deployment = commands.add_parser("deployment").add_subparsers(dest="action", required=True)
    deployment_upsert = deployment.add_parser("upsert")
    deployment_upsert.add_argument("project_id")
    deployment_upsert.add_argument(
        "--environment", choices=[item.value for item in DeploymentEnvironment], required=True
    )
    deployment_upsert.add_argument("--external-deployment-id", required=True)
    deployment_upsert.add_argument("--script-id")
    deployment_upsert.add_argument("--deployment-url")
    deployment_upsert.add_argument("--resource-id")
    deployment_upsert.add_argument("--active-version")
    _add_actor(deployment_upsert)
    deployment_upsert.set_defaults(command="deployment upsert")

    connection = commands.add_parser("connection").add_subparsers(dest="action", required=True)
    connection_upsert = connection.add_parser("upsert")
    connection_upsert.add_argument("--connection-type", required=True)
    connection_upsert.add_argument("--implementation-method", required=True)
    connection_upsert.add_argument("--source-project-id")
    connection_upsert.add_argument("--source-resource-id")
    connection_upsert.add_argument("--target-project-id")
    connection_upsert.add_argument("--target-resource-id")
    connection_upsert.add_argument(
        "--direction", choices=[item.value for item in ConnectionDirection], default="DIRECTED"
    )
    connection_upsert.add_argument("--purpose", default="")
    connection_upsert.add_argument("--notes", default="")
    _add_actor(connection_upsert)
    connection_upsert.set_defaults(command="connection upsert")
    connection_impact = connection.add_parser("impact")
    connection_impact.add_argument("resource_id")
    connection_impact.set_defaults(command="connection impact")

    credential = commands.add_parser("credential").add_subparsers(dest="action", required=True)
    credential_create = credential.add_parser("create")
    credential_create.add_argument("--provider", required=True)
    credential_create.add_argument("--label", required=True)
    credential_create.add_argument("--credential-type", required=True)
    credential_create.add_argument("--purpose", required=True)
    credential_create.add_argument("--storage-system", required=True)
    credential_create.add_argument("--storage-reference", required=True)
    credential_create.add_argument("--owner-project-id")
    credential_create.add_argument("--scope-description", default="")
    credential_create.add_argument("--rotation-due-at")
    credential_create.add_argument("--notes", default="")
    _add_actor(credential_create)
    credential_create.set_defaults(command="credential create")
    credential_link = credential.add_parser("link")
    credential_link.add_argument("credential_id")
    credential_link.add_argument("project_id")
    credential_link.add_argument("--resource-id")
    credential_link.add_argument("--purpose", required=True)
    _add_actor(credential_link)
    credential_link.set_defaults(command="credential link")
    credential_impact = credential.add_parser("impact")
    credential_impact.add_argument("credential_id")
    credential_impact.set_defaults(command="credential impact")

    discover = commands.add_parser("discover").add_subparsers(dest="action", required=True)
    contextos = discover.add_parser("contextos")
    contextos.add_argument("--projects-dir", type=Path, required=True)
    contextos.add_argument("--machine-id", required=True)
    contextos.add_argument("--source-run-id", required=True)
    contextos.set_defaults(command="discover contextos")
    discover_list = discover.add_parser("list")
    discover_list.add_argument("--status")
    discover_list.set_defaults(command="discover list")
    discover_apply = discover.add_parser("apply")
    discover_apply.add_argument("finding_id")
    _add_actor(discover_apply)
    discover_apply.set_defaults(command="discover apply")
    discover_reject = discover.add_parser("reject")
    discover_reject.add_argument("finding_id")
    discover_reject.add_argument("--reason", required=True)
    _add_actor(discover_reject)
    discover_reject.set_defaults(command="discover reject")

    backup = commands.add_parser("backup").add_subparsers(dest="action", required=True)
    backup_create = backup.add_parser("create")
    backup_create.add_argument("destination_dir", type=Path)
    backup_create.set_defaults(command="backup create")
    backup_verify = backup.add_parser("verify")
    backup_verify.add_argument("manifest_path", type=Path)
    backup_verify.set_defaults(command="backup verify")
    backup_restore = backup.add_parser("restore")
    backup_restore.add_argument("manifest_path", type=Path)
    backup_restore.add_argument("target_db", type=Path)
    backup_restore.add_argument("--replace", action="store_true")
    backup_restore.set_defaults(command="backup restore")

    looker = commands.add_parser("looker").add_subparsers(dest="looker_section", required=True)
    intake = looker.add_parser("intake").add_subparsers(dest="looker_intake_action", required=True)
    for action in ("verify", "preview"):
        item = intake.add_parser(action)
        item.add_argument("archive", type=Path)
        item.set_defaults(command=f"looker intake {action}")
    intake_import = intake.add_parser("import")
    intake_import.add_argument("archive", type=Path)
    intake_import.add_argument("project_id")
    intake_import.add_argument("--owner-email", required=True)
    _add_actor(intake_import)
    intake_import.set_defaults(command="looker intake import")
    analytics = looker.add_parser("analytics").add_subparsers(dest="looker_analytics_action", required=True)
    analytics_build = analytics.add_parser("build")
    analytics_build.add_argument("project_id")
    analytics_build.add_argument("intake_run_id")
    analytics_build.add_argument("--owner-email", required=True)
    _add_actor(analytics_build)
    analytics_build.set_defaults(command="looker analytics build")
    analytics_show = analytics.add_parser("show")
    analytics_show.add_argument("project_id")
    analytics_show.add_argument("--owner-email", required=True)
    analytics_show.add_argument("--node")
    analytics_show.add_argument("--direction", choices=("dependencies", "impact"))
    _add_actor(analytics_show)
    analytics_show.set_defaults(command="looker analytics show")
    reconcile = looker.add_parser("reconcile").add_subparsers(dest="looker_reconcile_action", required=True)
    reconcile_stage = reconcile.add_parser("stage")
    reconcile_stage.add_argument("project_id")
    reconcile_stage.add_argument("intake_run_id")
    reconcile_stage.add_argument("analytic_version", type=int)
    reconcile_stage.add_argument("--legacy-snapshot", type=Path, required=True)
    reconcile_stage.add_argument("--policy", type=Path, required=True)
    reconcile_stage.add_argument("--owner-email", required=True)
    _add_actor(reconcile_stage)
    reconcile_stage.set_defaults(command="looker reconcile stage")
    reconcile_report = reconcile.add_parser("report")
    reconcile_report.add_argument("reconciliation_id")
    reconcile_report.add_argument("--owner-email", required=True)
    _add_actor(reconcile_report)
    reconcile_report.set_defaults(command="looker reconcile report")
    reconcile_waive = reconcile.add_parser("waive")
    reconcile_waive.add_argument("reconciliation_id")
    reconcile_waive.add_argument("dimension")
    reconcile_waive.add_argument("item_key")
    reconcile_waive.add_argument("--reason", required=True)
    reconcile_waive.add_argument("--owner-email", required=True)
    _add_actor(reconcile_waive)
    reconcile_waive.set_defaults(command="looker reconcile waive")
    cutover = looker.add_parser("cutover").add_subparsers(dest="looker_cutover_action", required=True)
    cutover_prepare = cutover.add_parser("prepare")
    cutover_prepare.add_argument("project_id")
    cutover_prepare.add_argument("intake_run_id")
    cutover_prepare.add_argument("reconciliation_id")
    cutover_prepare.add_argument("--refresh-receipt", type=Path, required=True)
    cutover_prepare.add_argument("--backup-manifest", type=Path, required=True)
    cutover_prepare.add_argument("--legacy-root", type=Path, required=True)
    cutover_prepare.add_argument("--targets", type=Path, required=True)
    cutover_prepare.add_argument("--prepared-at", required=True)
    cutover_prepare.add_argument("--output", type=Path, required=True)
    cutover_prepare.add_argument("--owner-email", required=True)
    _add_actor(cutover_prepare)
    cutover_prepare.set_defaults(command="looker cutover prepare")
    cutover_verify = cutover.add_parser("verify")
    cutover_verify.add_argument("package", type=Path)
    cutover_verify.set_defaults(command="looker cutover verify")

    user = commands.add_parser("user").add_subparsers(dest="action", required=True)
    seed_owner = user.add_parser("seed-owner")
    seed_owner.add_argument("--owner-email", required=True)
    seed_owner.add_argument("--display-name", required=True)
    seed_owner.set_defaults(command="user seed-owner")
    user_create = user.add_parser("create")
    user_create.add_argument("--owner-email", required=True)
    user_create.add_argument("--email", required=True)
    user_create.add_argument("--display-name", required=True)
    user_create.add_argument("--role", choices=[item.value for item in UserRole], required=True)
    user_create.add_argument("--notes", default="")
    _add_actor(user_create)
    user_create.set_defaults(command="user create")
    user_list = user.add_parser("list")
    user_list.add_argument("--owner-email", required=True)
    user_list.add_argument("--active-only", action="store_true")
    user_list.set_defaults(command="user list")
    user_update = user.add_parser("update")
    user_update.add_argument("user_id")
    user_update.add_argument("--owner-email", required=True)
    user_update.add_argument("--expected-version", required=True, type=int)
    user_update.add_argument("--email")
    user_update.add_argument("--display-name")
    user_update.add_argument("--role", choices=[item.value for item in UserRole])
    user_update.add_argument("--notes")
    user_update.add_argument("--active", choices=("true", "false"))
    _add_actor(user_update)
    user_update.set_defaults(command="user update")
    user_deactivate = user.add_parser("deactivate")
    user_deactivate.add_argument("user_id")
    user_deactivate.add_argument("--owner-email", required=True)
    user_deactivate.add_argument("--expected-version", required=True, type=int)
    _add_actor(user_deactivate)
    user_deactivate.set_defaults(command="user deactivate")

    google_parser = commands.add_parser("google")
    google = google_parser.add_subparsers(dest="google_section", required=True)
    binding = google.add_parser("binding").add_subparsers(dest="binding_action", required=True)
    binding_create = binding.add_parser("create")
    binding_create.add_argument("--environment", required=True)
    binding_create.add_argument("--spreadsheet-id", required=True)
    binding_create.add_argument("--display-name", required=True)
    binding_create.add_argument("--contract-version", required=True, type=int)
    binding_create.add_argument("--credential-id", required=True)
    binding_create.add_argument("--gas-script-id")
    binding_create.add_argument("--gas-deployment-id")
    binding_create.add_argument("--enabled", action="store_true")
    binding_create.add_argument("--write-enabled", action="store_true")
    _add_actor(binding_create)
    binding_create.set_defaults(command="google binding create")
    binding_get = binding.add_parser("get")
    binding_get.add_argument("binding_id")
    binding_get.set_defaults(command="google binding get")
    binding_list = binding.add_parser("list")
    binding_list.set_defaults(command="google binding list")
    binding_update = binding.add_parser("update")
    binding_update.add_argument("binding_id")
    binding_update.add_argument("--expected-version", required=True, type=int)
    binding_update.add_argument("--display-name")
    binding_update.add_argument("--contract-version", type=int)
    binding_update.add_argument("--credential-id")
    binding_update.add_argument("--gas-script-id")
    binding_update.add_argument("--gas-deployment-id")
    binding_update.add_argument("--enabled", choices=("true", "false"))
    binding_update.add_argument("--write-enabled", choices=("true", "false"))
    _add_actor(binding_update)
    binding_update.set_defaults(command="google binding update")

    contract = google.add_parser("contract").add_subparsers(dest="contract_action", required=True)
    contract_show = contract.add_parser("show")
    contract_show.set_defaults(command="google contract show")
    contract_plan = contract.add_parser("plan")
    contract_plan.add_argument("--snapshot", type=Path, required=True)
    contract_plan.set_defaults(command="google contract plan")

    preflight = google.add_parser("preflight")
    preflight.add_argument("binding_id")
    preflight.add_argument("--gateway", choices=("fake", "google"), default="fake")
    preflight.add_argument("--fixture", type=Path)
    preflight.add_argument("--config", type=Path)
    preflight.set_defaults(command="google preflight")

    sync = commands.add_parser("sync").add_subparsers(dest="sync_action", required=True)
    for action in ("plan", "run"):
        item = sync.add_parser(action)
        item.add_argument("binding_id")
        item.add_argument("--owner-email", required=True)
        item.add_argument("--gateway", choices=("fake", "google"), default="fake")
        item.add_argument("--fixture", type=Path)
        item.add_argument("--config", type=Path)
        item.add_argument("--allow-google-writes", action="store_true")
        item.add_argument("--lock-path", type=Path)
        if action == "run":
            item.add_argument("--trigger", default="manual")
        item.set_defaults(command=f"sync {action}")
    sync_status = sync.add_parser("status")
    sync_status.add_argument("binding_id")
    sync_status.add_argument("--owner-email", required=True)
    sync_status.set_defaults(command="sync status")

    runtime = commands.add_parser("runtime").add_subparsers(
        dest="runtime_action", required=True
    )
    runtime_sync = runtime.add_parser("sync")
    runtime_sync.add_argument("--machine-profile", type=Path, required=True)
    runtime_sync.add_argument(
        "--trigger", choices=[item.value for item in RuntimeTrigger], required=True
    )
    runtime_sync.add_argument("--wait-seconds", type=float)
    runtime_sync.set_defaults(command="runtime sync")

    conflict = commands.add_parser("conflict").add_subparsers(dest="conflict_action", required=True)
    conflict_list = conflict.add_parser("list")
    conflict_list.add_argument("--status", default="OPEN")
    conflict_list.add_argument("--owner-email", required=True)
    conflict_list.set_defaults(command="conflict list")
    conflict_resolve = conflict.add_parser("resolve")
    conflict_resolve.add_argument("conflict_id")
    conflict_resolve.add_argument("--binding-id", required=True)
    conflict_resolve.add_argument("--owner-email", required=True)
    conflict_resolve.add_argument("--actor-email", required=True)
    conflict_resolve.add_argument("--strategy", choices=("KEEP_CANONICAL",), required=True)
    conflict_resolve.set_defaults(command="conflict resolve")

    diagnostics = commands.add_parser("diagnostics").add_subparsers(
        dest="diagnostics_action", required=True
    )
    diagnostics_create = diagnostics.add_parser("create")
    diagnostics_create.add_argument("destination", type=Path)
    diagnostics_create.set_defaults(command="diagnostics create")

    adoption = commands.add_parser("adoption").add_subparsers(
        dest="adoption_action", required=True
    )
    inspect = adoption.add_parser("inspect")
    inspect.add_argument("--host-family", choices=[item.value for item in HostFamily])
    inspect.add_argument("--contextos-root")
    inspect.set_defaults(command="adoption inspect")

    profile = adoption.add_parser("profile").add_subparsers(
        dest="adoption_profile_action", required=True
    )
    profile_plan = profile.add_parser("plan")
    profile_plan.add_argument("--python-executable", required=True)
    profile_plan.add_argument("--host-family", choices=[item.value for item in HostFamily])
    profile_plan.add_argument("--contextos-root")
    profile_plan.add_argument("--projectos-home")
    profile_plan.set_defaults(command="adoption profile plan")

    manifest = adoption.add_parser("manifest").add_subparsers(
        dest="adoption_manifest_action", required=True
    )
    manifest_validate = manifest.add_parser("validate")
    manifest_validate.add_argument("manifest", type=Path)
    manifest_validate.set_defaults(command="adoption manifest validate")

    bundle = adoption.add_parser("bundle").add_subparsers(
        dest="adoption_bundle_action", required=True
    )
    bundle_build = bundle.add_parser("build")
    bundle_build.add_argument("manifest", type=Path)
    bundle_build.add_argument("payload_root", type=Path)
    bundle_build.add_argument("output", type=Path)
    bundle_build.add_argument("--forbid", action="append", default=[])
    bundle_build.add_argument("--contextos-root")
    bundle_build.set_defaults(command="adoption bundle build")
    bundle_verify = bundle.add_parser("verify")
    bundle_verify.add_argument("bundle", type=Path)
    bundle_verify.add_argument("--forbid", action="append", default=[])
    bundle_verify.add_argument("--contextos-root")
    bundle_verify.set_defaults(command="adoption bundle verify")

    fixture = adoption.add_parser("fixture").add_subparsers(
        dest="adoption_fixture_action", required=True
    )
    fixture_init = fixture.add_parser("init")
    fixture_init.add_argument("root", type=Path)
    fixture_init.add_argument("--runtime-root", type=Path, required=True)
    fixture_init.add_argument(
        "--host-family", choices=[item.value for item in HostFamily], required=True
    )
    fixture_init.add_argument("--machine-id", required=True)
    fixture_init.add_argument("--contextos-version", default="3.0.1")
    fixture_init.set_defaults(command="adoption fixture init")

    def add_fixture_target(selected: argparse.ArgumentParser) -> None:
        selected.add_argument("--fixture-ack", required=True)
        selected.add_argument("--contextos-root", type=Path, required=True)
        selected.add_argument("--machine-profile", type=Path, required=True)
        selected.add_argument("--forbid", action="append", default=[])

    fixture_preflight = fixture.add_parser("preflight")
    fixture_preflight.add_argument("bundle", type=Path)
    add_fixture_target(fixture_preflight)
    fixture_preflight.set_defaults(command="adoption fixture preflight")
    for action in ("adopt", "upgrade"):
        selected = fixture.add_parser(action)
        selected.add_argument("bundle", type=Path)
        add_fixture_target(selected)
        selected.set_defaults(command=f"adoption fixture {action}")
    fixture_rollback = fixture.add_parser("rollback")
    fixture_rollback.add_argument("transaction_id")
    add_fixture_target(fixture_rollback)
    fixture_rollback.set_defaults(command="adoption fixture rollback")
    fixture_uninstall = fixture.add_parser("uninstall")
    add_fixture_target(fixture_uninstall)
    fixture_uninstall.set_defaults(command="adoption fixture uninstall")
    fixture_recover = fixture.add_parser("recover")
    fixture_recover.add_argument("transaction_id")
    add_fixture_target(fixture_recover)
    fixture_recover.set_defaults(command="adoption fixture recover")

    fixture_scheduler = fixture.add_parser("scheduler").add_subparsers(
        dest="adoption_fixture_scheduler_action", required=True
    )
    fixture_scheduler_render = fixture_scheduler.add_parser("render")
    add_fixture_target(fixture_scheduler_render)
    fixture_scheduler_render.set_defaults(
        command="adoption fixture scheduler render"
    )

    fixture_activate = fixture.add_parser("activate")
    fixture_activate.add_argument("definition_transaction_id")
    add_fixture_target(fixture_activate)
    fixture_activate.set_defaults(command="adoption fixture activate")

    fixture_deactivate = fixture.add_parser("deactivate")
    fixture_deactivate.add_argument("activation_id")
    add_fixture_target(fixture_deactivate)
    fixture_deactivate.set_defaults(command="adoption fixture deactivate")

    fixture_activation_recover = fixture.add_parser("activation-recover")
    fixture_activation_recover.add_argument("activation_id")
    add_fixture_target(fixture_activation_recover)
    fixture_activation_recover.set_defaults(
        command="adoption fixture activation-recover"
    )

    fixture_skill = fixture.add_parser("skill").add_subparsers(
        dest="adoption_fixture_skill_action", required=True
    )
    fixture_skill_inspect = fixture_skill.add_parser("inspect")
    add_fixture_target(fixture_skill_inspect)
    fixture_skill_inspect.set_defaults(command="adoption fixture skill inspect")

    acceptance_parser = commands.add_parser("acceptance")
    acceptance = acceptance_parser.add_subparsers(dest="acceptance_section", required=True)
    acceptance_package = acceptance.add_parser("package").add_subparsers(
        dest="acceptance_package_action", required=True
    )
    acceptance_build = acceptance_package.add_parser("build")
    acceptance_build.add_argument("--wheel", type=Path, required=True)
    acceptance_build.add_argument("--extension-bundle", type=Path, required=True)
    acceptance_build.add_argument("--source-revision", required=True)
    acceptance_build.add_argument("--created-at", required=True)
    acceptance_build.add_argument("--output", type=Path, required=True)
    acceptance_build.set_defaults(command="acceptance package build")
    acceptance_verify = acceptance_package.add_parser("verify")
    acceptance_verify.add_argument("package", type=Path)
    acceptance_verify.set_defaults(command="acceptance package verify")
    acceptance_evidence = acceptance.add_parser("evidence").add_subparsers(
        dest="acceptance_evidence_action", required=True
    )
    evidence_verify = acceptance_evidence.add_parser("verify")
    evidence_verify.add_argument("evidence", type=Path)
    evidence_verify.add_argument("--manifest", type=Path, required=True)
    evidence_verify.set_defaults(command="acceptance evidence verify")
    reconcile = acceptance.add_parser("reconcile")
    reconcile.add_argument("--manifest", type=Path, required=True)
    reconcile.add_argument("--evidence", type=Path, action="append", default=[])
    reconcile.add_argument("--output", type=Path)
    reconcile.set_defaults(command="acceptance reconcile")
    return parser


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value == "true"


def _workbook_snapshot(path: Path) -> WorkbookSnapshot:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        tabs = {
            name: (tuple(value.get("headers", ())), int(value.get("row_count", 0)))
            for name, value in data.get("tabs", {}).items()
        }
        return WorkbookSnapshot(data.get("contract_version"), tabs)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValidationError("workbook snapshot is invalid") from exc


def _gateway(arguments: argparse.Namespace, *, for_write: bool = False):
    gateway_name = getattr(arguments, "gateway", "fake")
    if gateway_name == "fake":
        fixture = getattr(arguments, "fixture", None)
        value: Mapping[str, Any] | Path = fixture or {
            "contract_version": 1,
            "tabs": {},
            "requests": [],
            "access_events": [],
            "write_ready": True,
        }
        return FakeGoogleGateway.from_fixture(value)
    if for_write and not getattr(arguments, "allow_google_writes", False):
        raise ValidationError("Google writes require the explicit --allow-google-writes flag")
    configuration = ProjectOSGoogleConfig.load(getattr(arguments, "config", None))
    if not configuration.google_enabled:
        raise ValidationError("Google integration is disabled in configuration")
    allow_writes = bool(
        for_write
        and getattr(arguments, "allow_google_writes", False)
        and configuration.google_write_enabled
    )
    if for_write and not allow_writes:
        raise ValidationError("Google writes are disabled in configuration")
    return RealGoogleGateway(
        configuration.expected_owner_email,
        allow_writes=allow_writes,
        cli_write_flag=bool(getattr(arguments, "allow_google_writes", False)),
    )


def _selected_host(arguments: argparse.Namespace) -> HostFamily:
    configured = getattr(arguments, "host_family", None)
    return HostFamily(configured) if configured else detect_host_family()


def _selected_home(family: HostFamily, environ: Mapping[str, str]) -> str | Path:
    if family is HostFamily.WINDOWS:
        return environ.get("USERPROFILE") or Path.home()
    return environ.get("HOME") or Path.home()


def _read_manifest(path: Path) -> ExtensionManifest:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("extension manifest is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValidationError("extension manifest is unavailable or invalid")
    return ExtensionManifest.from_mapping(value)


def _read_machine_profile(path: Path) -> MachineProfile:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("machine profile is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValidationError("machine profile is unavailable or invalid")
    return machine_profile_from_mapping(value)


def _fixture_transaction_context(
    arguments: argparse.Namespace,
) -> tuple[MachineProfile, FixtureInstallationTarget, LocalAdoptionStore, ArtifactPolicy]:
    profile = _read_machine_profile(arguments.machine_profile)
    environ = dict(os.environ)
    installation = ContextOSLocator(
        profile.host_family,
        environ,
        _selected_home(profile.host_family, environ),
    ).inspect(arguments.contextos_root)
    target = FixtureInstallationTarget.open(
        installation, profile.runtime_root, arguments.fixture_ack
    )
    store = LocalAdoptionStore.open(profile)
    policy = _artifact_policy(arguments.forbid, str(arguments.contextos_root))
    return profile, target, store, policy


def _run_fixture_transaction(arguments: argparse.Namespace) -> Any:
    profile, target, store, policy = _fixture_transaction_context(arguments)
    command = arguments.command
    try:
        if command in {
            "adoption fixture preflight",
            "adoption fixture adopt",
            "adoption fixture upgrade",
        }:
            operation = (
                AdoptionOperation.UPGRADE
                if command == "adoption fixture upgrade"
                else AdoptionOperation.ADOPT
            )
            transaction = AdoptionTransaction.begin(
                operation,
                target,
                profile,
                store,
                policy,
                str(uuid4()),
                arguments.bundle,
            )
            result = transaction.preflight()
            if command == "adoption fixture preflight":
                return result
            transaction.snapshot()
            transaction.stage()
            transaction.verify()
            return transaction.adopt_disabled()
        if command == "adoption fixture uninstall":
            transaction = AdoptionTransaction.begin(
                AdoptionOperation.UNINSTALL,
                target,
                profile,
                store,
                policy,
                str(uuid4()),
            )
            transaction.preflight()
            transaction.snapshot()
            return transaction.uninstall()
        transaction = AdoptionTransaction.resume(
            target,
            profile,
            store,
            policy,
            arguments.transaction_id,
        )
        if command == "adoption fixture rollback":
            return transaction.rollback()
        if command == "adoption fixture recover":
            return transaction.recover()
    except ProjectOSError:
        raise
    except Exception as exc:
        raise HealthError("fixture adoption transaction failed") from exc
    raise ValidationError("unsupported fixture transaction command")


def _artifact_policy(
    supplied: Sequence[str], contextos_root: str | None = None
) -> ArtifactPolicy:
    automatic = [str(Path.home()), getpass.getuser(), socket.gethostname()]
    if contextos_root:
        automatic.append(contextos_root)
    return ArtifactPolicy((*supplied, *automatic))


class _FixtureActivationProof:
    def __init__(self, profile: MachineProfile, profile_path: Path):
        self.profile = profile
        self.profile_path = Path(profile_path)

    def run(self, discovered, coordinator) -> ActivationProofResult:
        gateway = FakeGoogleGateway.from_fixture(
            {
                "contract_version": 1,
                "tabs": {},
                "requests": [],
                "access_events": [],
                "write_ready": True,
            }
        )
        statuses = []
        for trigger in (RuntimeTrigger.SCHEDULER, RuntimeTrigger.SKILL):
            result = coordinator.run(
                self.profile_path,
                Path(str(self.profile.database_path)),
                trigger,
                gateway,
                wait_seconds=0,
            )
            statuses.append(result.status)
        return ActivationProofResult(
            all(status == "COMPLETE" for status in statuses),
            (RuntimeTrigger.SCHEDULER.value, RuntimeTrigger.SKILL.value),
            tuple(statuses),
            None,
        )


def _scheduler_summary(definition) -> dict[str, object]:
    return {
        "host_family": definition.host_family.value,
        "scheduler_kind": definition.scheduler_kind.value,
        "task_id": definition.task_id,
        "interval_seconds": definition.interval_seconds,
        "execution_limit_seconds": definition.execution_limit_seconds,
        "enabled": definition.enabled,
        "sha256": definition.sha256,
        "argv": definition.argv,
    }


def _run_fixture_phase3c(arguments: argparse.Namespace) -> Any:
    profile, target, store, policy = _fixture_transaction_context(arguments)
    runner = FixtureSchedulerRunner.open(target, profile, store)
    command = arguments.command
    if command == "adoption fixture scheduler render":
        definition = adapter_for(profile).render(profile, arguments.machine_profile)
        adapter_for(profile).verify(definition, profile, arguments.machine_profile)
        return _scheduler_summary(definition)
    if command == "adoption fixture skill inspect":
        return SkillDiscoveryService().resolve(
            target,
            arguments.machine_profile,
            store,
            runner,
            policy,
        )

    activation = RuntimeActivation(
        target,
        arguments.machine_profile,
        store,
        runner,
        policy,
        _FixtureActivationProof(profile, arguments.machine_profile),
    )
    try:
        if command == "adoption fixture activate":
            return activation.begin(arguments.definition_transaction_id)
        if command == "adoption fixture deactivate":
            return activation.deactivate(arguments.activation_id)
        if command == "adoption fixture activation-recover":
            return activation.recover(arguments.activation_id)
    except ProjectOSError as exc:
        if activation.journal is None:
            raise
        raise HealthError("fixture runtime activation failed") from exc
    raise ValidationError("unsupported fixture activation command")


def _run_runtime_sync(arguments: argparse.Namespace) -> Any:
    if arguments.db is None:
        raise ValidationError("runtime sync requires an explicit database")
    profile = load_runtime_profile(arguments.machine_profile)
    if (
        arguments.db.is_symlink()
        or arguments.db.resolve() != Path(str(profile.database_path)).resolve()
    ):
        raise ValidationError("database does not match machine profile")
    config = ProjectOSGoogleConfig.load(
        Path(str(profile.config_path)), family=profile.host_family
    )
    gateway = RealGoogleGateway(
        config.expected_owner_email,
        allow_writes=True,
        cli_write_flag=True,
    )
    try:
        return RuntimeSyncCoordinator().run(
            arguments.machine_profile,
            arguments.db,
            RuntimeTrigger(arguments.trigger),
            gateway,
            wait_seconds=arguments.wait_seconds,
        )
    except GoogleIntegrationError as exc:
        raise HealthError("configured Google synchronization failed") from exc


def dispatch_without_database(arguments: argparse.Namespace) -> Any:
    command = arguments.command
    if command == "looker intake verify":
        return verify_intake_archive(arguments.archive)
    if command == "looker intake preview":
        evidence = verify_intake_archive(arguments.archive)
        with zipfile.ZipFile(evidence.path) as archive:
            assets = json.loads(archive.read("looker-assets.json"))["items"]
            relationships = json.loads(archive.read("looker-relationships.json"))["items"]
            findings = json.loads(archive.read("findings.json"))["items"]
        return {
            "archive_sha256": evidence.sha256,
            "source_run_id": evidence.manifest["run_id"],
            "asset_count": len(assets),
            "relationship_count": len(relationships),
            "finding_count": len(findings),
            "findings": findings,
        }
    if command == "looker cutover verify":
        return verify_cutover_package(arguments.package)
    if command.startswith("acceptance "):
        from .acceptance.commands import run_acceptance_command

        return run_acceptance_command(arguments)
    if command == "adoption fixture init":
        return issue_empty_fixture(
            arguments.root,
            arguments.runtime_root,
            HostFamily(arguments.host_family),
            arguments.machine_id,
            arguments.contextos_version,
        )
    if command in {
        "adoption fixture scheduler render",
        "adoption fixture activate",
        "adoption fixture deactivate",
        "adoption fixture activation-recover",
        "adoption fixture skill inspect",
    }:
        return _run_fixture_phase3c(arguments)
    if command.startswith("adoption fixture "):
        return _run_fixture_transaction(arguments)
    if command in {"adoption inspect", "adoption profile plan"}:
        family = _selected_host(arguments)
        environ = dict(os.environ)
        home = _selected_home(family, environ)
        installation = ContextOSLocator(family, environ, home).inspect(
            arguments.contextos_root
        )
        if command == "adoption inspect":
            return installation
        overrides = PlatformPathOverrides(runtime_root=arguments.projectos_home)
        paths = resolve_platform_paths(family, environ, home, overrides)
        identity = HostIdentity(
            family, installation.machine_id or socket.gethostname()
        )
        scheduler = (
            SchedulerKind.WINDOWS_TASK_SCHEDULER
            if family is HostFamily.WINDOWS
            else SchedulerKind.LAUNCHD
        )
        return plan_machine_profile(
            installation,
            identity,
            paths,
            arguments.python_executable,
            __version__,
            scheduler,
            (str(installation.root),),
        )
    if command == "adoption manifest validate":
        return _read_manifest(arguments.manifest)
    if command == "adoption bundle build":
        manifest = _read_manifest(arguments.manifest)
        policy = _artifact_policy(arguments.forbid, arguments.contextos_root)
        return ExtensionBundleBuilder().build(
            manifest, arguments.payload_root, arguments.output, policy
        )
    if command == "adoption bundle verify":
        return verify_extension_bundle(
            arguments.bundle,
            _artifact_policy(arguments.forbid, arguments.contextos_root),
        )
    raise ValidationError("unsupported database-free command")


def dispatch(arguments: argparse.Namespace, database: ProjectOSDatabase) -> Any:
    command = arguments.command
    if command.startswith("looker "):
        authorization = AuthorizationService(database, arguments.owner_email)
        context = authorization.resolve(arguments.actor)
        if command == "looker cutover prepare":
            if context.role is not UserRole.OWNER:
                raise ValidationError("Owner authorization is required")
            target_value = _json_file(arguments.targets, "cutover targets")
            if not isinstance(target_value, list):
                raise ValidationError("cutover targets must be a list")
            return CutoverPreparer(database).prepare(
                CutoverPreparationRequest(
                    str(_uuid(arguments.project_id)),
                    arguments.intake_run_id,
                    arguments.reconciliation_id,
                    RefreshReceipt.from_mapping(
                        _json_file(arguments.refresh_receipt, "refresh receipt")
                    ),
                    arguments.backup_manifest,
                    arguments.legacy_root,
                    tuple(CutoverTarget.from_mapping(item) for item in target_value),
                    arguments.actor,
                    arguments.owner_email,
                    arguments.prepared_at,
                    arguments.output,
                )
            )
        if command.startswith("looker reconcile "):
            if context.role is not UserRole.OWNER:
                raise ValidationError("Owner authorization is required")
            reconciler = LookerReconciler(database)
            if command == "looker reconcile stage":
                return reconciler.stage(
                    _uuid(arguments.project_id), arguments.intake_run_id, arguments.analytic_version,
                    _json_file(arguments.legacy_snapshot, "legacy snapshot"),
                    ReconciliationPolicy.from_mapping(_json_file(arguments.policy, "reconciliation policy")), arguments.actor,
                )
            if command == "looker reconcile report":
                return reconciler.report(arguments.reconciliation_id)
            return reconciler.waive(arguments.reconciliation_id, arguments.dimension, arguments.item_key, arguments.reason, context)
        project_id = _uuid(arguments.project_id)
        if command in {"looker intake import", "looker analytics build"}:
            if context.role is not UserRole.OWNER:
                raise ValidationError("Owner authorization is required")
            if command == "looker intake import":
                return LookerImporter(database).import_archive(
                    project_id, arguments.verified_evidence, arguments.actor
                )
            return LookerAnalyticsService(database).build(
                project_id, arguments.intake_run_id
            )
        project = ProjectRepository(database).get(project_id)
        if authorization.filter_entity(context, project) is None:
            raise ValidationError("Looker analytics are unavailable")
        service = LookerAnalyticsService(database)
        if arguments.node:
            if not arguments.direction:
                raise ValidationError("Looker graph direction is required")
            return (
                service.dependencies(project_id, arguments.node)
                if arguments.direction == "dependencies"
                else service.impact(project_id, arguments.node)
            )
        if arguments.direction:
            raise ValidationError("Looker graph node is required")
        return service.summary(project_id)
    if command == "init":
        return {"database": str(database.path), "schema_version": database.schema_version()}
    if command == "doctor":
        return ProjectOSDoctor(database).check()
    if command.startswith("user "):
        users = UserRepository(database, arguments.owner_email)
        if command == "user seed-owner":
            return users.seed_owner(arguments.owner_email, arguments.display_name)
        if command == "user create":
            return users.create(
                UserCreate(
                    arguments.email,
                    arguments.display_name,
                    UserRole(arguments.role),
                    notes=arguments.notes,
                ),
                arguments.actor,
            )
        if command == "user list":
            owner = users.get_by_email(arguments.owner_email)
            if owner is None or owner.role is not UserRole.OWNER or not owner.active:
                raise ValidationError("protected Owner is not active")
            return users.list(arguments.active_only)
        if command == "user update":
            return users.update(
                _uuid(arguments.user_id),
                arguments.expected_version,
                UserPatch(
                    email=arguments.email,
                    display_name=arguments.display_name,
                    role=UserRole(arguments.role) if arguments.role else None,
                    notes=arguments.notes,
                    active=_optional_bool(arguments.active),
                ),
                arguments.actor,
            )
        if command == "user deactivate":
            return users.deactivate(
                _uuid(arguments.user_id), arguments.expected_version, arguments.actor
            )
    if command.startswith("google binding "):
        bindings = GoogleBindingRepository(database)
        if command == "google binding create":
            return bindings.create(
                GoogleBindingCreate(
                    arguments.environment,
                    arguments.spreadsheet_id,
                    arguments.display_name,
                    arguments.contract_version,
                    _uuid(arguments.credential_id),
                    gas_script_id=arguments.gas_script_id,
                    gas_deployment_id=arguments.gas_deployment_id,
                    enabled=arguments.enabled,
                    write_enabled=arguments.write_enabled,
                ),
                arguments.actor,
            )
        if command == "google binding get":
            record = bindings.get(_uuid(arguments.binding_id))
            if record is None:
                raise ValidationError("Google binding does not exist")
            return record
        if command == "google binding list":
            return bindings.list()
        if command == "google binding update":
            return bindings.update(
                _uuid(arguments.binding_id),
                arguments.expected_version,
                GoogleBindingPatch(
                    display_name=arguments.display_name,
                    contract_version=arguments.contract_version,
                    credential_id=_uuid(arguments.credential_id),
                    gas_script_id=arguments.gas_script_id,
                    gas_deployment_id=arguments.gas_deployment_id,
                    enabled=_optional_bool(arguments.enabled),
                    write_enabled=_optional_bool(arguments.write_enabled),
                ),
                arguments.actor,
            )
    if command == "google contract show":
        return WorkbookContract.current()
    if command == "google contract plan":
        return WorkbookBootstrapPlanner().plan(
            _workbook_snapshot(arguments.snapshot), WorkbookContract.current()
        )
    if command == "google preflight":
        binding = GoogleBindingRepository(database).get(_uuid(arguments.binding_id))
        if binding is None:
            raise ValidationError("Google binding does not exist")
        return _gateway(arguments).preflight(binding)
    if command.startswith("sync "):
        binding_id = _uuid(arguments.binding_id)
        if command == "sync status":
            service = GoogleSyncService(
                database,
                arguments.owner_email,
                FakeGoogleGateway.from_fixture({"write_ready": False}),
                database.path.with_suffix(".sync.lock"),
            )
            return service.status(binding_id)
        gateway = _gateway(arguments, for_write=command == "sync run")
        service = GoogleSyncService(
            database,
            arguments.owner_email,
            gateway,
            arguments.lock_path or database.path.with_suffix(".sync.lock"),
        )
        if command == "sync plan":
            return service.plan(binding_id)
        return service.run(binding_id, arguments.trigger)
    if command == "conflict list":
        owner = UserRepository(database, arguments.owner_email).get_by_email(
            arguments.owner_email
        )
        if owner is None or owner.role is not UserRole.OWNER or not owner.active:
            raise ValidationError("Owner access is required")
        return [
            dict(row)
            for row in database.connection.execute(
                "SELECT conflict_id,request_id,current_version,status,created_at,resolved_at "
                "FROM conflicts WHERE status=? ORDER BY created_at,conflict_id",
                (arguments.status,),
            )
        ]
    if command == "conflict resolve":
        binding_id = _uuid(arguments.binding_id)
        if GoogleBindingRepository(database).get(binding_id) is None:
            raise ValidationError("Google binding does not exist")
        authorization = AuthorizationService(database, arguments.owner_email)
        processor = RequestProcessor(
            database,
            binding_id,
            authorization,
            MutationRegistry(database, arguments.owner_email),
        )
        result = processor.resolve_conflict(
            _uuid(arguments.conflict_id), arguments.actor_email, arguments.strategy
        )
        if result.code is not RequestResultCode.ACCEPTED:
            raise ValidationError("Owner access is required")
        return result
    if command == "diagnostics create":
        return DiagnosticBundleService(database).create(arguments.destination)
    projects = ProjectRepository(database)
    if command == "project create":
        return projects.create(
            ProjectCreate(
                slug=arguments.slug,
                name=arguments.name,
                description=arguments.description,
                project_type=ProjectType(arguments.type),
                status=ProjectStatus(arguments.status),
                visibility=ProjectVisibility(arguments.visibility),
                context_os_registered=arguments.context_os_registered,
                context_os_project_id=arguments.context_os_project_id,
                tags=tuple(arguments.tag),
                source_key=arguments.source_key,
            ),
            arguments.actor,
        )
    if command == "project get":
        record = projects.get(_uuid(arguments.project_id))
        if record is None:
            raise ValidationError("project does not exist")
        return record
    if command == "project list":
        return projects.list(arguments.include_archived)
    if command == "project update":
        return projects.update(
            _uuid(arguments.project_id),
            arguments.expected_version,
            ProjectPatch(
                name=arguments.name,
                description=arguments.description,
                project_type=ProjectType(arguments.type) if arguments.type else None,
                status=ProjectStatus(arguments.status) if arguments.status else None,
                visibility=ProjectVisibility(arguments.visibility) if arguments.visibility else None,
                context_os_project_id=arguments.context_os_project_id,
                tags=tuple(arguments.tag) if arguments.tag is not None else None,
            ),
            arguments.actor,
        )
    if command == "project archive":
        return projects.archive(
            _uuid(arguments.project_id), arguments.expected_version, arguments.actor
        )
    if command == "location upsert":
        return LocationRepository(database).upsert(
            _uuid(arguments.project_id),
            LocationUpsert(
                machine_id=arguments.machine_id,
                location_type=arguments.location_type,
                path=arguments.path,
                repository_root=arguments.repository_root,
                drive_folder_id=arguments.drive_folder_id,
                drive_folder_url=arguments.drive_folder_url,
                environment=arguments.environment,
            ),
            arguments.actor,
        )
    if command == "resource upsert":
        return ResourceRepository(database).upsert(
            _uuid(arguments.project_id),
            ResourceUpsert(
                resource_type=arguments.resource_type,
                provider=arguments.provider,
                name=arguments.name,
                external_id=arguments.external_id,
                url=arguments.url,
                environment=arguments.environment,
                role=arguments.role,
                metadata=_mapping(arguments.metadata, "metadata"),
            ),
            arguments.actor,
        )
    if command == "deployment upsert":
        return DeploymentRepository(database).upsert(
            _uuid(arguments.project_id),
            DeploymentUpsert(
                environment=DeploymentEnvironment(arguments.environment),
                external_deployment_id=arguments.external_deployment_id,
                script_id=arguments.script_id,
                deployment_url=arguments.deployment_url,
                resource_id=_uuid(arguments.resource_id),
                active_version=arguments.active_version,
            ),
            arguments.actor,
        )
    if command == "connection upsert":
        return ConnectionRepository(database).upsert(
            ConnectionUpsert(
                connection_type=arguments.connection_type,
                implementation_method=arguments.implementation_method,
                source_project_id=_uuid(arguments.source_project_id),
                source_resource_id=_uuid(arguments.source_resource_id),
                target_project_id=_uuid(arguments.target_project_id),
                target_resource_id=_uuid(arguments.target_resource_id),
                direction=ConnectionDirection(arguments.direction),
                purpose=arguments.purpose,
                notes=arguments.notes,
            ),
            arguments.actor,
        )
    if command == "connection impact":
        return ConnectionRepository(database).impact(_uuid(arguments.resource_id))
    credentials = CredentialReferenceService(database)
    if command == "credential create":
        return credentials.create(
            CredentialReferenceCreate(
                provider=arguments.provider,
                label=arguments.label,
                credential_type=arguments.credential_type,
                purpose=arguments.purpose,
                storage_system=arguments.storage_system,
                storage_reference=arguments.storage_reference,
                owner_project_id=_uuid(arguments.owner_project_id),
                scope_description=arguments.scope_description,
                rotation_due_at=arguments.rotation_due_at,
                notes=arguments.notes,
            ),
            arguments.actor,
        )
    if command == "credential link":
        return credentials.link_usage(
            _uuid(arguments.credential_id),
            _uuid(arguments.project_id),
            _uuid(arguments.resource_id),
            arguments.purpose,
            arguments.actor,
        )
    if command == "credential impact":
        return credentials.impact(_uuid(arguments.credential_id))
    discoveries = DiscoveryService(database)
    if command == "discover contextos":
        return discoveries.run(
            ContextOSManifestAdapter(arguments.projects_dir, arguments.machine_id),
            arguments.source_run_id,
        )
    if command == "discover list":
        return discoveries.list(arguments.status)
    if command == "discover apply":
        return discoveries.apply(_uuid(arguments.finding_id), arguments.actor)
    if command == "discover reject":
        return discoveries.reject(
            _uuid(arguments.finding_id), arguments.actor, arguments.reason
        )
    backups = BackupService(database)
    if command == "backup create":
        return backups.create(arguments.destination_dir)
    if command == "backup verify":
        return backups.verify(arguments.manifest_path)
    if command == "backup restore":
        return backups.restore(
            arguments.manifest_path, arguments.target_db, arguments.replace
        )
    raise ValidationError("unsupported command")


def _envelope(
    *, command: str, ok: bool, data: Any = None, errors: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    return {
        "ok": ok,
        "command": command,
        "data": _jsonable(data),
        "errors": errors or [],
        "meta": {"schema_version": SCHEMA_VERSION},
    }


def _safe_debug_log() -> None:
    configured = os.environ.get("PROJECTOS_DEBUG_LOG")
    if not configured:
        return
    path = Path(configured).expanduser()
    frames = traceback.extract_tb(__import__("sys").exc_info()[2])
    safe = "\n".join(f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in frames)
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(safe + "\n")
    except OSError:
        pass


def _validation_message(command: str, error: ProjectOSError) -> str:
    if command.startswith("acceptance "):
        return "acceptance validation failed"
    if command == "runtime sync":
        return "runtime sync validation failed"
    if command in {
        "adoption fixture scheduler render",
        "adoption fixture activate",
        "adoption fixture deactivate",
        "adoption fixture activation-recover",
        "adoption fixture skill inspect",
    }:
        return "fixture runtime validation failed"
    return str(error)


def main(argv: Sequence[str] | None = None) -> int:
    command = "cli"
    database: ProjectOSDatabase | None = None
    exit_code = 0
    try:
        arguments = build_parser().parse_args(argv)
        command = arguments.command
        if command == "runtime sync":
            data = _run_runtime_sync(arguments)
        elif command in DATABASE_FREE_COMMANDS:
            data = dispatch_without_database(arguments)
        else:
            if command in LOOKER_DATABASE_COMMANDS and arguments.db is None:
                raise ValidationError("Looker command requires an explicit database")
            if command == "looker intake import":
                arguments.verified_evidence = verify_intake_archive(arguments.archive)
            database = ProjectOSDatabase(arguments.db or default_database_path()).initialize()
            data = dispatch(arguments, database)
        if command == "doctor" and not data.healthy:
            exit_code = 3
            payload = _envelope(
                command=command,
                ok=False,
                data=data,
                errors=[{"code": "health_check_failed", "message": "health checks failed"}],
            )
        elif command == "google preflight" and not data.ok:
            exit_code = 3
            payload = _envelope(
                command=command,
                ok=False,
                data=data,
                errors=[{"code": "preflight_failed", "message": "Google preflight failed"}],
            )
        elif command == "sync plan" and not data.ready:
            exit_code = 3
            payload = _envelope(
                command=command,
                ok=False,
                data=data,
                errors=[{"code": "preflight_failed", "message": "sync plan is blocked"}],
            )
        elif command in {"sync run", "runtime sync"} and data.status != "COMPLETE":
            exit_code = 3
            payload = _envelope(
                command=command,
                ok=False,
                data=data,
                errors=[{"code": "sync_unavailable", "message": "sync did not complete"}],
            )
        elif command == "adoption profile plan" and not data.ready:
            exit_code = 3
            payload = _envelope(
                command=command,
                ok=False,
                data=data,
                errors=[{"code": "preflight_failed", "message": "adoption profile is blocked"}],
            )
        else:
            payload = _envelope(command=command, ok=True, data=data)
    except VersionConflict as exc:
        exit_code = 2
        payload = _envelope(
            command=command,
            ok=False,
            errors=[{"code": "version_conflict", "message": str(exc)}],
        )
    except HealthError as exc:
        exit_code = 3
        payload = _envelope(
            command=command,
            ok=False,
            errors=[{"code": "health_error", "message": str(exc)}],
        )
    except (MigrationError, sqlite3.DatabaseError):
        exit_code = 3
        payload = _envelope(
            command=command,
            ok=False,
            errors=[{"code": "health_error", "message": "database health check failed"}],
        )
    except ProjectOSError as exc:
        exit_code = 2
        payload = _envelope(
            command=command,
            ok=False,
            errors=[{"code": "validation_error", "message": _validation_message(command, exc)}],
        )
    except Exception:
        exit_code = 1
        _safe_debug_log()
        payload = _envelope(
            command=command,
            ok=False,
            errors=[{"code": "internal_error", "message": "unexpected internal error"}],
        )
    finally:
        if database is not None:
            database.close()
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
