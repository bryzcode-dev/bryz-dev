from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from tests.helpers import TemporaryDirectoryMixin

from projectos.acceptance.authority import ACCEPTANCE_ACKNOWLEDGEMENT, AcceptanceTarget, HostSession
from projectos.acceptance.model import ACCEPTANCE_TASKS
from projectos.acceptance.profile import AcceptanceProfile, acceptance_machine_profile
from projectos.acceptance.store import LocalAcceptanceStore
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.errors import ValidationError


class AcceptanceProfileTests(TemporaryDirectoryMixin, unittest.TestCase):
    def machine_profile(self, runtime: Path) -> MachineProfile:
        contextos = PurePosixPath(str((self.temp_path / "fixture").resolve()))
        local = PurePosixPath(str(runtime.resolve()))
        python = PurePosixPath("/usr/bin/python3")
        return MachineProfile(
            1,
            "99999999-9999-9999-9999-999999999999",
            "fixture-machine",
            HostFamily.MACOS,
            "0.1.0",
            "3.0.1",
            1,
            contextos,
            contextos / "context-os/extensions",
            contextos / "skills",
            local,
            local / "projectos.db",
            local / "projectos.toml",
            local / "projectos.sync.lock",
            local / "logs",
            local / "staging",
            python,
            (str(python), "-m", "projectos.cli"),
            SchedulerKind.LAUNCHD,
            "com.contextos.projectos.sync",
            "PLANNED",
            None,
        )

    def target(self) -> AcceptanceTarget:
        root = self.temp_path / "acceptance-authority"
        runtime = self.temp_path / "runtime"
        session = HostSession(HostFamily.MACOS, "a" * 64, False, True)
        with patch("projectos.acceptance.authority.detect_host_session", return_value=session):
            AcceptanceTarget.issue(root, runtime, HostFamily.MACOS)
        return AcceptanceTarget.open(root, runtime, ACCEPTANCE_ACKNOWLEDGEMENT, session)

    def acceptance_profile(self) -> AcceptanceProfile:
        target = self.target()
        return AcceptanceProfile.from_machine_profile(
            self.machine_profile(target.runtime_root),
            target,
            source_revision="1" * 40,
            release_sha256="2" * 64,
            wheel_sha256="3" * 64,
            definition_transaction_id="definition-01",
            activation_id="activation-01",
            max_probe_seconds=90,
        )

    def test_acceptance_profile_uses_only_acceptance_entrypoint_and_task_identifier(self) -> None:
        target = self.target()
        production = self.machine_profile(target.runtime_root)
        acceptance = acceptance_machine_profile(production)
        changed = {
            field
            for field in production.__dataclass_fields__
            if getattr(production, field) != getattr(acceptance, field)
        }
        self.assertEqual({"projectos_entrypoint", "scheduler_task_id"}, changed)
        self.assertEqual(("/usr/bin/python3", "-m", "projectos.acceptance_probe"), acceptance.projectos_entrypoint)
        self.assertEqual(ACCEPTANCE_TASKS["macos"], acceptance.scheduler_task_id)

    def test_acceptance_profile_rejects_production_task_and_path_escape(self) -> None:
        target = self.target()
        production = self.machine_profile(target.runtime_root)
        with self.assertRaisesRegex(ValidationError, "acceptance task"):
            AcceptanceProfile.from_machine_profile(
                replace(production, projectos_entrypoint=("/usr/bin/python3", "-m", "projectos.acceptance_probe")),
                target,
                source_revision="1" * 40,
                release_sha256="2" * 64,
                wheel_sha256="3" * 64,
                definition_transaction_id="definition-01",
                activation_id="activation-01",
            )
        escaped = replace(production, database_path=PurePosixPath("/tmp/escaped.db"))
        with self.assertRaisesRegex(ValidationError, "runtime"):
            AcceptanceProfile.from_machine_profile(
                escaped,
                target,
                source_revision="1" * 40,
                release_sha256="2" * 64,
                wheel_sha256="3" * 64,
                definition_transaction_id="definition-01",
                activation_id="activation-01",
            )

    def test_acceptance_store_is_local_exclusive_and_never_initializes_database(self) -> None:
        profile = self.acceptance_profile()
        store = LocalAcceptanceStore.open(profile.target, profile)
        database = Path(str(profile.machine_profile.database_path))
        self.assertFalse(database.exists())
        with store.exclusive():
            with self.assertRaisesRegex(ValidationError, "in use"):
                with LocalAcceptanceStore.open(profile.target, profile).exclusive():
                    self.fail("second store lock unexpectedly acquired")
        self.assertFalse(database.exists())
        path = store.save_profile(profile)
        self.assertEqual(profile.canonical_bytes(), path.read_bytes())
        self.assertEqual(profile, store.load_profile())

    def test_acceptance_metadata_contains_no_private_identifiers_or_secrets(self) -> None:
        profile = self.acceptance_profile()
        target = profile.target
        marker = (target.root / ".projectos-acceptance-v1").read_text(encoding="utf-8")
        receipt = (
            target.runtime_root / "acceptance/receipts" / f"{target.receipt_id}.json"
        ).read_text(encoding="utf-8")
        for searchable in (marker, receipt):
            self.assertNotIn(str(self.temp_path), searchable)
            self.assertNotIn("fixture-machine", searchable)
            self.assertNotIn("password", searchable.casefold())
            self.assertNotIn("token", searchable.casefold())
            self.assertEqual(
                json.dumps(json.loads(searchable), sort_keys=True, separators=(",", ":")) + "\n",
                searchable,
            )


if __name__ == "__main__":
    unittest.main()
