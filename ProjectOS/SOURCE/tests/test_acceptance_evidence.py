from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from tests.helpers import TemporaryDirectoryMixin

from projectos.acceptance.evidence import (
    AcceptanceCaseResult,
    AcceptanceEvidenceBuilder,
    AcceptanceEvidenceVerifier,
    HostAcceptanceRecord,
)
from projectos.acceptance.model import ACCEPTANCE_TASKS, REQUIRED_ACCEPTANCE_CASES, AcceptanceManifest
from projectos.errors import ValidationError


def manifest() -> AcceptanceManifest:
    return AcceptanceManifest.from_mapping({
        "schema_version": 2,
        "projectos_version": "0.1.0",
        "source_revision": "1" * 40,
        "wheel": {"filename": "projectos-0.1.0-py3-none-any.whl", "size": 100, "member_count": 10, "sha256": "2" * 64},
        "extension_bundle": {
            "filename": "projectos-extension.zip", "size": 200, "member_count": 3,
            "sha256": "7" * 64, "extension_id": "projectos",
            "product_version": "0.1.0", "manifest_sha256": "9" * 64,
        },
        "supported_hosts": ["macos", "windows"],
        "python_contract": ">=3.11",
        "contextos_contract": ">=3.0.1,<4",
        "acceptance_tasks": ACCEPTANCE_TASKS,
        "required_cases": list(REQUIRED_ACCEPTANCE_CASES),
        "created_at": "2026-09-27T12:00:00Z",
        "members": [
            {"path": "docs/PHASE3D_HOST_OPERATIONS.md", "size": 1, "sha256": "3" * 64},
            {"path": "macos/run-projectos-acceptance.sh", "size": 1, "sha256": "4" * 64},
            {"path": "projectos-0.1.0-py3-none-any.whl", "size": 100, "sha256": "2" * 64},
            {"path": "projectos-extension.zip", "size": 200, "sha256": "7" * 64},
            {"path": "windows/Run-ProjectOSAcceptance.ps1", "size": 1, "sha256": "5" * 64},
        ],
    })


def record(host: str = "macos") -> HostAcceptanceRecord:
    release = manifest()
    cases = tuple(
        AcceptanceCaseResult(
            index + 1, case_id, "PASS", "OK", "NATIVE",
            "2026-09-27T12:00:00Z", "2026-09-27T12:00:00Z", {"count": 1},
        )
        for index, case_id in enumerate(REQUIRED_ACCEPTANCE_CASES)
    )
    return HostAcceptanceRecord(
        "projectos-host-acceptance-v2", release.projectos_version, release.source_revision,
        release.wheel.sha256, release.extension_bundle.sha256, "6" * 64,
        hashlib.sha256(release.canonical_bytes()).hexdigest(), "a" * 64, "8" * 64, host,
        "15.0" if host == "macos" else "11", "arm64" if host == "macos" else "x86_64",
        "3.14.7", "99999999-9999-9999-9999-999999999999", True, True, cases,
        ("installed-disabled", "enabled", "installed-disabled", "absent"),
        "DEACTIVATED", "DEFINITION_ROLLED_BACK", True, True, True,
        ("raw-native-output", "database", "local-journal"), (),
    )


