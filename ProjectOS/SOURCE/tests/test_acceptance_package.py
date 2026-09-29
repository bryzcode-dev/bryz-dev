from __future__ import annotations

import getpass
import hashlib
import json
import socket
import stat
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from tests.helpers import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build_backend

from projectos import __version__
from projectos.adoption.bundle import ArtifactPolicy, ExtensionBundleBuilder
from projectos.adoption.host import HostFamily
from projectos.adoption.manifest import (
    CommandDeclaration,
    CompatibilityDeclaration,
    ExtensionManifest,
    SkillDeclaration,
)
from projectos.acceptance.model import (
    REQUIRED_ACCEPTANCE_CASES,
    AcceptanceManifest,
    SupportState,
)
from projectos.acceptance.package import AcceptancePackageBuilder, verify_acceptance_package
from projectos.errors import ValidationError


CREATED_AT = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
SOURCE_REVISION = "320692861fc3f64f6bd8b4bb6732b82d339f9ae7"
EXPECTED_CASES = (
    "package_integrity",
    "standard_user_non_elevated",
    "fixture_authority",
    "local_path_separation",
    "definition_structural_equivalence",
    "native_install_disabled",
    "native_enable",
    "immediate_trigger",
    "common_lock_contention",
    "native_non_overlap",
    "two_hour_configuration",
    "eligible_resume_configuration",
    "skill_discovery",
    "deactivation_order",
    "native_disable_remove",
    "definition_rollback",
    "retained_database_health",
    "identifier_secret_symlink_scan",
)


