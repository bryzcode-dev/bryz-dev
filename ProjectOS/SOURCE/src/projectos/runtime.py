from __future__ import annotations

import json
import time
from enum import StrEnum
from pathlib import Path

from projectos.adoption.fixture import assert_fixture_separation
from projectos.adoption.host import detect_host_family
from projectos.adoption.path_policy import HostPathPolicy
from projectos.adoption.profile import MachineProfile, machine_profile_from_mapping
from projectos.bindings import GoogleBindingRepository
from projectos.database import ProjectOSDatabase
from projectos.errors import ValidationError
from projectos.google.config import ProjectOSGoogleConfig
from projectos.google.gateway import GoogleGateway
from projectos.sync.service import GoogleSyncService, SyncRunResult


class RuntimeTrigger(StrEnum):
    SCHEDULER = "scheduler"
    SKILL = "skill"


def runtime_sync_argv(
    profile: MachineProfile,
    profile_path: Path,
    trigger: RuntimeTrigger,
) -> tuple[str, ...]:
    selected = RuntimeTrigger(trigger)
    return (
        *profile.projectos_entrypoint,
        "--db",
        str(profile.database_path),
        "runtime",
        "sync",
        "--machine-profile",
        str(profile_path),
        "--trigger",
        selected.value,
    )


def load_runtime_profile(path: Path) -> MachineProfile:
    profile_path = Path(path)
    if not profile_path.is_file() or profile_path.is_symlink():
        raise ValidationError("machine profile is unavailable or invalid")
    try:
        value = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("machine profile is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValidationError("machine profile is unavailable or invalid")
    profile = machine_profile_from_mapping(value)
    if profile.host_family is not detect_host_family():
        raise ValidationError("machine profile host does not match runtime host")
    policy = HostPathPolicy(profile.host_family)
    assert_fixture_separation(
        profile.host_family, profile.contextos_root, profile.runtime_root
    )
    if not policy.is_within(str(profile_path.absolute()), profile.runtime_root):
        raise ValidationError("machine profile path must stay within local runtime")
    for local_path in (
        profile.database_path,
        profile.config_path,
        profile.lock_path,
        profile.log_root,
        profile.staging_root,
    ):
        if policy.is_within(local_path, profile.contextos_root):
            raise ValidationError("runtime path must remain outside ContextOS root")
    return profile


class RuntimeSyncCoordinator:
    def run(
        self,
        profile_path: Path,
        database_path: Path,
        trigger: RuntimeTrigger,
        gateway: GoogleGateway,
        *,
        wait_seconds: float | None = None,
        monotonic=time.monotonic,
        sleeper=time.sleep,
    ) -> SyncRunResult:
        selected_trigger = RuntimeTrigger(trigger)
        profile = load_runtime_profile(Path(profile_path))
        explicit_database = Path(database_path)
        configured_database = Path(str(profile.database_path))
        if (
            explicit_database.is_symlink()
            or explicit_database.resolve() != configured_database.resolve()
        ):
            raise ValidationError("database does not match machine profile")
        if wait_seconds is None:
            selected_wait = 0.0 if selected_trigger is RuntimeTrigger.SCHEDULER else 10.0
        else:
            selected_wait = wait_seconds
        if (
            isinstance(selected_wait, bool)
            or not isinstance(selected_wait, (int, float))
            or not 0 <= selected_wait <= 30
        ):
            raise ValidationError("sync lock wait must be between zero and thirty seconds")
        if selected_trigger is RuntimeTrigger.SCHEDULER and selected_wait != 0:
            raise ValidationError("scheduler sync cannot wait for the lock")

        config = ProjectOSGoogleConfig.load(
            Path(str(profile.config_path)), family=profile.host_family
        )
        if Path(config.path).resolve() != Path(str(profile.config_path)).resolve():
            raise ValidationError("Google configuration does not match machine profile")
        if config.machine_id != profile.machine_id:
            raise ValidationError("Google configuration machine does not match profile")
        if not config.google_enabled or not config.google_write_enabled:
            raise ValidationError("Google configuration writes are disabled")

        database = ProjectOSDatabase.open_existing(configured_database)
        try:
            binding = GoogleBindingRepository(database).get(config.binding_id)
            if binding is None:
                raise ValidationError("configured Google binding is unavailable")
            if (
                binding.environment != config.environment
                or binding.spreadsheet_id != config.spreadsheet_id
                or binding.contract_version != config.contract_version
                or binding.credential_id != config.credential_reference_id
            ):
                raise ValidationError("Google configuration does not match binding")
            service = GoogleSyncService(
                database,
                config.expected_owner_email,
                gateway,
                Path(str(profile.lock_path)),
            )
            return service.run(
                config.binding_id,
                selected_trigger.value,
                wait_seconds=float(selected_wait),
                monotonic=monotonic,
                sleeper=sleeper,
            )
        finally:
            database.close()
