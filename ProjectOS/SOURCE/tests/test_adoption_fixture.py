from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.contextos import ContextOSLocator
from projectos.adoption.fixture import (
    FIXTURE_MARKER,
    FixtureInstallationTarget,
    assert_fixture_separation,
    issue_empty_fixture,
)
from projectos.adoption.host import HostFamily
from projectos.errors import ValidationError


class AdoptionFixtureTests(TemporaryDirectoryMixin, unittest.TestCase):
    def issue(self, name: str = "contextos-fixture"):
        runtime = self.temp_path / "runtime"
        root = self.temp_path / name
        receipt = issue_empty_fixture(
            root, runtime, HostFamily.MACOS, "fixture-mac", "3.0.1"
        )
        installation = ContextOSLocator(
            HostFamily.MACOS, {}, self.temp_path / "home"
        ).inspect(root)
        return runtime, root, receipt, installation

    @staticmethod
    def inventory(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_issue_fixture_requires_new_or_empty_root_and_writes_local_receipt(self) -> None:
        runtime, root, receipt, _installation = self.issue()

        marker = json.loads((root / FIXTURE_MARKER).read_text(encoding="utf-8"))
        receipt_path = (
            runtime
            / "adoption"
            / "fixture-receipts"
            / f"{receipt.fixture_id}.json"
        )
        persisted = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {"format": "projectos-contextos-fixture-v1", "fixture_id": receipt.fixture_id},
            marker,
        )
        self.assertEqual(str(root.resolve()), persisted["root"])
        self.assertEqual("macos", persisted["host_family"])
        self.assertEqual(receipt.marker_sha256, persisted["marker_sha256"])
        self.assertTrue((root / "context-os/config/extension-contract.json").is_file())
        self.assertTrue((root / "context-os-machine.json").is_file())

        occupied = self.temp_path / "occupied"
        occupied.mkdir()
        (occupied / "unrelated.txt").write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "empty"):
            issue_empty_fixture(
                occupied, runtime, HostFamily.MACOS, "fixture-mac", "3.0.1"
            )
        self.assertEqual("preserve", (occupied / "unrelated.txt").read_text())

    def test_fixture_target_requires_matching_receipt_marker_and_acknowledgement(self) -> None:
        runtime, root, receipt, installation = self.issue()

        with self.assertRaisesRegex(ValidationError, "acknowledgement"):
            FixtureInstallationTarget.open(installation, runtime, "wrong")

        target = FixtureInstallationTarget.open(installation, runtime, "FIXTURE_ONLY")
        self.assertEqual(receipt.fixture_id, target.fixture_id)
        self.assertEqual(root.resolve(), target.root)
        self.assertEqual(root.resolve() / "context-os/extensions", target.extensions_root)
        self.assertEqual(root.resolve() / "skills", target.skills_root)
        self.assertEqual(
            root.resolve() / "context-os/extensions/registry.json",
            target.registry_path,
        )
        with self.assertRaisesRegex(ValidationError, "within fixture"):
            target.assert_managed_path(target.root / ".." / "escape")

        marker = json.loads((root / FIXTURE_MARKER).read_text(encoding="utf-8"))
        marker["extra"] = True
        (root / FIXTURE_MARKER).write_text(json.dumps(marker), encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "marker"):
            FixtureInstallationTarget.open(installation, runtime, "FIXTURE_ONLY")

    def test_copied_marker_cannot_authorize_an_existing_contextos_root(self) -> None:
        runtime, root, _receipt, _installation = self.issue("authorized")
        copied = self.temp_path / "copied"
        copied.mkdir()
        for relative in (
            FIXTURE_MARKER,
            "context-os/config/extension-contract.json",
            "context-os-machine.json",
        ):
            destination = copied / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((root / relative).read_bytes())
        (copied / "context-os/extensions").mkdir(parents=True)
        (copied / "skills").mkdir()
        installation = ContextOSLocator(
            HostFamily.MACOS, {}, self.temp_path / "home"
        ).inspect(copied)

        with self.assertRaisesRegex(ValidationError, "receipt"):
            FixtureInstallationTarget.open(installation, runtime, "FIXTURE_ONLY")

    def test_fixture_target_rejects_runtime_overlap_in_both_directions(self) -> None:
        runtime = self.temp_path / "runtime"
        with self.assertRaisesRegex(ValidationError, "separate"):
            issue_empty_fixture(
                runtime / "fixture", runtime, HostFamily.MACOS, "fixture-mac"
            )
        fixture = self.temp_path / "fixture-parent"
        with self.assertRaisesRegex(ValidationError, "separate"):
            issue_empty_fixture(
                fixture, fixture / "runtime", HostFamily.MACOS, "fixture-mac"
            )

    def test_fixture_target_rejects_symlinked_root_or_managed_ancestors(self) -> None:
        actual = self.temp_path / "actual"
        actual.mkdir()
        linked = self.temp_path / "linked"
        linked.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(ValidationError, "symlink"):
            issue_empty_fixture(
                linked, self.temp_path / "runtime", HostFamily.MACOS, "fixture-mac"
            )

        runtime, root, _receipt, installation = self.issue("ancestor")
        extensions = root / "context-os/extensions"
        extensions.rmdir()
        external = self.temp_path / "external"
        external.mkdir()
        extensions.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValidationError, "symlink"):
            FixtureInstallationTarget.open(installation, runtime, "FIXTURE_ONLY")

    def test_fixture_target_uses_component_aware_windows_drive_and_unc_rules(self) -> None:
        assert_fixture_separation(
            HostFamily.WINDOWS,
            r"C:\ContextOS-Fixture",
            r"C:\Users\fixture\AppData\Local\ProjectOS",
        )
        assert_fixture_separation(
            HostFamily.WINDOWS,
            r"\\server\share\ContextOS",
            r"C:\Users\fixture\AppData\Local\ProjectOS",
        )
        with self.assertRaisesRegex(ValidationError, "separate"):
            assert_fixture_separation(
                HostFamily.WINDOWS,
                r"C:\Fixtures\ContextOS",
                r"c:\fixtures\contextos\runtime",
            )

    def test_fixture_target_open_is_read_only(self) -> None:
        runtime, root, _receipt, installation = self.issue("readonly")
        before_root = self.inventory(root)
        before_runtime = self.inventory(runtime)

        FixtureInstallationTarget.open(installation, runtime, "FIXTURE_ONLY")

        self.assertEqual(before_root, self.inventory(root))
        self.assertEqual(before_runtime, self.inventory(runtime))


if __name__ == "__main__":
    unittest.main()
