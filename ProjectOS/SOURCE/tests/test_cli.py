from __future__ import annotations

import gc
import io
import json
import sqlite3
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from tests.helpers import REPO_ROOT, TemporaryDirectoryMixin

from projectos.cli import main
from projectos.database import ProjectOSDatabase


class CliTests(TemporaryDirectoryMixin, unittest.TestCase):
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
        self.assertIn("schema_version", payload["meta"])
        return code, payload, raw

    def create_project(self):
        code, payload, _ = self.invoke(
            "project",
            "create",
            "--slug",
            "cli-project",
            "--name",
            "CLI Project",
            "--type",
            "LOCAL",
            "--visibility",
            "PRIVATE",
            "--actor",
            "owner",
        )
        self.assertEqual(0, code)
        return payload["data"]

    def test_success_is_single_json_document_and_exit_zero(self) -> None:
        code, payload, _ = self.invoke("init")

        self.assertEqual(0, code)
        self.assertTrue(payload["ok"])
        self.assertEqual("init", payload["command"])
        self.assertEqual([], payload["errors"])

    def test_help_uses_argparse_normal_exit_without_internal_error(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"])

        self.assertEqual(0, raised.exception.code)
        self.assertIn("usage: projectos", stdout.getvalue())
        self.assertNotIn("internal_error", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_validation_error_is_json_and_exit_two(self) -> None:
        code, payload, _ = self.invoke(
            "project",
            "create",
            "--slug",
            "Bad Slug",
            "--name",
            "Bad",
            "--type",
            "LOCAL",
            "--visibility",
            "PUBLIC",
            "--actor",
            "owner",
        )

        self.assertEqual(2, code)
        self.assertFalse(payload["ok"])
        self.assertEqual("validation_error", payload["errors"][0]["code"])

    def test_version_conflict_is_json_and_exit_two(self) -> None:
        project = self.create_project()

        code, payload, _ = self.invoke(
            "project",
            "update",
            project["project_id"],
            "--expected-version",
            "99",
            "--name",
            "Stale Update",
            "--actor",
            "owner",
        )

        self.assertEqual(2, code)
        self.assertEqual("version_conflict", payload["errors"][0]["code"])

    def test_doctor_failure_is_json_and_exit_three(self) -> None:
        database = ProjectOSDatabase(self.db_path).initialize()
        database.connection.execute("PRAGMA foreign_keys=OFF")
        database.connection.execute(
            "INSERT INTO project_locations "
            "(location_id,project_id,machine_id,location_type,created_at,updated_at) "
            "VALUES('bad','missing','mac','LOCAL','now','now')"
        )
        database.close()

        code, payload, _ = self.invoke("doctor")

        self.assertEqual(3, code)
        self.assertFalse(payload["ok"])
        self.assertIn("foreign_key_violation", payload["data"]["checks"])

    def test_doctor_corrupt_database_is_health_failure_not_internal_error(self) -> None:
        self.db_path.write_bytes(b"not a sqlite database")

        code, payload, raw = self.invoke("doctor")

        self.assertEqual(3, code)
        self.assertEqual("health_error", payload["errors"][0]["code"])
        self.assertNotIn("sqlite", raw.lower())

    def test_internal_error_is_redacted_json_and_exit_one(self) -> None:
        with patch("projectos.cli.dispatch", side_effect=RuntimeError("api_token=do-not-print")):
            code, payload, raw = self.invoke("init")

        self.assertEqual(1, code)
        self.assertEqual("internal_error", payload["errors"][0]["code"])
        self.assertNotIn("do-not-print", raw)

    def test_repeated_init_and_discovery_are_idempotent(self) -> None:
        first_init, _, _ = self.invoke("init")
        second_init, _, _ = self.invoke("init")
        projects_dir = self.temp_path / "projects"
        manifest_dir = projects_dir / "context-os"
        manifest_dir.mkdir(parents=True)
        manifest_dir.joinpath("project.json").write_text(
            (REPO_ROOT / "tests/fixtures/contextos-project.json").read_text()
        )
        first_code, first, _ = self.invoke(
            "discover", "contextos", "--projects-dir", str(projects_dir),
            "--machine-id", "mac", "--source-run-id", "cli-scan-1"
        )
        second_code, second, _ = self.invoke(
            "discover", "contextos", "--projects-dir", str(projects_dir),
            "--machine-id", "mac", "--source-run-id", "cli-scan-2"
        )

        self.assertEqual((0, 0, 0, 0), (first_init, second_init, first_code, second_code))
        self.assertEqual(1, first["data"]["created_count"])
        self.assertEqual(1, second["data"]["existing_count"])

    def test_cli_never_emits_secret_input(self) -> None:
        secret = "-----BEGIN PRIVATE KEY----- super-secret"

        code, payload, raw = self.invoke(
            "credential", "create", "--provider", "TEST", "--label", "unsafe",
            "--credential-type", "API", "--purpose", "test", "--storage-system", "ENV",
            "--storage-reference", secret, "--actor", "owner"
        )

        self.assertEqual(2, code)
        self.assertFalse(payload["ok"])
        self.assertNotIn("super-secret", raw)
        self.assertNotIn(secret, raw)

        parser_secret = "super-secret-invalid-choice"
        _, _, parser_raw = self.invoke(
            "project", "create", "--slug", "unsafe", "--name", "Unsafe",
            "--type", parser_secret, "--visibility", "PUBLIC", "--actor", "owner"
        )
        self.assertNotIn(parser_secret, parser_raw)


if __name__ == "__main__":
    unittest.main()
