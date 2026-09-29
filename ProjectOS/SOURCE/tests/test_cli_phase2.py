from __future__ import annotations

import gc
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.helpers import TemporaryDirectoryMixin

from projectos.cli import main
from projectos.sync.lock import ProjectOSFileLock


class Phase2CliTests(TemporaryDirectoryMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db_path = self.temp_path / "projectos.db"

    def invoke(self, *arguments: str):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--db", str(self.db_path), *arguments])
            gc.collect()
        raw = stdout.getvalue()
        payload = json.loads(raw)
        self.assertEqual("", stderr.getvalue())
        self.assertEqual(1, len([line for line in raw.splitlines() if line.strip()]))
        self.assertEqual({"ok", "command", "data", "errors", "meta"}, set(payload))
        return code, payload, raw

    def seed(self):
        code, owner, _ = self.invoke(
            "user", "seed-owner", "--owner-email", "owner@example.com",
            "--display-name", "Owner"
        )
        self.assertEqual(0, code)
        code, admin, _ = self.invoke(
            "user", "create", "--owner-email", "owner@example.com", "--email", "admin@example.com",
            "--display-name", "Admin", "--role", "ADMIN", "--actor", "owner@example.com"
        )
        self.assertEqual(0, code)
        code, credential, _ = self.invoke(
            "credential", "create", "--provider", "GOOGLE", "--label", "sync",
            "--credential-type", "ADC", "--purpose", "sync", "--storage-system", "KEYCHAIN",
            "--storage-reference", "projectos/google", "--actor", "owner@example.com"
        )
        self.assertEqual(0, code)
        code, binding, _ = self.invoke(
            "google", "binding", "create", "--environment", "DEV", "--spreadsheet-id", "sheet-id",
            "--display-name", "ProjectOS", "--contract-version", "1", "--credential-id",
            credential["data"]["credential_id"], "--enabled", "--write-enabled", "--actor", "owner@example.com"
        )
        self.assertEqual(0, code)
        return owner["data"], admin["data"], binding["data"]

    def fixture(self, name="fixture.json", contract_version=1) -> Path:
        path = self.temp_path / name
        path.write_text(json.dumps({
            "contract_version": contract_version, "tabs": {}, "requests": [],
            "access_events": [], "write_ready": True
        }), encoding="utf-8")
        return path

    def test_phase2_commands_keep_single_json_envelope(self) -> None:
        self.seed()
        for command in (
            ("user", "list", "--owner-email", "owner@example.com"),
            ("google", "contract", "show"),
            ("diagnostics", "create", str(self.temp_path / "diagnostics")),
        ):
            code, payload, _raw = self.invoke(*command)
            self.assertEqual(0, code)
            self.assertTrue(payload["ok"])

    def test_user_and_binding_validation_exit_two(self) -> None:
        code, payload, _ = self.invoke(
            "user", "seed-owner", "--owner-email", "not-an-email", "--display-name", "Owner"
        )
        self.assertEqual(2, code)
        self.assertEqual("validation_error", payload["errors"][0]["code"])
        self.seed()
        code, payload, _ = self.invoke(
            "google", "binding", "create", "--environment", "DEV", "--spreadsheet-id", "",
            "--display-name", "Broken", "--contract-version", "1", "--credential-id",
            "00000000-0000-0000-0000-000000000001", "--actor", "owner@example.com"
        )
        self.assertEqual(2, code)
        self.assertFalse(payload["ok"])

    def test_sync_lock_and_preflight_failure_exit_three(self) -> None:
        _owner, _admin, binding = self.seed()
        fixture = self.fixture()
        lock = self.temp_path / "sync.lock"
        with ProjectOSFileLock(lock, "test", "held"):
            code, payload, _ = self.invoke(
                "sync", "run", binding["binding_id"], "--owner-email", "owner@example.com",
                "--gateway", "fake", "--fixture", str(fixture), "--lock-path", str(lock)
            )
        self.assertEqual(3, code)
        self.assertEqual("LOCKED", payload["data"]["status"])
        drifted = self.fixture("drifted.json", 99)
        code, payload, _ = self.invoke(
            "sync", "run", binding["binding_id"], "--owner-email", "owner@example.com",
            "--gateway", "fake", "--fixture", str(drifted), "--lock-path", str(lock)
        )
        self.assertEqual(3, code)
        self.assertEqual("PREFLIGHT_FAILED", payload["data"]["status"])

    def test_google_write_requires_explicit_gateway_and_flag(self) -> None:
        _owner, _admin, binding = self.seed()
        code, payload, _ = self.invoke(
            "sync", "run", binding["binding_id"], "--owner-email", "owner@example.com",
            "--gateway", "google"
        )
        self.assertEqual(2, code)
        self.assertIn("explicit", payload["errors"][0]["message"].lower())

    def test_fake_sync_end_to_end_is_idempotent(self) -> None:
        _owner, _admin, binding = self.seed()
        fixture = self.fixture()
        arguments = (
            "sync", "run", binding["binding_id"], "--owner-email", "owner@example.com",
            "--gateway", "fake", "--fixture", str(fixture)
        )
        first, first_payload, _ = self.invoke(*arguments)
        second, second_payload, _ = self.invoke(*arguments)
        self.assertEqual((0, 0), (first, second))
        self.assertEqual("COMPLETE", first_payload["data"]["status"])
        self.assertEqual("COMPLETE", second_payload["data"]["status"])

    def test_conflict_resolution_is_owner_only(self) -> None:
        self.seed()
        code, payload, _ = self.invoke(
            "conflict", "resolve", "00000000-0000-0000-0000-000000000001",
            "--binding-id", "00000000-0000-0000-0000-000000000002",
            "--owner-email", "owner@example.com", "--actor-email", "admin@example.com",
            "--strategy", "KEEP_CANONICAL"
        )
        self.assertEqual(2, code)
        self.assertFalse(payload["ok"])

    def test_diagnostics_response_contains_manifest_not_private_data(self) -> None:
        self.seed()
        self.invoke(
            "project", "create", "--slug", "hidden", "--name", "Hidden Project", "--type", "LOCAL",
            "--visibility", "PRIVATE", "--actor", "owner@example.com"
        )
        code, payload, raw = self.invoke("diagnostics", "create", str(self.temp_path / "diag"))
        self.assertEqual(0, code)
        self.assertIn("manifest_path", payload["data"])
        self.assertNotIn("Hidden Project", raw)
        self.assertNotIn("owner@example.com", raw)

    def test_cli_parser_never_echoes_google_or_user_input(self) -> None:
        secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
        code, payload, raw = self.invoke(
            "user", "create", "--owner-email", "owner@example.com", "--email", secret,
            "--display-name", "Unsafe", "--role", "NOPE", "--actor", "owner@example.com"
        )
        self.assertEqual(2, code)
        self.assertNotIn(secret, raw)
        self.assertEqual("validation_error", payload["errors"][0]["code"])


if __name__ == "__main__":
    unittest.main()
