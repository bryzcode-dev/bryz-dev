from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path, PurePosixPath
from uuid import UUID

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.host import HostFamily
from projectos.adoption.profile import (
    MachineProfile,
    SchedulerKind,
    machine_profile_mapping,
)
from projectos.bindings import GoogleBindingRepository
from projectos.credentials import CredentialReferenceCreate, CredentialReferenceService
from projectos.database import ProjectOSDatabase
from projectos.errors import MigrationError, ValidationError
from projectos.google.fake_gateway import FakeGoogleGateway
from projectos.google.config import ProjectOSGoogleConfig
from projectos.google.types import GoogleBindingCreate
from projectos.runtime import RuntimeSyncCoordinator, RuntimeTrigger, runtime_sync_argv
from projectos.sync.lock import ProjectOSFileLock
from projectos.users import UserRepository


class RuntimeSyncTests(TemporaryDirectoryMixin, unittest.TestCase):
    def _write_config(
        self,
        path: Path,
        *,
        machine_id: str,
        binding_id: UUID,
        credential_id: UUID,
        google_enabled: bool = True,
        google_write_enabled: bool = True,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                (
                    'contract_version = 1',
                    f'machine_id = "{machine_id}"',
                    'environment = "DEV"',
                    f'binding_id = "{binding_id}"',
                    'spreadsheet_id = "sheet-runtime"',
                    'expected_owner_email = "owner@example.com"',
                    f'credential_reference_id = "{credential_id}"',
                    f'google_enabled = {str(google_enabled).lower()}',
                    f'google_write_enabled = {str(google_write_enabled).lower()}',
                    "",
                )
            ),
            encoding="utf-8",
        )

    def make_system(self) -> tuple[MachineProfile, Path, UUID, FakeGoogleGateway]:
        runtime_root = self.temp_path / "runtime"
        contextos_root = self.temp_path / "contextos"
        database_path = runtime_root / "projectos.db"
        config_path = runtime_root / "projectos.toml"
        database = ProjectOSDatabase(database_path).initialize()
        owner = "owner@example.com"
        UserRepository(database, owner).seed_owner(owner, "Owner")
        credential = CredentialReferenceService(database).create(
            CredentialReferenceCreate(
                "GOOGLE", "runtime", "ADC", "sync", "KEYCHAIN", "projectos/runtime"
            ),
            owner,
        )
        binding = GoogleBindingRepository(database).create(
            GoogleBindingCreate(
                "DEV",
                "sheet-runtime",
                "ProjectOS",
                1,
                credential.credential_id,
                enabled=True,
                write_enabled=True,
            ),
            owner,
        )
        database.close()
        self._write_config(
            config_path,
            machine_id="runtime-machine",
            binding_id=binding.binding_id,
            credential_id=credential.credential_id,
        )
        profile = MachineProfile(
            1,
            "58b9478e-07be-4b08-a901-45e4110c8882",
            "runtime-machine",
            HostFamily.MACOS,
            "0.1.0",
            "3.0.1",
            1,
            PurePosixPath(contextos_root),
            PurePosixPath(contextos_root / "context-os/extensions"),
            PurePosixPath(contextos_root / "skills"),
            PurePosixPath(runtime_root),
            PurePosixPath(database_path),
            PurePosixPath(config_path),
            PurePosixPath(runtime_root / "projectos.sync.lock"),
            PurePosixPath(runtime_root / "logs"),
            PurePosixPath(runtime_root / "staging"),
            PurePosixPath(sys.executable),
            (sys.executable, "-m", "projectos.cli"),
            SchedulerKind.LAUNCHD,
            "com.contextos.projectos.sync",
            "ADOPTED",
            "a" * 64,
        )
        profile_path = runtime_root / "adoption" / "machine-profile.json"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_text(
            json.dumps(machine_profile_mapping(profile), sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        gateway = FakeGoogleGateway.from_fixture(
            {
                "contract_version": 1,
                "tabs": {},
                "requests": [],
                "access_events": [],
                "write_ready": True,
            }
        )
        return profile, profile_path, binding.binding_id, gateway

    def test_open_existing_never_creates_or_migrates_database(self) -> None:
        missing = self.temp_path / "missing" / "projectos.db"
        with self.assertRaises(MigrationError):
            ProjectOSDatabase.open_existing(missing)
        self.assertFalse(missing.exists())
        self.assertFalse(missing.parent.exists())

        outdated = self.temp_path / "outdated.db"
        connection = sqlite3.connect(outdated)
        connection.executescript(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT);"
            "INSERT INTO schema_migrations VALUES(1,'0001.sql','t');"
        )
        connection.close()
        before = outdated.read_bytes()
        with self.assertRaises(MigrationError):
            ProjectOSDatabase.open_existing(outdated)
        self.assertEqual(before, outdated.read_bytes())

    def test_open_existing_read_only_does_not_create_wal_or_shm(self) -> None:
        path = self.temp_path / "readonly.db"
        ProjectOSDatabase(path).initialize().close()
        for suffix in ("-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        before = path.read_bytes()

        database = ProjectOSDatabase.open_existing(path, read_only=True)
        self.assertEqual(3, database.schema_version())
        database.close()

        self.assertEqual(before, path.read_bytes())
        self.assertFalse(Path(f"{path}-wal").exists())
        self.assertFalse(Path(f"{path}-shm").exists())

    def test_runtime_sync_requires_database_and_config_to_match_profile(self) -> None:
        profile, profile_path, binding_id, gateway = self.make_system()
        coordinator = RuntimeSyncCoordinator()

        with self.assertRaisesRegex(ValidationError, "database"):
            coordinator.run(
                profile_path,
                self.temp_path / "other.db",
                RuntimeTrigger.SCHEDULER,
                gateway,
            )

        config_path = Path(profile.config_path)
        database = ProjectOSDatabase.open_existing(Path(profile.database_path))
        credential_id = UUID(
            database.connection.execute(
                "SELECT credential_id FROM google_bindings"
            ).fetchone()[0]
        )
        database.close()
        self._write_config(
            config_path,
            machine_id="different-machine",
            binding_id=binding_id,
            credential_id=credential_id,
        )
        with self.assertRaisesRegex(ValidationError, "machine"):
            coordinator.run(
                profile_path,
                Path(profile.database_path),
                RuntimeTrigger.SCHEDULER,
                gateway,
            )

    def test_runtime_sync_requires_current_schema_and_enabled_google_writes(self) -> None:
        profile, profile_path, binding_id, gateway = self.make_system()
        database = ProjectOSDatabase.open_existing(Path(profile.database_path))
        credential_id = UUID(
            database.connection.execute("SELECT credential_id FROM google_bindings").fetchone()[0]
        )
        database.close()
        self._write_config(
            Path(profile.config_path),
            machine_id=profile.machine_id,
            binding_id=binding_id,
            credential_id=credential_id,
            google_write_enabled=False,
        )
        with self.assertRaisesRegex(ValidationError, "writes"):
            RuntimeSyncCoordinator().run(
                profile_path,
                Path(profile.database_path),
                RuntimeTrigger.SCHEDULER,
                gateway,
            )

        Path(profile.database_path).unlink()
        connection = sqlite3.connect(Path(profile.database_path))
        connection.executescript(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT);"
            "INSERT INTO schema_migrations VALUES(1,'0001.sql','t');"
        )
        connection.close()
        self._write_config(
            Path(profile.config_path),
            machine_id=profile.machine_id,
            binding_id=binding_id,
            credential_id=credential_id,
        )
        with self.assertRaises(MigrationError):
            RuntimeSyncCoordinator().run(
                profile_path,
                Path(profile.database_path),
                RuntimeTrigger.SCHEDULER,
                gateway,
            )

    def test_google_config_requires_boolean_enable_flags(self) -> None:
        _profile, profile_path, _binding_id, _gateway = self.make_system()
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        config_path = Path(profile["config_path"])
        content = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            content.replace("google_enabled = true", 'google_enabled = "false"'),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValidationError, "invalid"):
            ProjectOSGoogleConfig.load(config_path)

    def test_scheduler_and_skill_use_same_service_and_profile_lock(self) -> None:
        profile, profile_path, _binding_id, gateway = self.make_system()
        scheduler_argv = runtime_sync_argv(profile, profile_path, RuntimeTrigger.SCHEDULER)
        skill_argv = runtime_sync_argv(profile, profile_path, RuntimeTrigger.SKILL)

        self.assertEqual(scheduler_argv[:-1], skill_argv[:-1])
        self.assertEqual(("scheduler", "skill"), (scheduler_argv[-1], skill_argv[-1]))
        with ProjectOSFileLock(Path(profile.lock_path), "held", "existing-run"):
            scheduler = RuntimeSyncCoordinator().run(
                profile_path,
                Path(profile.database_path),
                RuntimeTrigger.SCHEDULER,
                gateway,
            )
            skill = RuntimeSyncCoordinator().run(
                profile_path,
                Path(profile.database_path),
                RuntimeTrigger.SKILL,
                gateway,
                wait_seconds=0,
            )
        self.assertEqual(("LOCKED", "LOCKED"), (scheduler.status, skill.status))
        self.assertEqual([], gateway.call_log)

    def test_scheduler_never_waits_and_skill_defaults_to_ten_seconds(self) -> None:
        profile, profile_path, _binding_id, gateway = self.make_system()
        clock = [0.0]
        sleeps: list[float] = []

        def monotonic() -> float:
            return clock[0]

        def sleeper(seconds: float) -> None:
            sleeps.append(seconds)
            clock[0] += seconds

        with ProjectOSFileLock(Path(profile.lock_path), "held", "existing-run"):
            scheduler = RuntimeSyncCoordinator().run(
                profile_path,
                Path(profile.database_path),
                RuntimeTrigger.SCHEDULER,
                gateway,
                monotonic=monotonic,
                sleeper=sleeper,
            )
            self.assertEqual([], sleeps)
            skill = RuntimeSyncCoordinator().run(
                profile_path,
                Path(profile.database_path),
                RuntimeTrigger.SKILL,
                gateway,
                monotonic=monotonic,
                sleeper=sleeper,
            )
        self.assertEqual(("LOCKED", "LOCKED"), (scheduler.status, skill.status))
        self.assertEqual([10.0], sleeps)

    def test_skill_wait_rejects_negative_or_above_thirty_seconds(self) -> None:
        profile, profile_path, _binding_id, gateway = self.make_system()
        for seconds in (-0.1, 30.1):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(
                ValidationError, "wait"
            ):
                RuntimeSyncCoordinator().run(
                    profile_path,
                    Path(profile.database_path),
                    RuntimeTrigger.SKILL,
                    gateway,
                    wait_seconds=seconds,
                )


if __name__ == "__main__":
    unittest.main()
