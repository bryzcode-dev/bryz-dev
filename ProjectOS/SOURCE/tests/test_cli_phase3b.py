from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.bundle import ArtifactPolicy, ExtensionBundleBuilder
from projectos.adoption.host import HostFamily
from projectos.adoption.manifest import (
    CommandDeclaration,
    CompatibilityDeclaration,
    ExtensionManifest,
    SkillDeclaration,
)
from projectos.adoption.profile import (
    MachineProfile,
    SchedulerKind,
    machine_profile_mapping,
)
from projectos.adoption.registry import ExtensionRegistry
from projectos.cli import build_parser, main


class Phase3BCliTests(TemporaryDirectoryMixin, unittest.TestCase):
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

    def profile(self, suffix: str = "default") -> MachineProfile:
        runtime = (self.temp_path / f"runtime-{suffix}").resolve()
        contextos = (self.temp_path / f"contextos-{suffix}").resolve()
        python = Path("/usr/bin/python3")
        return MachineProfile(
            1,
            f"88888888-8888-8888-8888-{abs(hash(suffix)) % 10**12:012d}",
            f"fixture-{suffix}",
            HostFamily.MACOS,
            "0.1.0",
            "3.0.1",
            1,
            contextos,
            contextos / "context-os/extensions",
            contextos / "skills",
            runtime,
            runtime / "projectos.db",
            runtime / "projectos.toml",
            runtime / "projectos.sync.lock",
            runtime / "logs",
            runtime / "staging",
            python,
            (str(python), "-m", "projectos.cli"),
            SchedulerKind.LAUNCHD,
            "com.contextos.projectos.sync",
            "PLANNED",
            None,
        )

    def manifest(self, version: str = "0.1.0") -> ExtensionManifest:
        return ExtensionManifest(
            1,
            1,
            "projectos",
            version,
            "2026-09-27T00:00:00Z",
            CompatibilityDeclaration(
                "3.0.1", "4.0.0", 1, (HostFamily.MACOS, HostFamily.WINDOWS)
            ),
            SkillDeclaration(
                "projectos", version, "skills/projectos/SKILL.md", ("sync",)
            ),
            (CommandDeclaration("health", ("projectos", "doctor"), False),),
            2,
            "CURRENT",
            "machine-profile.json",
            True,
            (),
            "STAGED",
            (),
        )

    def bundle(self, suffix: str, version: str = "0.1.0") -> Path:
        payload = self.temp_path / f"payload-{suffix}"
        skill = payload / "skills/projectos/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# ProjectOS fixture skill\n", encoding="utf-8")
        (payload / "projectos.whl").write_bytes(f"wheel-{version}".encode())
        output = self.temp_path / f"bundle-{suffix}.zip"
        ExtensionBundleBuilder().build(
            self.manifest(version), payload, output, ArtifactPolicy(())
        )
        return output

    def initialize(self, suffix: str = "default") -> tuple[MachineProfile, Path]:
        profile = self.profile(suffix)
        code, payload, _ = self.invoke(
            "adoption",
            "fixture",
            "init",
            str(profile.contextos_root),
            "--runtime-root",
            str(profile.runtime_root),
            "--host-family",
            "macos",
            "--machine-id",
            profile.machine_id,
        )
        self.assertEqual(0, code, payload)
        profile_path = self.temp_path / f"machine-profile-{suffix}.json"
        profile_path.write_text(
            json.dumps(machine_profile_mapping(profile)), encoding="utf-8"
        )
        return profile, profile_path

    @staticmethod
    def target_options(profile: MachineProfile, profile_path: Path) -> tuple[str, ...]:
        return (
            "--fixture-ack",
            "FIXTURE_ONLY",
            "--contextos-root",
            str(profile.contextos_root),
            "--machine-profile",
            str(profile_path),
        )

    def test_phase3b_commands_are_database_free_and_one_json_envelope(self) -> None:
        profile, profile_path = self.initialize("database-free")
        bundle = self.bundle("database-free")
        database = self.temp_path / "must-not-exist.db"

        with patch(
            "projectos.cli.ProjectOSDatabase",
            side_effect=AssertionError("database must not initialize"),
        ):
            code, payload, _ = self.invoke(
                "--db",
                str(database),
                "adoption",
                "fixture",
                "preflight",
                str(bundle),
                *self.target_options(profile, profile_path),
            )

        self.assertEqual(0, code)
        self.assertEqual("PREFLIGHTED", payload["data"]["state"])
        self.assertFalse(database.exists())

    def test_fixture_init_refuses_nonempty_or_symlinked_root(self) -> None:
        runtime = self.temp_path / "runtime-init-refusal"
        nonempty = self.temp_path / "nonempty"
        nonempty.mkdir()
        (nonempty / "keep.txt").write_text("keep", encoding="utf-8")
        code, payload, _ = self.invoke(
            "adoption", "fixture", "init", str(nonempty),
            "--runtime-root", str(runtime), "--host-family", "macos",
            "--machine-id", "fixture-refusal",
        )
        self.assertEqual(2, code)
        self.assertFalse(payload["ok"])
        external = self.temp_path / "external"
        external.mkdir()
        linked = self.temp_path / "linked"
        linked.symlink_to(external, target_is_directory=True)
        code, _, _ = self.invoke(
            "adoption", "fixture", "init", str(linked),
            "--runtime-root", str(runtime), "--host-family", "macos",
            "--machine-id", "fixture-refusal",
        )
        self.assertEqual(2, code)

    def test_cli_has_no_live_adopt_or_force_flag(self) -> None:
        parser = build_parser()
        with self.assertRaises(Exception):
            parser.parse_args(["adoption", "adopt", "bundle.zip"])
        with self.assertRaises(Exception):
            parser.parse_args(
                ["adoption", "fixture", "adopt", "bundle.zip", "--force"]
            )

    def test_fixture_acknowledgement_marker_and_local_receipt_are_all_required(self) -> None:
        profile, profile_path = self.initialize("three-factors")
        bundle = self.bundle("three-factors")
        base = (
            "adoption", "fixture", "preflight", str(bundle),
            "--contextos-root", str(profile.contextos_root),
            "--machine-profile", str(profile_path),
        )
        code, _, _ = self.invoke(*base, "--fixture-ack", "wrong")
        self.assertEqual(2, code)
        marker = Path(profile.contextos_root) / ".projectos-contextos-fixture-v1"
        saved_marker = marker.read_bytes()
        marker.unlink()
        code, _, _ = self.invoke(*base, "--fixture-ack", "FIXTURE_ONLY")
        self.assertEqual(2, code)
        marker.write_bytes(saved_marker)
        receipt = next((Path(profile.runtime_root) / "adoption/fixture-receipts").iterdir())
        receipt.unlink()
        code, _, _ = self.invoke(*base, "--fixture-ack", "FIXTURE_ONLY")
        self.assertEqual(2, code)

    def test_preflight_and_failed_stage_do_not_mutate_target(self) -> None:
        profile, profile_path = self.initialize("no-mutation")
        bundle = self.bundle("no-mutation")
        before = self.target_bytes(Path(profile.contextos_root))
        code, _, _ = self.invoke(
            "adoption", "fixture", "preflight", str(bundle),
            *self.target_options(profile, profile_path),
        )
        self.assertEqual(0, code)
        self.assertEqual(before, self.target_bytes(Path(profile.contextos_root)))
        corrupt = self.temp_path / "corrupt.zip"
        corrupt.write_bytes(b"not-a-zip")
        code, payload, _ = self.invoke(
            "adoption", "fixture", "adopt", str(corrupt),
            *self.target_options(profile, profile_path),
        )
        self.assertEqual(2, code)
        self.assertFalse(payload["ok"])
        self.assertEqual(before, self.target_bytes(Path(profile.contextos_root)))

    def test_fixture_adopt_upgrade_rollback_uninstall_round_trip(self) -> None:
        profile, profile_path = self.initialize("round-trip")
        options = self.target_options(profile, profile_path)
        code, adopted, _ = self.invoke(
            "adoption", "fixture", "adopt", str(self.bundle("rt-v1", "0.1.0")),
            *options,
        )
        self.assertEqual(0, code)
        self.assertEqual("ADOPTED", adopted["data"]["state"])
        original = Path(profile.contextos_root) / "context-os/extensions/registry.json"
        v1_registry = original.read_bytes()
        code, upgraded, _ = self.invoke(
            "adoption", "fixture", "upgrade", str(self.bundle("rt-v2", "0.2.0")),
            *options,
        )
        self.assertEqual(0, code)
        self.assertEqual("ADOPTED", upgraded["data"]["state"])
        code, rolled_back, _ = self.invoke(
            "adoption", "fixture", "rollback", upgraded["data"]["transaction_id"],
            *options,
        )
        self.assertEqual(0, code)
        self.assertEqual("ROLLED_BACK", rolled_back["data"]["state"])
        self.assertEqual(v1_registry, original.read_bytes())
        code, uninstalled, _ = self.invoke(
            "adoption", "fixture", "uninstall", *options
        )
        self.assertEqual(0, code)
        self.assertEqual("UNINSTALLED", uninstalled["data"]["state"])
        self.assertIsNone(ExtensionRegistry.load(original).projectos_entry())

    def test_recover_is_idempotent_after_each_injected_failure(self) -> None:
        boundaries = (
            "after_preflight", "after_snapshot", "after_stage", "after_verify",
            "after_version_copy", "before_registry_replace", "after_registry_replace",
        )
        for index, boundary in enumerate(boundaries):
            with self.subTest(boundary=boundary):
                profile, profile_path = self.initialize(f"recover-{index}")
                options = self.target_options(profile, profile_path)
                with patch(
                    "projectos.adoption.transaction._boundary",
                    side_effect=lambda name, selected=boundary: (
                        (_ for _ in ()).throw(RuntimeError(name))
                        if name == selected else None
                    ),
                ):
                    code, payload, _ = self.invoke(
                        "adoption", "fixture", "adopt",
                        str(self.bundle(f"recover-{index}")), *options,
                    )
                self.assertEqual(3, code, payload)
                transaction_id = next(
                    path.name for path in
                    (Path(profile.runtime_root) / "adoption/transactions").iterdir()
                )
                for _ in range(2):
                    code, recovered, _ = self.invoke(
                        "adoption", "fixture", "recover", transaction_id, *options
                    )
                    self.assertEqual(0, code)
                    self.assertEqual("ROLLED_BACK", recovered["data"]["state"])

    def test_cli_never_echoes_paths_marked_sensitive_or_secret_input(self) -> None:
        profile, profile_path = self.initialize("redaction")
        secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
        unsafe = self.temp_path / "unsafe.zip"
        unsafe.write_bytes(secret.encode())

        code, payload, raw = self.invoke(
            "adoption", "fixture", "adopt", str(unsafe),
            *self.target_options(profile, profile_path), "--forbid", secret,
        )

        self.assertEqual(2, code)
        self.assertFalse(payload["ok"])
        self.assertNotIn(secret, raw)
        self.assertNotIn(str(profile.contextos_root), raw)

    def test_nonfixture_existing_commands_remain_unchanged(self) -> None:
        manifest = self.temp_path / "manifest.json"
        manifest.write_text(json.dumps(self.manifest().to_mapping()), encoding="utf-8")

        code, payload, _ = self.invoke(
            "adoption", "manifest", "validate", str(manifest)
        )

        self.assertEqual(0, code)
        self.assertEqual("adoption manifest validate", payload["command"])
        self.assertEqual("projectos", payload["data"]["extension_id"])

    @staticmethod
    def target_bytes(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
