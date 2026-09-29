from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from typing import Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from projectos.adoption.contextos import (
    CONTEXTOS_EXTENSION_CONTRACT_VERSION,
    ContextOSInstallation,
)
from projectos.adoption.host import HostFamily, HostIdentity
from projectos.adoption.path_policy import HostPathPolicy
from projectos.adoption.paths import PlatformPaths
from projectos.errors import ValidationError
from projectos.validation import require_text


MACHINE_PROFILE_VERSION = 1


class SchedulerKind(str, Enum):
    LAUNCHD = "launchd"
    WINDOWS_TASK_SCHEDULER = "windows-task-scheduler"


@dataclass(frozen=True)
class ProfileCheck:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class MachineProfile:
    profile_schema_version: int
    installation_id: str
    machine_id: str
    host_family: HostFamily
    projectos_version: str
    contextos_version: str
    extension_contract_version: int
    contextos_root: PurePath
    extensions_root: PurePath
    skills_root: PurePath
    runtime_root: PurePath
    database_path: PurePath
    config_path: PurePath
    lock_path: PurePath
    log_root: PurePath
    staging_root: PurePath
    python_executable: PurePath
    projectos_entrypoint: tuple[str, ...]
    scheduler_kind: SchedulerKind
    scheduler_task_id: str
    adoption_state: str
    last_verified_manifest_hash: str | None


@dataclass(frozen=True)
class MachineProfilePlan:
    profile: MachineProfile | None
    checks: tuple[ProfileCheck, ...]
    ready: bool
    errors: tuple[str, ...]


def _scheduler_for(family: HostFamily) -> SchedulerKind:
    return (
        SchedulerKind.WINDOWS_TASK_SCHEDULER
        if family is HostFamily.WINDOWS
        else SchedulerKind.LAUNCHD
    )


def _task_id(kind: SchedulerKind) -> str:
    return (
        r"ContextOS\ProjectOS\Sync"
        if kind is SchedulerKind.WINDOWS_TASK_SCHEDULER
        else "com.contextos.projectos.sync"
    )


def plan_machine_profile(
    installation: ContextOSInstallation,
    identity: HostIdentity,
    paths: PlatformPaths,
    python_executable: str | PurePath,
    projectos_version: str,
    scheduler_kind: SchedulerKind,
    shared_roots: Sequence[str | PurePath] = (),
) -> MachineProfilePlan:
    policy = HostPathPolicy(identity.family)
    checks: list[ProfileCheck] = []
    errors: list[str] = []

    def check(name: str, ok: bool, message: str) -> None:
        checks.append(ProfileCheck(name, ok, message))
        if not ok:
            errors.append(message)

    check(
        "extension_contract",
        installation.contract.contract_version == CONTEXTOS_EXTENSION_CONTRACT_VERSION,
        "ContextOS extension contract is incompatible",
    )
    check(
        "supported_host",
        identity.family in installation.contract.supported_hosts,
        "ContextOS contract does not support host family",
    )
    check(
        "machine_identity",
        installation.machine_id in (None, identity.machine_id),
        "ContextOS machine identity does not match",
    )
    check(
        "scheduler",
        SchedulerKind(scheduler_kind) is _scheduler_for(identity.family),
        "scheduler does not match host family",
    )
    check(
        "python_executable",
        policy.is_absolute(str(python_executable)),
        "python executable must be absolute",
    )
    for name, value in (
        ("runtime", paths.runtime_root),
        ("database", paths.database_path),
        ("config", paths.config_path),
        ("lock", paths.lock_path),
        ("log", paths.log_root),
        ("staging", paths.staging_root),
    ):
        try:
            policy.assert_local_runtime(str(value), shared_roots)
        except ValidationError:
            check(name, False, f"{name} path must be local")
        else:
            check(name, True, f"{name} path is local")
    if errors:
        return MachineProfilePlan(None, tuple(checks), False, tuple(errors))

    version = require_text(projectos_version, "projectos_version")
    executable_type = type(paths.runtime_root)
    executable = executable_type(str(python_executable))
    installation_id = str(
        uuid5(NAMESPACE_URL, f"projectos:{identity.family.value}:{identity.machine_id}")
    )
    profile = MachineProfile(
        MACHINE_PROFILE_VERSION,
        installation_id,
        identity.machine_id,
        identity.family,
        version,
        installation.contract.contextos_version,
        installation.contract.contract_version,
        installation.root,
        installation.extensions_root,
        installation.skills_root,
        paths.runtime_root,
        paths.database_path,
        paths.config_path,
        paths.lock_path,
        paths.log_root,
        paths.staging_root,
        executable,
        (str(executable), "-m", "projectos.cli"),
        SchedulerKind(scheduler_kind),
        _task_id(SchedulerKind(scheduler_kind)),
        "PLANNED",
        None,
    )
    return MachineProfilePlan(profile, tuple(checks), True, ())