class AcceptancePackageTests(unittest.TestCase):
    def _extension_bundle(self, root: Path) -> Path:
        payload = root / "extension-payload"
        skill = payload / "skills/projectos/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# ProjectOS\n", encoding="utf-8")
        manifest = ExtensionManifest(
            1,
            1,
            "projectos",
            __version__,
            "2026-09-27T00:00:00Z",
            CompatibilityDeclaration(
                "3.0.1", "4.0.0", 1, (HostFamily.MACOS, HostFamily.WINDOWS)
            ),
            SkillDeclaration(
                "projectos",
                __version__,
                "skills/projectos/SKILL.md",
                ("inspect-project", "status", "sync"),
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
        output = root / "projectos-extension.zip"
        ExtensionBundleBuilder().build(manifest, payload, output, ArtifactPolicy(()))
        return output

    def _build(self, root: Path, name: str = "projectos-acceptance.zip") -> Path:
        wheel_dir = root / "wheel"
        wheel_dir.mkdir()
        wheel = wheel_dir / build_backend.build_wheel(str(wheel_dir))
        extension_bundle = self._extension_bundle(root)
        output = root / name
        AcceptancePackageBuilder().build(
            wheel, extension_bundle, SOURCE_REVISION, CREATED_AT, output
        )
        return output

    def test_acceptance_manifest_has_exact_canonical_release_and_case_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self._build(Path(temporary))
            with zipfile.ZipFile(package) as archive:
                raw = archive.read("acceptance-manifest.json")
        mapping = json.loads(raw)
        self.assertEqual(
            {
                "acceptance_tasks",
                "contextos_contract",
                "created_at",
                "extension_bundle",
                "members",
                "projectos_version",
                "python_contract",
                "required_cases",
                "schema_version",
                "source_revision",
                "supported_hosts",
                "wheel",
            },
            set(mapping),
        )
        self.assertEqual(EXPECTED_CASES, REQUIRED_ACCEPTANCE_CASES)
        self.assertEqual(list(EXPECTED_CASES), mapping["required_cases"])
        self.assertEqual(
            [state.value for state in SupportState],
            ["SIMULATED", "MACOS_VERIFIED", "WINDOWS_VERIFIED", "CROSS_PLATFORM_VERIFIED"],
        )
        manifest = AcceptanceManifest.from_mapping(mapping)
        self.assertEqual(raw, manifest.canonical_bytes())
        self.assertEqual("2026-09-27T12:00:00Z", mapping["created_at"])
        self.assertEqual(2, mapping["schema_version"])

    def test_v2_manifest_binds_exact_extension_bundle_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self._build(Path(temporary))
            verified = verify_acceptance_package(package)
        metadata = verified.manifest.extension_bundle
        self.assertEqual("projectos-extension.zip", metadata.filename)
        self.assertEqual("projectos", metadata.extension_id)
        self.assertEqual(__version__, metadata.product_version)
        self.assertEqual(1, metadata.member_count)
        self.assertRegex(metadata.sha256, r"^[0-9a-f]{64}$")
        self.assertRegex(metadata.manifest_sha256, r"^[0-9a-f]{64}$")

    def test_acceptance_package_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_package = self._build(Path(first))
            second_package = self._build(Path(second))
            self.assertEqual(first_package.read_bytes(), second_package.read_bytes())

    def test_acceptance_package_contains_exactly_seven_members(self) -> None:
        expected = {
            "acceptance-manifest.json",
            "projectos-0.1.0-py3-none-any.whl",
            "projectos-extension.zip",
            "macos/run-projectos-acceptance.sh",
            "windows/Run-ProjectOSAcceptance.ps1",
            "docs/PHASE3D_HOST_OPERATIONS.md",
            "SHA256SUMS.txt",
        }
        with tempfile.TemporaryDirectory() as temporary:
            package = self._build(Path(temporary))
            verified = verify_acceptance_package(package)
            with zipfile.ZipFile(package) as archive:
                self.assertEqual(expected, set(archive.namelist()))
                sums = archive.read("SHA256SUMS.txt").decode("ascii").splitlines()
                sum_names = [line.split("  ", 1)[1] for line in sums]
                self.assertEqual(sorted(sum_names), sum_names)
                self.assertEqual(expected - {"SHA256SUMS.txt"}, set(sum_names))
            self.assertEqual(package, verified.path)
            self.assertEqual(hashlib.sha256(package.read_bytes()).hexdigest(), verified.sha256)

    def test_nested_extension_bundle_rejects_hash_inventory_symlink_extra_member_and_release_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self._build(root)
            with zipfile.ZipFile(original) as archive:
                entries = [(item, archive.read(item.filename)) for item in archive.infolist()]
            changed = root / "changed-extension.zip"
            with zipfile.ZipFile(changed, "w") as archive:
                for item, content in entries:
                    if item.filename == "projectos-extension.zip":
                        content += b"changed"
                    archive.writestr(item, content)
            with self.assertRaises(ValidationError):
                verify_acceptance_package(changed)

    def test_extraction_writes_only_verified_bundle_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = verify_acceptance_package(self._build(root))
            destination = root / "staging/projectos-extension.zip"
            extracted = package.extract_extension_bundle(destination)
            self.assertEqual(destination, extracted)
            self.assertEqual(
                package.manifest.extension_bundle.sha256,
                hashlib.sha256(extracted.read_bytes()).hexdigest(),
            )
            with self.assertRaises(ValidationError):
                package.extract_extension_bundle(destination)

    def test_package_build_requires_extension_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / build_backend.build_wheel(str(root))
            with self.assertRaises(TypeError):
                AcceptancePackageBuilder().build(  # type: ignore[call-arg]
                    wheel, SOURCE_REVISION, CREATED_AT, root / "acceptance.zip"
                )

    def test_package_rejects_wrong_wheel_hash_extra_member_casefold_duplicate_traversal_and_symlink(self) -> None:
        mutations = {
            "wrong-wheel": [("projectos-0.1.0-py3-none-any.whl", b"not the wheel", None)],
            "extra": [("extra.txt", b"extra", None)],
            "casefold": [("MACOS/run-projectos-acceptance.sh", b"duplicate", None)],
            "traversal": [("../escape.txt", b"escape", None)],
            "symlink": [("link", b"target", (stat.S_IFLNK | 0o777) << 16)],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self._build(root)
            with zipfile.ZipFile(original) as archive:
                entries = [(item, archive.read(item.filename)) for item in archive.infolist()]
            for label, additions in mutations.items():
                changed = root / f"{label}.zip"
                with zipfile.ZipFile(changed, "w") as archive:
                    replaced = {name for name, _, _ in additions}
                    for item, content in entries:
                        if item.filename not in replaced:
                            archive.writestr(item, content)
                    for name, content, external_attr in additions:
                        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                        info.external_attr = external_attr or ((stat.S_IFREG | 0o644) << 16)
                        archive.writestr(info, content)
                with self.subTest(label=label):
                    with self.assertRaises(ValidationError):
                        verify_acceptance_package(changed)

    def test_package_contains_no_private_identifier_or_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self._build(Path(temporary))
            with zipfile.ZipFile(package) as archive:
                searchable = b"\n".join(archive.read(name) for name in archive.namelist()).decode(
                    "utf-8", errors="replace"
                )
        for forbidden in (str(Path.home()), str(REPO_ROOT), getpass.getuser(), socket.gethostname()):
            self.assertNotIn(forbidden, searchable)
        self.assertNotIn("-----BEGIN PRIVATE KEY-----", searchable)
        self.assertNotRegex(searchable, r"ghp_[A-Za-z0-9]{20,}")
        self.assertNotRegex(searchable, r"(?i)(password|access[_-]?token)\s*[:=]\s*[^\s]+")


if __name__ == "__main__":
    unittest.main()
