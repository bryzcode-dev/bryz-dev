from __future__ import annotations

import json
import unittest
from pathlib import Path, PureWindowsPath

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.contextos import (
    ContextOSCompatibilityError,
    ContextOSLocator,
)
from projectos.adoption.host import HostFamily


class ContextOSAdoptionTests(TemporaryDirectoryMixin, unittest.TestCase):
    def make_root(self, name: str = "contextos", **contract_changes) -> Path:
        root = self.temp_path / name
        config = root / "context-os" / "config"
        config.mkdir(parents=True)
        (config / "context-os.json").write_text("{}\n", encoding="utf-8")
        contract = {
            "contract_version": 1,
            "contextos_version": "3.0.1",
            "extensions_root": "context-os/extensions",
            "skills_root": "skills",
            "runtime_root_template": "~/Library/Application Support/ClaudeContextOS/home",
            "supported_hosts": ["macos", "windows"],
        }
        contract.update(contract_changes)
        (config / "extension-contract.json").write_text(
            json.dumps(contract), encoding="utf-8"
        )
        return root

    def snapshot(self, root: Path) -> tuple[tuple[str, int], ...]:
        return tuple(
            (str(path.relative_to(root)), path.stat().st_size)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        )

    def test_explicit_root_precedes_environment_and_default(self) -> None:
        explicit = self.make_root("explicit")
        locator = ContextOSLocator(
            HostFamily.MACOS,
            {"CONTEXTOS_ROOT": str(self.temp_path / "environment")},
            self.temp_path / "home",
        )

        self.assertEqual((str(explicit.resolve()),), locator.candidates(explicit))

    def test_environment_root_precedes_platform_default(self) -> None:
        environment = self.make_root("environment")
        locator = ContextOSLocator(
            HostFamily.MACOS,
            {"CONTEXTOS_ROOT": str(environment)},
            self.temp_path / "home",
        )

        self.assertEqual((str(environment.resolve()),), locator.candidates())

    def test_windows_default_uses_userprofile_dot_claude(self) -> None:
        locator = ContextOSLocator(
            HostFamily.WINDOWS,
            {"USERPROFILE": r"C:\Users\Example"},
            PureWindowsPath(r"C:\Users\Example"),
        )

        self.assertEqual(
            (str(PureWindowsPath(r"C:\Users\Example") / ".claude"),),
            locator.candidates(),
        )

    def test_locator_reads_compatible_contract_without_writes(self) -> None:
        root = self.make_root()
        before = self.snapshot(root)

        installation = ContextOSLocator(
            HostFamily.MACOS, {}, self.temp_path / "home"
        ).inspect(root)

        self.assertEqual(root.resolve(), installation.root)
        self.assertEqual(1, installation.contract.contract_version)
        self.assertEqual("3.0.1", installation.contract.contextos_version)
        self.assertEqual(root.resolve() / "context-os/extensions", installation.extensions_root)
        self.assertEqual(root.resolve() / "skills", installation.skills_root)
        self.assertIsNone(installation.machine_id)
        self.assertEqual(before, self.snapshot(root))

    def test_missing_contract_fails_without_fallback_mutation(self) -> None:
        root = self.temp_path / "missing"
        root.mkdir()
        before = tuple(root.iterdir())

        with self.assertRaisesRegex(ContextOSCompatibilityError, "extension contract is missing"):
            ContextOSLocator(HostFamily.MACOS, {}, self.temp_path / "home").inspect(root)

        self.assertEqual(before, tuple(root.iterdir()))

    def test_malformed_contract_is_bounded_validation_error(self) -> None:
        root = self.make_root()
        contract = root / "context-os/config/extension-contract.json"
        contract.write_text("{not-json", encoding="utf-8")

        with self.assertRaisesRegex(ContextOSCompatibilityError, "extension contract is invalid"):
            ContextOSLocator(HostFamily.MACOS, {}, self.temp_path / "home").inspect(root)

    def test_newer_contract_version_fails_closed(self) -> None:
        root = self.make_root(contract_version=2)

        with self.assertRaisesRegex(ContextOSCompatibilityError, "contract version"):
            ContextOSLocator(HostFamily.MACOS, {}, self.temp_path / "home").inspect(root)

    def test_unsupported_host_fails_closed(self) -> None:
        root = self.make_root(supported_hosts=["windows"])

        with self.assertRaisesRegex(ContextOSCompatibilityError, "does not support macos"):
            ContextOSLocator(HostFamily.MACOS, {}, self.temp_path / "home").inspect(root)

    def test_extensions_and_skills_must_stay_within_contextos_root(self) -> None:
        for field, value in (
            ("extensions_root", "../extensions"),
            ("skills_root", "/tmp/skills"),
        ):
            with self.subTest(field=field):
                root = self.make_root(field, **{field: value})
                with self.assertRaisesRegex(ContextOSCompatibilityError, field):
                    ContextOSLocator(
                        HostFamily.MACOS, {}, self.temp_path / "home"
                    ).inspect(root)

    def test_machine_profile_identifier_is_optional_but_validated_when_present(self) -> None:
        root = self.make_root("profile")
        profile = root / "context-os-machine.json"
        profile.write_text(json.dumps({"machine_id": "workstation-01"}), encoding="utf-8")

        installation = ContextOSLocator(
            HostFamily.MACOS, {}, self.temp_path / "home"
        ).inspect(root)
        self.assertEqual("workstation-01", installation.machine_id)

        profile.write_text(json.dumps({"machine_id": "  "}), encoding="utf-8")
        with self.assertRaisesRegex(ContextOSCompatibilityError, "machine profile is invalid"):
            ContextOSLocator(HostFamily.MACOS, {}, self.temp_path / "home").inspect(root)


if __name__ == "__main__":
    unittest.main()