class AcceptanceEvidenceTests(TemporaryDirectoryMixin, unittest.TestCase):
    def build(self, selected: HostAcceptanceRecord | None = None, attachments=None) -> Path:
        output = self.temp_path / f"evidence-{len(list(self.temp_path.glob('*.zip')))}.zip"
        AcceptanceEvidenceBuilder().build(
            selected or record(), attachments or {"summary.json": b'{"safe":true}\n'}, output
        )
        return output

    def test_evidence_contains_exact_allowlisted_fields_cases_hashes_and_cleanup(self) -> None:
        path = self.build()
        verified = AcceptanceEvidenceVerifier().verify(path, manifest())
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(
                {"projectos-host-acceptance-v2.json", "attachments/summary.json", "SHA256SUMS.txt"},
                set(archive.namelist()),
            )
            mapping = json.loads(archive.read("projectos-host-acceptance-v2.json"))
        self.assertEqual(list(REQUIRED_ACCEPTANCE_CASES), [item["case_id"] for item in mapping["cases"]])
        self.assertTrue(mapping["cleanup_complete"])
        self.assertTrue(mapping["task_absent"])
        self.assertEqual("macos", verified.record.host_family)

    def test_evidence_excludes_paths_identities_external_ids_commands_native_output_and_raw_logs(self) -> None:
        path = self.build()
        with zipfile.ZipFile(path) as archive:
            searchable = b"\n".join(archive.read(name) for name in archive.namelist()).decode()
        for forbidden in ("/Users/", "C:\\Users\\", "owner@example.com", "sheet-id", "launchctl ", "schtasks.exe ", "stdout", "stderr"):
            self.assertNotIn(forbidden, searchable)

    def test_evidence_archive_rejects_traversal_casefold_duplicate_symlink_extra_binary_and_bad_hash(self) -> None:
        original = self.build()
        with zipfile.ZipFile(original) as archive:
            entries = [(item, archive.read(item.filename)) for item in archive.infolist()]
        changes = {
            "traversal": ("../escape.json", b"{}", None),
            "casefold": ("ATTACHMENTS/summary.json", b"{}", None),
            "symlink": ("link", b"target", (stat.S_IFLNK | 0o777) << 16),
            "extra": ("extra.bin", b"\x00\x01", None),
        }
        for label, addition in changes.items():
            changed = self.temp_path / f"{label}.zip"
            with zipfile.ZipFile(changed, "w") as archive:
                for item, content in entries:
                    archive.writestr(item, content)
                name, content, attrs = addition
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = attrs or ((stat.S_IFREG | 0o644) << 16)
                archive.writestr(info, content)
            with self.subTest(label=label), self.assertRaises(ValidationError):
                AcceptanceEvidenceVerifier().verify(changed, manifest())
        bad = self.temp_path / "bad-hash.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            for item, content in entries:
                archive.writestr(item, b"changed" if item.filename == "attachments/summary.json" else content)
        with self.assertRaises(ValidationError):
            AcceptanceEvidenceVerifier().verify(bad, manifest())

    def test_verifier_rejects_missing_duplicate_unknown_skipped_failed_or_simulated_native_case(self) -> None:
        base = record()
        variants = (
            base.cases[:-1],
            (*base.cases, base.cases[0]),
            (replace(base.cases[0], case_id="unknown"), *base.cases[1:]),
            (replace(base.cases[0], status="SKIPPED"), *base.cases[1:]),
            (replace(base.cases[0], status="FAILED"), *base.cases[1:]),
            (replace(base.cases[0], execution="SIMULATED"), *base.cases[1:]),
        )
        for cases in variants:
            with self.subTest(count=len(cases)):
                with self.assertRaises(ValidationError):
                    self.build(replace(base, cases=tuple(cases)))

    def test_verifier_rejects_release_host_elevation_definition_and_cleanup_mismatch(self) -> None:
        base = record()
        variants = (
            replace(base, source_revision="9" * 40),
            replace(base, host_family="linux"),
            replace(base, non_elevated=False),
            replace(base, definition_sha256="9" * 64),
            replace(base, cleanup_complete=False),
            replace(base, task_absent=False),
        )
        for item in variants:
            with self.subTest(host=item.host_family):
                with self.assertRaises(ValidationError):
                    path = self.build(item)
                    AcceptanceEvidenceVerifier().verify(path, manifest(), expected_definition_sha256="8" * 64)

    def test_equal_or_adjusted_wall_timestamps_use_sequence_not_duration(self) -> None:
        base = record()
        adjusted = tuple(
            replace(item, started_at="2026-09-27T12:00:01Z", ended_at="2026-09-27T12:00:00Z")
            for item in base.cases
        )
        verified = AcceptanceEvidenceVerifier().verify(self.build(replace(base, cases=adjusted)), manifest())
        self.assertEqual(tuple(range(1, len(REQUIRED_ACCEPTANCE_CASES) + 1)), tuple(item.sequence for item in verified.record.cases))

    def test_verifier_and_reconciler_reject_old_release_or_mismatched_extension_bundle(self) -> None:
        release = manifest()
        changed = replace(record(), extension_bundle_sha256="b" * 64)
        path = self.build(changed)
        with self.assertRaisesRegex(ValidationError, "release"):
            AcceptanceEvidenceVerifier().verify(path, release)


if __name__ == "__main__":
    unittest.main()
