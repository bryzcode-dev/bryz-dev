from __future__ import annotations

import builtins
import os
import unittest
from pathlib import Path
from uuid import uuid4

from tests.helpers import REPO_ROOT, TemporaryDirectoryMixin

from projectos.adoption.host import HostFamily
from projectos.google.config import ProjectOSGoogleConfig
from projectos.google.contract import WorkbookContract, WorkbookSnapshot
from projectos.google.real_gateway import GoogleIntegrationError, RealGoogleGateway
from projectos.google.types import GoogleBindingRecord


def binding(**changes) -> GoogleBindingRecord:
    values = {
        "binding_id": uuid4(),
        "environment": "DEV",
        "spreadsheet_id": "sheet-id",
        "display_name": "ProjectOS",
        "contract_version": 1,
        "credential_id": uuid4(),
        "gas_script_id": "script-id",
        "gas_deployment_id": "deployment-id",
        "sharing_policy": "OWNER_ONLY",
        "enabled": True,
        "write_enabled": True,
        "status": "READY",
        "version": 1,
        "created_at": "t",
        "updated_at": "t",
        "last_preflight_at": None,
        "last_publication_revision": None,
    }
    values.update(changes)
    return GoogleBindingRecord(**values)


class FakeSheetsClient:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot or WorkbookSnapshot(1, {})
        self.calls = []

    def read_contract(self, spreadsheet_id):
        self.calls.append(("read_contract", spreadsheet_id))
        return self.snapshot

    def pull_requests(self, spreadsheet_id, checkpoint):
        return {"rows": (), "cursor": checkpoint, "historical_digest": "0" * 64}

    def pull_access_events(self, spreadsheet_id, checkpoint):
        return {"rows": (), "cursor": checkpoint, "historical_digest": "0" * 64}

    def publish_results(self, spreadsheet_id, results):
        self.calls.append(("publish_results", spreadsheet_id, len(results)))
        return {"revision_id": None, "verified": True, "row_counts": {"results": len(results)}, "hashes": {}}

    def publish_projection(self, spreadsheet_id, bundle):
        self.calls.append(("publish_projection", spreadsheet_id))
        return {"revision_id": bundle["revision_id"], "verified": True, "row_counts": {}, "hashes": {}}


class FakeDriveClient:
    def __init__(self, permissions):
        self.permissions = permissions

    def list_permissions(self, spreadsheet_id):
        return self.permissions


class RealGatewayTests(TemporaryDirectoryMixin, unittest.TestCase):
    def _write_config(self, path: Path, machine="test-machine"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'machine_id = "{machine}"\nenvironment = "DEV"\nbinding_id = "00000000-0000-0000-0000-000000000001"\n'
            'spreadsheet_id = "sheet-placeholder"\nexpected_owner_email = "owner@example.com"\n'
            'contract_version = 1\ncredential_reference_id = "00000000-0000-0000-0000-000000000002"\n'
            'google_enabled = false\ngoogle_write_enabled = false\n',
            encoding="utf-8",
        )

    def test_config_resolution_uses_argument_then_projectos_home_then_macos_default(self) -> None:
        explicit = self.temp_path / "explicit.toml"
        home = self.temp_path / "home"
        projectos_home = self.temp_path / "projectos-home"
        self._write_config(explicit, "explicit")
        self._write_config(projectos_home / "projectos.toml", "projectos-home")
        self._write_config(home / "Library/Application Support/ProjectOS/projectos.toml", "mac-default")
        environ = {"PROJECTOS_HOME": str(projectos_home), "HOME": str(home)}
        self.assertEqual("explicit", ProjectOSGoogleConfig.load(explicit, environ).machine_id)
        self.assertEqual("projectos-home", ProjectOSGoogleConfig.load(environ=environ).machine_id)
        self.assertEqual(
            "mac-default",
            ProjectOSGoogleConfig.load(
                environ={"HOME": str(home)}, family=HostFamily.MACOS, home=home
            ).machine_id,
        )

    def test_example_has_no_real_identifiers_or_absolute_home(self) -> None:
        text = (REPO_ROOT / "config/projectos.example.toml").read_text(encoding="utf-8")
        self.assertNotIn("/Users/", text)
        self.assertNotIn("owner@example.com", text)
        self.assertNotRegex(text, r"1[A-Za-z0-9_-]{30,}")
        self.assertIn("CHANGE_ME", text)

    def test_core_imports_without_google_packages(self) -> None:
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name.startswith("google"):
                raise ImportError("blocked for test")
            return original(name, *args, **kwargs)
        builtins.__import__ = guarded
        try:
            gateway = RealGoogleGateway("owner@example.com")
            self.assertIsNotNone(gateway)
        finally:
            builtins.__import__ = original

    def test_real_gateway_does_no_network_work_on_construction(self) -> None:
        calls = []
        RealGoogleGateway(
            "owner@example.com",
            credential_factory=lambda _ref: calls.append("credentials"),
            sheets_factory=lambda _credentials: calls.append("sheets"),
            drive_factory=lambda _credentials: calls.append("drive"),
        )
        self.assertEqual([], calls)

    def test_preflight_blocks_identity_contract_or_sharing_mismatch(self) -> None:
        cases = (
            ("wrong@example.com", WorkbookSnapshot(1, {}), [{"email": "owner@example.com", "role": "owner"}]),
            ("owner@example.com", WorkbookSnapshot(99, {}), [{"email": "owner@example.com", "role": "owner"}]),
            ("owner@example.com", WorkbookSnapshot(1, {}), [{"email": "owner@example.com", "role": "owner"}, {"email": "viewer@example.com", "role": "reader"}]),
        )
        for identity, snapshot, permissions in cases:
            with self.subTest(identity=identity, contract=snapshot.contract_version, permissions=permissions):
                gateway = RealGoogleGateway(
                    "owner@example.com",
                    identity_factory=lambda _credentials, value=identity: value,
                    credential_factory=lambda _ref: object(),
                    sheets_factory=lambda _credentials, value=snapshot: FakeSheetsClient(value),
                    drive_factory=lambda _credentials, value=permissions: FakeDriveClient(value),
                )
                result = gateway.preflight(binding())
                self.assertFalse(result.ok)

    def test_write_requires_all_binding_and_cli_gates(self) -> None:
        sheets = FakeSheetsClient()
        def gateway(allow_writes=False, cli_write_flag=False):
            return RealGoogleGateway(
                "owner@example.com",
                allow_writes=allow_writes,
                cli_write_flag=cli_write_flag,
                identity_factory=lambda _credentials: "owner@example.com",
                credential_factory=lambda _ref: object(),
                sheets_factory=lambda _credentials: sheets,
                drive_factory=lambda _credentials: FakeDriveClient([{"email": "owner@example.com", "role": "owner"}]),
            )
        for candidate, record in (
            (gateway(False, True), binding()),
            (gateway(True, False), binding()),
            (gateway(True, True), binding(enabled=False)),
            (gateway(True, True), binding(write_enabled=False)),
        ):
            candidate.preflight(record)
            with self.assertRaises(GoogleIntegrationError):
                candidate.publish_results(record, ())
        allowed = gateway(True, True)
        record = binding()
        self.assertTrue(allowed.preflight(record).ok)
        self.assertTrue(allowed.publish_results(record, ()).verified)


if __name__ == "__main__":
    unittest.main()
