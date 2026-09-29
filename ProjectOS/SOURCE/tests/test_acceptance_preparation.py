from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from tests.helpers import TemporaryDirectoryMixin
from tests.test_acceptance_package import AcceptancePackageTests

from projectos.acceptance.authority import HostSession
from projectos.acceptance.preparation import (
    AcceptancePreparationRequest,
    AcceptancePreparer,
)
from projectos.adoption.fixture import issue_empty_fixture
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind, machine_profile_mapping
from projectos.errors import ValidationError


class AcceptancePreparationTests(TemporaryDirectoryMixin, unittest.TestCase):
    def session(self, *, elevated: bool = False, family: HostFamily = HostFamily.MACOS):
        return HostSession(family, "a" * 64, elevated, not elevated)

    def system(self, suffix: str = ""):
        fixture = self.temp_path / f"fixture{suffix}"
        runtime = self.temp_path / f"runtime{suffix}"
        issue_empty_fixture(fixture, runtime, HostFamily.MACOS, "fixture-machine")
        local = PurePosixPath(str(runtime.resolve()))
        fixture_path = PurePosixPath(str(fixture.resolve()))
        python = PurePosixPath("/usr/bin/python3")
        profile = MachineProfile(
            1, "99999999-9999-9999-9999-999999999999", "fixture-machine",
            HostFamily.MACOS, "0.1.0", "3.0.1", 1, fixture_path,
            fixture_path / "context-os/extensions", fixture_path / "skills", local,
            local / "projectos.db", local / "projectos.toml", local / "projectos.sync.lock",
            local / "logs", local / "staging", python,
            (str(python), "-m", "projectos.cli"), SchedulerKind.LAUNCHD,
            "com.contextos.projectos.sync", "PLANNED", None,
        )
        profile_path = runtime / "machine-profile.json"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(
            json.dumps(machine_profile_mapping(profile), sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        package_root = self.temp_path / f"package{suffix}"
        package_root.mkdir()
        package = AcceptancePackageTests()._build(package_root)
        evidence = runtime / "acceptance/evidence"
        evidence.mkdir(parents=True)
        request = AcceptancePreparationRequest(
            self.temp_path / f"authority{suffix}", runtime, fixture, profile_path, package, evidence,
            "CLEAN_HOST_NATIVE_ACCEPTANCE", "FIXTURE_ONLY",
        )
        return request, profile

    def prepare(self, request, *, session=None, boundary_hook=lambda name: None):
        selected = session or self.session()
        with patch("projectos.acceptance.authority.detect_host_session", return_value=selected):
            return AcceptancePreparer().prepare(
                request, session=selected, boundary_hook=boundary_hook
            )

    def test_prepare_requires_new_authority_exact_acks_fixture_receipt_and_standard_user(self) -> None:
        request, _ = self.system()
        for changed in (
            replace(request, acceptance_ack="wrong"),
            replace(request, fixture_ack="wrong"),
        ):
            with self.subTest(changed=changed), self.assertRaises(ValidationError):
                self.prepare(changed)
        with self.assertRaisesRegex(ValidationError, "elevated"):
            self.prepare(request, session=self.session(elevated=True))

    def test_prepare_binds_package_wheel_extension_source_profile_and_host(self) -> None:
        request, _ = self.system()
        prepared = self.prepare(request)
        record = prepared.record
        self.assertEqual(prepared.package.sha256, record.package_sha256)
        self.assertEqual(prepared.package.manifest.wheel.sha256, record.wheel_sha256)
        self.assertEqual(
            prepared.package.manifest.extension_bundle.sha256,
            record.extension_bundle_sha256,
        )
        self.assertEqual(HostFamily.MACOS, prepared.target.host_family)
        self.assertEqual(
            hashlib.sha256(prepared.profile.canonical_bytes()).hexdigest(),
            record.profile_sha256,
        )

    def test_prepare_allocates_safe_definition_activation_and_preparation_ids(self) -> None:
        prepared = self.prepare(self.system()[0])
        values = (
            prepared.record.preparation_id,
            prepared.profile.definition_transaction_id,
            prepared.profile.activation_id,
        )
        self.assertEqual(3, len(set(values)))
        for value in values:
            self.assertRegex(value, r"^[0-9a-f-]{36}$")

    def test_prepare_stages_only_verified_extension_below_runtime(self) -> None:
        request, _ = self.system()
        prepared = self.prepare(request)
        self.assertTrue(prepared.staged_extension_bundle.is_file())
        self.assertTrue(prepared.staged_extension_bundle.is_relative_to(request.runtime_root))
        self.assertEqual(
            prepared.package.manifest.extension_bundle.sha256,
            hashlib.sha256(prepared.staged_extension_bundle.read_bytes()).hexdigest(),
        )

    def test_prepare_is_one_shot_and_rejects_symlink_overlap_elevation_and_host_mismatch(self) -> None:
        request, _ = self.system()
        self.prepare(request)
        with self.assertRaises(ValidationError):
            self.prepare(request)
        linked_request, _ = self.system("-linked")
        actual = self.temp_path / "actual-authority"
        actual.mkdir()
        linked_request.acceptance_root.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(ValidationError, "symlink"):
            self.prepare(linked_request)
        overlap_request, _ = self.system("-overlap")
        overlap_request = replace(
            overlap_request,
            acceptance_root=overlap_request.fixture_root / "acceptance",
        )
        with self.assertRaisesRegex(ValidationError, "excluded"):
            self.prepare(overlap_request)
        mismatch_request, _ = self.system("-host")
        with self.assertRaisesRegex(ValidationError, "host"):
            self.prepare(
                mismatch_request,
                session=self.session(family=HostFamily.WINDOWS),
            )

    def test_prepare_failure_at_every_write_boundary_leaves_no_reusable_partial_state(self) -> None:
        boundaries = AcceptancePreparer.boundaries()
        for index, boundary in enumerate(boundaries):
            with self.subTest(boundary=boundary):
                request, _ = self.system(f"-{index}")
                def stop(name, selected=boundary):
                    if name == selected:
                        raise RuntimeError(name)
                with self.assertRaises(RuntimeError):
                    self.prepare(request, boundary_hook=stop)
                self.assertFalse((request.runtime_root / "acceptance/state/preparation.json").exists())
                self.assertFalse((request.runtime_root / "acceptance/staging/projectos-extension.zip").exists())

    def test_prepare_record_is_canonical_and_contains_no_resolved_paths(self) -> None:
        request, _ = self.system()
        prepared = self.prepare(request)
        content = prepared.record_path.read_bytes()
        self.assertEqual(prepared.record.canonical_bytes(), content)
        self.assertNotIn(str(self.temp_path).encode(), content)


if __name__ == "__main__":
    unittest.main()
