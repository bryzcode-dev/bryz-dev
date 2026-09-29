from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.host import HostFamily
from projectos.adoption.manifest import (
    CommandDeclaration,
    CompatibilityDeclaration,
    ExtensionManifest,
    SkillDeclaration,
)
from projectos.cli import main


class Phase3ACliTests(TemporaryDirectoryMixin, unittest.TestCase):
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

    def contextos_root(self, *, contract_version: int = 1) -> Path:
        root = self.temp_path / f"contextos-{contract_version}"
        config = root / "context-os" / "config"
        config.mkdir(parents=True)
        (config / "context-os.json").write_text("{}\n", encoding="utf-8")
        (config / "extension-contract.json").write_text(
            json.dumps(
                {
                    "contract_version": contract_version,
                    "contextos_version": "3.0.1",
                    "extensions_root": "context-os/extensions",
                    "skills_root": "skills",
                    "runtime_root_template": "~/Library/Application Support/ClaudeContextOS/home",
                    "supported_hosts": ["macos", "windows"],
                }
            ),
            encoding="utf-8",
        )
        (root / "context-os-machine.json").write_text(
            json.dumps({"machine_id": "test-workstation"}), encoding="utf-8"
        )
        return root

    def manifest(self) -> ExtensionManifest:
        return ExtensionManifest(
            1,
            1,
            "projectos",
            "0.1.0",
            "2026-09-27T00:00:00Z",
            CompatibilityDeclaration(
                "3.0.1", "4.0.0", 1, (HostFamily.MACOS, HostFamily.WINDOWS)
            ),
            SkillDeclaration(
                "projectos", "0.1.0", "skills/projectos/SKILL.md", ("sync", "status")
            ),
            (
                CommandDeclaration("health", ("projectos", "doctor"), False),
                CommandDeclaration("sync", ("projectos", "sync", "run"), True),
            ),
            2,
            "CURRENT",
            "machine-profile.json",
            True,
            (),
            "STAGED",
            (),
        )

    def write_manifest_and_payload(self) -> tuple[Path, Path]:
        manifest_path = self.temp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(self.manifest().to_mapping()), encoding="utf-8"
        )
        payload = self.temp_path / "payload"
        skill = payload / "skills" / "projectos" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# ProjectOS\n", encoding="utf-8")
        (payload / "machine-profile.json").write_text("{}\n", encoding="utf-8")
        (payload / "projectos.whl").write_bytes(b"wheel-placeholder")
        return manifest_path, payload

    def test_adoption_inspect_returns_one_json_document_without_creating_database(self) -> None:
        root = self.contextos_root()
        database = self.temp_path / "must-not-exist.db"

        code, payload, _ = self.invoke(
            "--db",
            str(database),
            "adoption",
            "inspect",
            "--host-family",
            "macos",
            "--contextos-root",
            str(root),
        )

        self.assertEqual(0, code)
        self.assertTrue(payload["ok"])
        self.assertEqual("test-workstation", payload["data"]["machine_id"])
        self.assertFalse(database.exists())

    def test_adoption_profile_plan_is_read_only_and_reports_ready(self) -> None:
        root = self.contextos_root()
        projectos_home = self.temp_path / "local-projectos"
        before = tuple(self.temp_path.rglob("*"))

        code, payload, _ = self.invoke(
            "adoption",
            "profile",
            "plan",
            "--host-family",
            "macos",
            "--contextos-root",
            str(root),
            "--projectos-home",
            str(projectos_home),
            "--python-executable",
            "/usr/bin/python3",
        )

        self.assertEqual(0, code)
        self.assertTrue(payload["data"]["ready"])
        self.assertEqual("PLANNED", payload["data"]["profile"]["adoption_state"])
        self.assertEqual(before, tuple(self.temp_path.rglob("*")))

    def test_adoption_profile_plan_reports_incompatible_contract_without_traceback(self) -> None:
        root = self.contextos_root(contract_version=2)

        code, payload, raw = self.invoke(
            "adoption",
            "profile",
            "plan",
            "--host-family",
            "macos",
            "--contextos-root",
            str(root),
            "--projectos-home",
            str(self.temp_path / "local"),
            "--python-executable",
            "/usr/bin/python3",
        )

        self.assertEqual(2, code)
        self.assertFalse(payload["ok"])
        self.assertNotIn("Traceback", raw)
        self.assertNotIn(str(self.temp_path), payload["errors"][0]["message"])

    def test_manifest_validate_rejects_secret_without_echoing_it(self) -> None:
        secret = "super-secret-value"
        mapping = self.manifest().to_mapping()
        mapping["api_token"] = secret
        path = self.temp_path / "unsafe-manifest.json"
        path.write_text(json.dumps(mapping), encoding="utf-8")

        code, payload, raw = self.invoke("adoption", "manifest", "validate", str(path))

        self.assertEqual(2, code)
        self.assertFalse(payload["ok"])
        self.assertNotIn(secret, raw)

    def test_bundle_build_writes_only_requested_staging_output(self) -> None:
        manifest, payload_root = self.write_manifest_and_payload()
        output = self.temp_path / "staging" / "projectos-extension.zip"
        before_payload = {
            str(path.relative_to(payload_root)): path.read_bytes()
            for path in payload_root.rglob("*")
            if path.is_file()
        }

        code, response, _ = self.invoke(
            "adoption",
            "bundle",
            "build",
            str(manifest),
            str(payload_root),
            str(output),
            "--forbid",
            "developer-workstation",
        )

        self.assertEqual(0, code)
        self.assertTrue(output.is_file())
        self.assertEqual(str(output), response["data"]["path"])
        self.assertEqual(
            before_payload,
            {
                str(path.relative_to(payload_root)): path.read_bytes()
                for path in payload_root.rglob("*")
                if path.is_file()
            },
        )

    def test_bundle_verify_is_read_only(self) -> None:
        manifest, payload_root = self.write_manifest_and_payload()
        output = self.temp_path / "bundle.zip"
        build_code, _, _ = self.invoke(
            "adoption", "bundle", "build", str(manifest), str(payload_root), str(output)
        )
        before = output.read_bytes()

        code, response, _ = self.invoke("adoption", "bundle", "verify", str(output))

        self.assertEqual((0, 0), (build_code, code))
        self.assertTrue(response["data"]["ok"])
        self.assertEqual(before, output.read_bytes())

    def test_bundle_build_rejects_resolved_contextos_root(self) -> None:
        manifest, payload_root = self.write_manifest_and_payload()
        contextos_root = self.temp_path / "contextos-root"
        (payload_root / "unsafe.txt").write_text(str(contextos_root), encoding="utf-8")

        code, response, raw = self.invoke(
            "adoption",
            "bundle",
            "build",
            str(manifest),
            str(payload_root),
            str(self.temp_path / "unsafe.zip"),
            "--contextos-root",
            str(contextos_root),
        )

        self.assertEqual(2, code)
        self.assertFalse(response["ok"])
        self.assertEqual("adoption bundle build", response["command"])
        self.assertEqual(
            "bundle payload contains a forbidden host identifier",
            response["errors"][0]["message"],
        )
        self.assertNotIn(str(contextos_root), response["errors"][0]["message"])
        self.assertFalse((self.temp_path / "unsafe.zip").exists())

    def test_adoption_commands_never_instantiate_projectos_database(self) -> None:
        root = self.contextos_root()

        with patch(
            "projectos.cli.ProjectOSDatabase",
            side_effect=AssertionError("database must not initialize"),
        ):
            code, payload, _ = self.invoke(
                "adoption",
                "inspect",
                "--host-family",
                "macos",
                "--contextos-root",
                str(root),
            )

        self.assertEqual(0, code)
        self.assertTrue(payload["ok"])

    def test_adoption_commands_do_not_resolve_database_default(self) -> None:
        root = self.contextos_root()

        with patch(
            "projectos.cli.default_database_path",
            side_effect=AssertionError("database default must remain lazy"),
        ):
            code, payload, _ = self.invoke(
                "adoption",
                "inspect",
                "--host-family",
                "macos",
                "--contextos-root",
                str(root),
            )

        self.assertEqual(0, code)
        self.assertTrue(payload["ok"])

    def test_existing_database_commands_still_initialize_and_dispatch(self) -> None:
        database = self.temp_path / "existing.db"

        code, payload, _ = self.invoke("--db", str(database), "init")

        self.assertEqual(0, code)
        self.assertTrue(payload["ok"])
        self.assertTrue(database.is_file())


if __name__ == "__main__":
    unittest.main()