def machine_profile_mapping(profile: MachineProfile) -> dict[str, object]:
    if profile is None:
        raise ValidationError("machine profile is unavailable")
    value = asdict(profile)
    for key, nested in tuple(value.items()):
        if isinstance(nested, Enum):
            value[key] = nested.value
        elif isinstance(nested, PurePath):
            value[key] = str(nested)
        elif isinstance(nested, tuple):
            value[key] = list(nested)
    return value


def machine_profile_from_mapping(value: Mapping[str, object]) -> MachineProfile:
    expected = {
        "profile_schema_version",
        "installation_id",
        "machine_id",
        "host_family",
        "projectos_version",
        "contextos_version",
        "extension_contract_version",
        "contextos_root",
        "extensions_root",
        "skills_root",
        "runtime_root",
        "database_path",
        "config_path",
        "lock_path",
        "log_root",
        "staging_root",
        "python_executable",
        "projectos_entrypoint",
        "scheduler_kind",
        "scheduler_task_id",
        "adoption_state",
        "last_verified_manifest_hash",
    }
    if set(value) != expected:
        raise ValidationError("machine profile fields are invalid")
    if (
        type(value.get("profile_schema_version")) is not int
        or type(value.get("extension_contract_version")) is not int
        or value["profile_schema_version"] != MACHINE_PROFILE_VERSION
        or value["extension_contract_version"] != CONTEXTOS_EXTENSION_CONTRACT_VERSION
    ):
        raise ValidationError("machine profile version is invalid")
    string_fields = expected - {
        "profile_schema_version",
        "extension_contract_version",
        "projectos_entrypoint",
        "last_verified_manifest_hash",
    }
    if any(not isinstance(value.get(field), str) for field in string_fields):
        raise ValidationError("machine profile field type is invalid")
    entrypoint = value.get("projectos_entrypoint")
    if (
        not isinstance(entrypoint, list)
        or len(entrypoint) != 3
        or any(not isinstance(item, str) for item in entrypoint)
    ):
        raise ValidationError("machine profile entrypoint is invalid")
    try:
        family = HostFamily(value["host_family"])
        scheduler = SchedulerKind(value["scheduler_kind"])
        UUID(value["installation_id"])
    except (TypeError, ValueError) as exc:
        raise ValidationError("machine profile identity is invalid") from exc
    if scheduler is not _scheduler_for(family):
        raise ValidationError("machine profile scheduler is invalid")
    path_type = PureWindowsPath if family is HostFamily.WINDOWS else PurePosixPath
    path_fields = (
        "contextos_root",
        "extensions_root",
        "skills_root",
        "runtime_root",
        "database_path",
        "config_path",
        "lock_path",
        "log_root",
        "staging_root",
        "python_executable",
    )
    paths = {field: path_type(value[field]) for field in path_fields}
    policy = HostPathPolicy(family)
    if any(not policy.is_absolute(path) for path in paths.values()):
        raise ValidationError("machine profile path must be absolute")
    if not policy.is_within(
        paths["extensions_root"], paths["contextos_root"]
    ) or not policy.is_within(paths["skills_root"], paths["contextos_root"]):
        raise ValidationError("machine profile managed path must stay within ContextOS root")
    expected_entrypoint = [str(paths["python_executable"]), "-m", "projectos.cli"]
    if entrypoint != expected_entrypoint:
        raise ValidationError("machine profile entrypoint is invalid")
    if value["adoption_state"] not in {"PLANNED", "STAGED", "ADOPTED", "DISABLED"}:
        raise ValidationError("machine profile adoption state is invalid")
    verified_hash = value["last_verified_manifest_hash"]
    if verified_hash is not None and (
        not isinstance(verified_hash, str)
        or len(verified_hash) != 64
        or any(character not in "0123456789abcdef" for character in verified_hash)
    ):
        raise ValidationError("machine profile verified hash is invalid")
    return MachineProfile(
        MACHINE_PROFILE_VERSION,
        require_text(value["installation_id"], "installation_id"),
        require_text(value["machine_id"], "machine_id"),
        family,
        require_text(value["projectos_version"], "projectos_version"),
        require_text(value["contextos_version"], "contextos_version"),
        CONTEXTOS_EXTENSION_CONTRACT_VERSION,
        paths["contextos_root"],
        paths["extensions_root"],
        paths["skills_root"],
        paths["runtime_root"],
        paths["database_path"],
        paths["config_path"],
        paths["lock_path"],
        paths["log_root"],
        paths["staging_root"],
        paths["python_executable"],
        tuple(entrypoint),
        scheduler,
        require_text(value["scheduler_task_id"], "scheduler_task_id"),
        value["adoption_state"],
        verified_hash,
    )
