from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO_ROOT

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from projectos.acceptance.authority import HostSession
from projectos.adoption.host import HostFamily
from projectos.errors import ValidationError


class LookerIntakeTests(unittest.TestCase):
    def mapping(self, repository: str, output: str) -> dict:
        return {
            "schema_version": 1,
            "source_machine_id": "source-machine-01",
            "host_family": "macos",
            "repository_root": repository,
            "output_root": output,
            "git": {"remote": "origin", "primary_branch": "main", "ownership_context": "owner-managed"},
            "master_sheet": {"spreadsheet_id": "sheet-safe-id", "url": "https://docs.google.com/spreadsheets/d/sheet-safe-id", "tabs": ["Models", "Views"]},
            "gas": {"script_id": "script-safe-id", "deployment_ids": ["deploy-safe-id"], "source_root": repository},
            "sync_script_paths": [f"{repository}/sync.py"],
            "scheduler_definition_paths": [f"{repository}/scheduler.txt"],
            "validation_commands": [{"command_id": "tests", "executable": "python3", "arguments": ["-m", "unittest"], "working_directory": repository, "timeout_seconds": 30, "expected_exit_codes": [0], "parser": "TEST_SUMMARY"}],
            "credential_references": [{"provider": "google", "label": "looker-sheet", "storage_system": "keychain", "storage_reference": "projectos/looker-sheet"}],
        }

    def test_intake_is_canonical_strict_and_cross_platform(self) -> None:
        from projectos.looker.model import LookerIntake

        value = self.mapping("/opt/looker", "/opt/evidence")
        intake = LookerIntake.from_mapping(value)
        self.assertEqual(value, json.loads(intake.canonical_bytes()))
        with self.assertRaisesRegex(ValidationError, "fields"):
            LookerIntake.from_mapping({**value, "unknown": True})
        windows = self.mapping(r"C:\Looker", r"D:\Evidence")
        windows["host_family"] = "windows"
        windows["gas"]["source_root"] = r"C:\Looker"
        windows["sync_script_paths"] = [r"C:\Looker\sync.ps1"]
        windows["scheduler_definition_paths"] = [r"C:\Looker\task.xml"]
        windows["validation_commands"][0]["working_directory"] = r"C:\Looker"
        self.assertEqual("windows", LookerIntake.from_mapping(windows).host_family.value)

    def test_repository_and_output_are_separate_non_symlink_roots(self) -> None:
        from projectos.looker.model import LookerIntake
        from projectos.looker.policy import validate_collector_environment

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"; repository.mkdir()
            output = root / "output"; output.mkdir()
            session = HostSession(HostFamily.MACOS, "1" * 64, False, True)
            paths = validate_collector_environment(LookerIntake.from_mapping(self.mapping(str(repository), str(output))), session)
            self.assertEqual(repository.resolve(), paths.repository_root)
            nested = repository / "evidence"; nested.mkdir()
            with self.assertRaisesRegex(ValidationError, "separate"):
                validate_collector_environment(LookerIntake.from_mapping(self.mapping(str(repository), str(nested))), session)
            link = root / "link"; link.symlink_to(repository, target_is_directory=True)
            with self.assertRaisesRegex(ValidationError, "symlink"):
                validate_collector_environment(LookerIntake.from_mapping(self.mapping(str(link), str(output))), session)

    def test_standard_user_session_is_required(self) -> None:
        from projectos.looker.model import LookerIntake
        from projectos.looker.policy import validate_collector_environment

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); repository = root / "repo"; repository.mkdir(); output = root / "out"; output.mkdir()
            intake = LookerIntake.from_mapping(self.mapping(str(repository), str(output)))
            with self.assertRaisesRegex(ValidationError, "standard-user"):
                validate_collector_environment(intake, HostSession(HostFamily.MACOS, "2" * 64, True, False))
            with self.assertRaisesRegex(ValidationError, "host"):
                validate_collector_environment(intake, HostSession(HostFamily.WINDOWS, "2" * 64, False, True))

    def test_command_envelope_rejects_shell_syntax_secret_arguments_and_unknown_parser(self) -> None:
        from projectos.looker.model import LookerIntake

        base = self.mapping("/opt/looker", "/opt/evidence")
        for arguments, parser in [(["-m", "tests", "|", "tee"], "TEST_SUMMARY"), (["--token", "value"], "STATUS_ONLY"), (["ok"], "UNKNOWN")]:
            value = json.loads(json.dumps(base)); value["validation_commands"][0]["arguments"] = arguments; value["validation_commands"][0]["parser"] = parser
            with self.assertRaises(ValidationError):
                LookerIntake.from_mapping(value)

    def test_credential_declarations_are_safe_references_only(self) -> None:
        from projectos.looker.model import LookerIntake

        value = self.mapping("/opt/looker", "/opt/evidence")
        value["credential_references"][0]["token"] = "secret-value"
        with self.assertRaisesRegex(ValidationError, "fields|secret"):
            LookerIntake.from_mapping(value)


if __name__ == "__main__":
    unittest.main()
