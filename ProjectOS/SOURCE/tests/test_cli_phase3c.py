from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.helpers import TemporaryDirectoryMixin
from tests import test_activation_transaction as activation_tests
from tests import test_runtime_sync as runtime_tests

from projectos.adoption.activation_store import LocalActivationStore
from projectos.database import ProjectOSDatabase
from projectos.google.fake_gateway import FakeGoogleGateway
from projectos.sync.lock import ProjectOSFileLock
from projectos.cli import build_parser, main


class Phase3CCliTests(TemporaryDirectoryMixin, unittest.TestCase):
    manifest = activation_tests.ActivationTransactionTests.manifest
    _profile = activation_tests.ActivationTransactionTests._profile
    _database_and_config = activation_tests.ActivationTransactionTests._database_and_config
    system = activation_tests.ActivationTransactionTests.system
    activation_system = activation_tests.ActivationTransactionTests.activation_system
    _write_config = runtime_tests.RuntimeSyncTests._write_config
    make_runtime_system = runtime_tests.RuntimeSyncTests.make_system

    def invoke(self, *arguments: str):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(arguments))
        raw = stdout.getvalue()
        payload = json.loads(raw)
        self.assertEqual("", stderr.getvalue())
        self.assertEqual(1, len([line for line in raw.splitlines() if line.strip()]))
        self.assertEqual({"ok", "command", "data", "errors", "meta"}, set(payload))
        return code, payload, raw

    @staticmethod
    def gateway() -> FakeGoogleGateway:
        return FakeGoogleGateway.from_fixture(
            {
                "contract_version": 1,
                "tabs": {},
                "requests": [],
                "access_events": [],
                "write_ready": True,
            }
        )

    @staticmethod
    def target_options(system) -> tuple[str, ...]:
        return (
            "--fixture-ack",
            "FIXTURE_ONLY",
            "--contextos-root",
            str(system["target"].root),
            "--machine-profile",
            str(system["profile_path"]),
        )

    def test_runtime_sync_opens_exact_existing_profile_database_without_initialize(self) -> None:
        profile, profile_path, _binding_id, _gateway = self.make_runtime_system()
        with patch(
            "projectos.cli.RealGoogleGateway", return_value=self.gateway()
        ), patch.object(
            ProjectOSDatabase,
            "initialize",
            side_effect=AssertionError("runtime sync must not initialize"),
        ):
            code, payload, _ = self.invoke(
                "--db",
                str(profile.database_path),
                "runtime",
                "sync",
                "--machine-profile",
                str(profile_path),
                "--trigger",
                "scheduler",
            )

        self.assertEqual(0, code, payload)
        self.assertEqual("COMPLETE", payload["data"]["status"])

    def test_runtime_sync_rejects_fake_gateway_fixture_and_database_mismatch(self) -> None:
        profile, profile_path, _binding_id, _gateway = self.make_runtime_system()
        for extra in (("--gateway", "fake"), ("--fixture", "fixture.json")):
            with self.subTest(extra=extra):
                code, payload, _ = self.invoke(
                    "--db",
                    str(profile.database_path),
                    "runtime",
                    "sync",
                    "--machine-profile",
                    str(profile_path),
                    "--trigger",
                    "scheduler",
                    *extra,
                )
                self.assertEqual(2, code)
                self.assertFalse(payload["ok"])

        with patch(
            "projectos.cli.ProjectOSGoogleConfig.load",
            side_effect=AssertionError("config must not load for a database mismatch"),
        ):
            code, payload, _ = self.invoke(
                "--db",
                str(self.temp_path / "other.db"),
                "runtime",
                "sync",
                "--machine-profile",
                str(profile_path),
                "--trigger",
                "scheduler",
            )
        self.assertEqual(2, code)
        self.assertEqual("validation_error", payload["errors"][0]["code"])

        outside_profile = self.temp_path / "outside-profile.json"
        outside_profile.write_bytes(profile_path.read_bytes())
        with patch(
            "projectos.cli.ProjectOSGoogleConfig.load",
            side_effect=AssertionError("config must not load before profile validation"),
        ):
            code, payload, _ = self.invoke(
                "--db",
                str(profile.database_path),
                "runtime",
                "sync",
                "--machine-profile",
                str(outside_profile),
                "--trigger",
                "scheduler",
            )
        self.assertEqual(2, code, payload)

    def test_runtime_sync_triggers_share_one_json_contract_and_lock(self) -> None:
        profile, profile_path, _binding_id, _gateway = self.make_runtime_system()
        results = []
        with ProjectOSFileLock(Path(profile.lock_path), "held", "existing-run"), patch(
            "projectos.cli.RealGoogleGateway", return_value=self.gateway()
        ):
            for trigger in ("scheduler", "skill"):
                arguments = [
                    "--db",
                    str(profile.database_path),
                    "runtime",
                    "sync",
                    "--machine-profile",
                    str(profile_path),
                    "--trigger",
                    trigger,
                ]
                if trigger == "skill":
                    arguments.extend(("--wait-seconds", "0"))
                results.append(self.invoke(*arguments))

        for code, payload, _ in results:
            self.assertEqual(3, code)
            self.assertEqual("LOCKED", payload["data"]["status"])
            self.assertEqual("sync_unavailable", payload["errors"][0]["code"])
        self.assertEqual(set(results[0][1]), set(results[1][1]))

    def test_phase3c_fixture_commands_are_database_lazy_until_runtime_verification(self) -> None:
        system = self.activation_system("lazy")
        options = self.target_options(system)
        with patch.object(
            ProjectOSDatabase,
            "open_existing",
            side_effect=AssertionError("read-only fixture commands must be database lazy"),
        ):
            rendered = self.invoke(
                "adoption", "fixture", "scheduler", "render", *options
            )
            inspected = self.invoke(
                "adoption", "fixture", "skill", "inspect", *options
            )
        self.assertEqual(0, rendered[0], rendered[1])
        self.assertEqual(0, inspected[0], inspected[1])

    def test_scheduler_render_is_disabled_and_does_not_execute_native_command(self) -> None:
        system = self.activation_system("render")
        with patch("subprocess.run", side_effect=AssertionError("native command executed")):
            code, payload, _ = self.invoke(
                "adoption",
                "fixture",
                "scheduler",
                "render",
                *self.target_options(system),
            )
        self.assertEqual(0, code, payload)
        self.assertFalse(payload["data"]["enabled"])
        self.assertEqual(7200, payload["data"]["interval_seconds"])
        self.assertEqual("launchd", payload["data"]["scheduler_kind"])

    def test_fixture_activate_inspect_deactivate_round_trip(self) -> None:
        system = self.activation_system("round-trip")
        options = self.target_options(system)
        code, activated, _ = self.invoke(
            "adoption",
            "fixture",
            "activate",
            system["definition_transaction_id"],
            *options,
        )
        self.assertEqual(0, code, activated)
        self.assertEqual("PROVED", activated["data"]["state"])

        code, inspected, _ = self.invoke(
            "adoption", "fixture", "skill", "inspect", *options
        )
        self.assertEqual(0, code, inspected)
        self.assertIsNotNone(inspected["data"]["skill"])
        self.assertIsNone(inspected["data"]["diagnostic"])

        activation_id = activated["data"]["activation_id"]
        code, deactivated, _ = self.invoke(
            "adoption", "fixture", "deactivate", activation_id, *options
        )
        self.assertEqual(0, code, deactivated)
        self.assertEqual("DEACTIVATED", deactivated["data"]["state"])

        code, inspected, _ = self.invoke(
            "adoption", "fixture", "skill", "inspect", *options
        )
        self.assertEqual(0, code, inspected)
        self.assertEqual("REGISTRY_DISABLED", inspected["data"]["diagnostic"]["code"])

    def test_activation_failure_returns_exit_three_and_recovery_is_idempotent(self) -> None:
        system = self.activation_system("failure")
        options = self.target_options(system)
        missing = self.invoke(
            "adoption",
            "fixture",
            "activate",
            "00000000-0000-0000-0000-000000000000",
            *options,
        )
        self.assertEqual(2, missing[0], missing[1])
        (system["installed_root"] / "skills/projectos/SKILL.md").write_text(
            "changed", encoding="utf-8"
        )
        code, payload, _ = self.invoke(
            "adoption",
            "fixture",
            "activate",
            system["definition_transaction_id"],
            *options,
        )
        self.assertEqual(3, code)
        self.assertEqual("health_error", payload["errors"][0]["code"])

        activation_store = LocalActivationStore.open(system["store"])
        activation_id = next(path.name for path in activation_store.root.iterdir())
        first = self.invoke(
            "adoption", "fixture", "activation-recover", activation_id, *options
        )
        second = self.invoke(
            "adoption", "fixture", "activation-recover", activation_id, *options
        )
        self.assertEqual((0, 0), (first[0], second[0]))
        self.assertEqual(first[1]["data"], second[1]["data"])
        self.assertEqual("ROLLED_BACK", first[1]["data"]["state"])

    def test_cli_has_no_live_activate_native_runner_enable_or_force_flag(self) -> None:
        parser = build_parser()
        rejected = (
            ["adoption", "activate", "definition-id"],
            ["adoption", "fixture", "activate", "definition-id", "--native"],
            ["adoption", "fixture", "activate", "definition-id", "--runner", "native"],
            ["adoption", "fixture", "activate", "definition-id", "--enable"],
            ["adoption", "fixture", "activate", "definition-id", "--force"],
        )
        for arguments in rejected:
            with self.subTest(arguments=arguments), self.assertRaises(Exception):
                parser.parse_args(arguments)

    def test_phase3c_errors_never_echo_profile_path_email_identifier_or_secret(self) -> None:
        sensitive = self.temp_path / "owner@example.com-secret-sheet-identifier.json"
        code, payload, raw = self.invoke(
            "adoption",
            "fixture",
            "scheduler",
            "render",
            "--fixture-ack",
            "FIXTURE_ONLY",
            "--contextos-root",
            str(self.temp_path / "contextos"),
            "--machine-profile",
            str(sensitive),
        )
        self.assertEqual(2, code, payload)
        for forbidden in (str(sensitive), "owner@example.com", "secret", "identifier"):
            self.assertNotIn(forbidden, raw)

    def test_phase3a_phase3b_and_catalog_commands_remain_unchanged(self) -> None:
        parser = build_parser()
        commands = (
            ["adoption", "inspect"],
            ["adoption", "profile", "plan", "--python-executable", "/usr/bin/python3"],
            [
                "adoption", "fixture", "recover", "transaction-id",
                "--fixture-ack", "FIXTURE_ONLY",
                "--contextos-root", "/tmp/contextos",
                "--machine-profile", "/tmp/profile.json",
            ],
            ["project", "list"],
            ["google", "contract", "show"],
        )
        expected = (
            "adoption inspect",
            "adoption profile plan",
            "adoption fixture recover",
            "project list",
            "google contract show",
        )
        self.assertEqual(expected, tuple(parser.parse_args(item).command for item in commands))


if __name__ == "__main__":
    unittest.main()
