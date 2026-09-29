from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tests.helpers import REPO_ROOT

from projectos import acceptance_host, cli
from projectos.acceptance.commands import HostPreflightPlan
from projectos.acceptance.journal import HostAcceptanceState
from projectos.acceptance.transaction import HostAcceptanceResult
from projectos.adoption.host import HostFamily


class Phase3DCliTests(unittest.TestCase):
    def invoke(self, function, argv):
        output = io.StringIO()
        with redirect_stdout(output):
            code = function(argv)
        lines = output.getvalue().splitlines()
        self.assertEqual(1, len(lines), lines)
        return code, json.loads(lines[0])

    def test_ordinary_cli_exposes_only_build_and_read_only_acceptance_commands(self) -> None:
        parser = cli.build_parser()
        commands = (
            ["acceptance", "package", "build", "--wheel", "a.whl", "--extension-bundle", "projectos-extension.zip", "--source-revision", "1" * 40, "--created-at", "2026-09-27T12:00:00Z", "--output", "a.zip"],
            ["acceptance", "package", "verify", "a.zip"],
            ["acceptance", "evidence", "verify", "e.zip", "--manifest", "manifest.json"],
            ["acceptance", "reconcile", "--manifest", "manifest.json"],
        )
        self.assertEqual(
            ["acceptance package build", "acceptance package verify", "acceptance evidence verify", "acceptance reconcile"],
            [parser.parse_args(argv).command for argv in commands],
        )

    def test_ordinary_cli_has_no_native_run_runner_force_or_production_task_option(self) -> None:
        parser = cli.build_parser()
        for argv in (
            ["acceptance", "run"], ["acceptance", "native"],
            ["acceptance", "package", "verify", "a.zip", "--force"],
            ["acceptance", "package", "verify", "a.zip", "--task-id", "com.contextos.projectos.sync"],
        ):
            with self.subTest(argv=argv), self.assertRaises(Exception):
                parser.parse_args(argv)

    def test_host_module_requires_exact_ack_receipts_manifest_profile_and_evidence_root(self) -> None:
        private = "/private/Users/example/acceptance"
        code, payload = self.invoke(
            acceptance_host.main,
            ["preflight", "--acceptance-root", private, "--runtime-root", "/tmp/runtime", "--fixture-root", "/tmp/fixture", "--machine-profile", "/tmp/profile.json", "--package", "/tmp/package.zip", "--evidence-root", "/tmp/evidence", "--acceptance-ack", "wrong", "--fixture-ack", "wrong"],
        )
        self.assertEqual(2, code)
        self.assertFalse(payload["ok"])
        self.assertNotIn(private, json.dumps(payload))

    def test_host_preflight_is_read_only_and_returns_planned_native_actions(self) -> None:
        plan = HostPreflightPlan(
            HostFamily.MACOS,
            "8" * 64,
            (("launchctl", "print", "gui/501/com.contextos.projectos.acceptance.sync"),),
            True,
        )
        with patch("projectos.acceptance_host.plan_host_preflight", return_value=plan) as preflight:
            code, payload = self.invoke(acceptance_host.main, [
                "preflight", "--acceptance-root", "/a", "--runtime-root", "/r",
                "--fixture-root", "/f", "--machine-profile", "/p", "--package", "/z",
                "--evidence-root", "/e", "--acceptance-ack", "CLEAN_HOST_NATIVE_ACCEPTANCE",
                "--fixture-ack", "FIXTURE_ONLY",
            ])
        self.assertEqual(0, code)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["data"]["read_only"])
        self.assertEqual(1, preflight.call_count)

    def test_prepare_emits_one_redacted_json_envelope_without_native_execution(self) -> None:
        prepared = {"preparation_id": "1" * 36, "support_state": "SIMULATED"}
        with patch("projectos.acceptance_host.prepare_host", return_value=prepared) as prepare:
            code, payload = self.invoke(acceptance_host.main, [
                "prepare", "--acceptance-root", "/a", "--runtime-root", "/r",
                "--fixture-root", "/f", "--machine-profile", "/p", "--package", "/z",
                "--evidence-root", "/e", "--acceptance-ack", "CLEAN_HOST_NATIVE_ACCEPTANCE",
                "--fixture-ack", "FIXTURE_ONLY",
            ])
        self.assertEqual(0, code)
        self.assertTrue(payload["ok"])
        self.assertEqual(1, prepare.call_count)

    def test_host_run_is_unreachable_through_projectos_cli(self) -> None:
        with self.assertRaises(Exception):
            cli.build_parser().parse_args(["acceptance", "host", "run"])

    def test_ordinary_cli_still_cannot_reach_prepare_run_or_recover(self) -> None:
        parser = cli.build_parser()
        for command in ("prepare", "run", "recover"):
            with self.subTest(command=command), self.assertRaises(Exception):
                parser.parse_args(["acceptance", command])

    def test_run_emits_run_id_after_first_journal_and_maps_terminal_exit_codes(self) -> None:
        result = HostAcceptanceResult(
            "run-01", HostAcceptanceState.EVIDENCE_SEALED, (), True, ()
        )
        arguments = [
            "run", "--acceptance-root", "/a", "--runtime-root", "/r",
            "--fixture-root", "/f", "--machine-profile", "/p", "--package", "/z",
            "--evidence-root", "/e", "--acceptance-ack", "CLEAN_HOST_NATIVE_ACCEPTANCE",
            "--fixture-ack", "FIXTURE_ONLY",
        ]
        with patch("projectos.acceptance_host.run_prepared_acceptance", return_value=result):
            code, payload = self.invoke(acceptance_host.main, arguments)
        self.assertEqual(0, code)
        self.assertEqual("run-01", payload["data"]["run_id"])

        recovered = replace(result, state=HostAcceptanceState.FAILED)
        with patch("projectos.acceptance_host.run_prepared_acceptance", return_value=recovered):
            code, payload = self.invoke(acceptance_host.main, arguments)
        self.assertEqual(3, code)
        self.assertEqual("run-01", payload["data"]["run_id"])

    def test_phase3d_errors_are_one_json_envelope_and_never_echo_private_values(self) -> None:
        private = "/Users/private-person/package.zip"
        code, payload = self.invoke(cli.main, ["acceptance", "package", "verify", private])
        self.assertEqual(2, code)
        self.assertEqual("validation_error", payload["errors"][0]["code"])
        self.assertNotIn(private, json.dumps(payload))

    def test_prior_cli_contracts_remain_unchanged(self) -> None:
        parsed = cli.build_parser().parse_args(["adoption", "fixture", "skill", "inspect", "--fixture-ack", "FIXTURE_ONLY", "--contextos-root", "/fixture", "--machine-profile", "/profile"])
        self.assertEqual("adoption fixture skill inspect", parsed.command)
        runtime = cli.build_parser().parse_args(["--db", "/db", "runtime", "sync", "--machine-profile", "/profile", "--trigger", "scheduler"])
        self.assertEqual("runtime sync", runtime.command)


if __name__ == "__main__":
    unittest.main()
