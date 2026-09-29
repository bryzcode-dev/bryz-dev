from __future__ import annotations

import getpass
import hashlib
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests.helpers import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build_backend


class BuildBackendTests(unittest.TestCase):
    def test_builds_installable_projectos_wheel_without_external_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel_name = build_backend.build_wheel(temporary)
            wheel_path = Path(temporary) / wheel_name

            self.assertEqual("projectos-0.1.0-py3-none-any.whl", wheel_name)
            with zipfile.ZipFile(wheel_path) as archive:
                names = set(archive.namelist())
                metadata = archive.read("projectos-0.1.0.dist-info/METADATA").decode()
                entry_points = archive.read(
                    "projectos-0.1.0.dist-info/entry_points.txt"
                ).decode()

            self.assertIn("projectos/cli.py", names)
            self.assertIn("projectos/migrations/0001.sql", names)
            self.assertIn("projectos/migrations/0002.sql", names)
            self.assertIn("projectos/migrations/0003.sql", names)
            self.assertIn("Name: projectos", metadata)
            self.assertIn("Requires-Python: >=3.11", metadata)
            self.assertIn("Provides-Extra: google", metadata)
            self.assertIn("Requires-Dist: google-api-python-client", metadata)
            self.assertIn("extra == 'google'", metadata)
            self.assertNotIn("Requires-Dist: google-api-python-client\n", metadata)
            self.assertIn("projectos = projectos.cli:main", entry_points)

    def test_wheel_contains_all_phase3b_modules(self) -> None:
        expected = {
            path.relative_to(REPO_ROOT / "src").as_posix()
            for path in (REPO_ROOT / "src/projectos/adoption").glob("*.py")
        }
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / build_backend.build_wheel(temporary)
            with zipfile.ZipFile(wheel) as archive:
                self.assertTrue(expected)
                self.assertEqual(expected, expected.intersection(archive.namelist()))

    def test_phase3b_wheel_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_wheel = Path(first) / build_backend.build_wheel(first)
            second_wheel = Path(second) / build_backend.build_wheel(second)

            self.assertEqual(first_wheel.read_bytes(), second_wheel.read_bytes())
            self.assertEqual(
                hashlib.sha256(first_wheel.read_bytes()).hexdigest(),
                hashlib.sha256(second_wheel.read_bytes()).hexdigest(),
            )

    def test_wheel_contains_all_phase3c_modules(self) -> None:
        expected = {
            "projectos/runtime.py",
            "projectos/adoption/activation.py",
            "projectos/adoption/activation_store.py",
            "projectos/adoption/discovery.py",
            "projectos/adoption/scheduler.py",
            "projectos/adoption/scheduler_fixture.py",
            "projectos/adoption/scheduler_macos.py",
            "projectos/adoption/scheduler_windows.py",
            "projectos/adoption/skill.py",
        }
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / build_backend.build_wheel(temporary)
            with zipfile.ZipFile(wheel) as archive:
                self.assertEqual(expected, expected.intersection(archive.namelist()))

    def test_phase3c_wheel_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_wheel = Path(first) / build_backend.build_wheel(first)
            second_wheel = Path(second) / build_backend.build_wheel(second)

            self.assertEqual(first_wheel.read_bytes(), second_wheel.read_bytes())
            self.assertEqual(
                hashlib.sha256(first_wheel.read_bytes()).hexdigest(),
                hashlib.sha256(second_wheel.read_bytes()).hexdigest(),
            )

    def test_wheel_contains_acceptance_assets_as_regular_members(self) -> None:
        expected = {
            "projectos/acceptance/assets/macos/run-projectos-acceptance.sh",
            "projectos/acceptance/assets/windows/Run-ProjectOSAcceptance.ps1",
            "projectos/acceptance/assets/docs/PHASE3D_HOST_OPERATIONS.md",
        }
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / build_backend.build_wheel(temporary)
            with zipfile.ZipFile(wheel) as archive:
                members = {item.filename: item for item in archive.infolist()}

        self.assertEqual(expected, expected.intersection(members))
        for name in expected:
            self.assertEqual(0o100644, members[name].external_attr >> 16)

    def test_wheel_contains_all_phase3d_b_modules(self) -> None:
        expected = {
            "projectos/acceptance/collector.py",
            "projectos/acceptance/controllers.py",
            "projectos/acceptance/host_context.py",
            "projectos/acceptance/native_probe.py",
            "projectos/acceptance/preparation.py",
            "projectos/acceptance_host.py",
        }
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / build_backend.build_wheel(temporary)
            with zipfile.ZipFile(wheel) as archive:
                self.assertEqual(expected, expected.intersection(archive.namelist()))

    def test_wheel_contains_complete_phase4_runtime(self) -> None:
        expected = {
            "projectos/looker/analytics.py",
            "projectos/looker/collector.py",
            "projectos/looker/cutover.py",
            "projectos/looker/evidence.py",
            "projectos/looker/importer.py",
            "projectos/looker/lookml.py",
            "projectos/looker/reconcile.py",
            "projectos/looker/refresh.py",
            "projectos/looker/repository.py",
            "projectos/looker_cutover_host.py",
            "projectos/looker_host.py",
            "projectos/migrations/0003.sql",
        }
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / build_backend.build_wheel(temporary)
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
        self.assertEqual(expected, expected.intersection(names))

    def test_packaged_phase3d_operations_are_byte_identical_to_handoff(self) -> None:
        expected = (REPO_ROOT / "docs/PHASE3D_HOST_OPERATIONS.md").read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / build_backend.build_wheel(temporary)
            with zipfile.ZipFile(wheel) as archive:
                actual = archive.read(
                    "projectos/acceptance/assets/docs/PHASE3D_HOST_OPERATIONS.md"
                )
        self.assertEqual(expected, actual)

    def test_extracted_wheel_completes_fixture_activation_and_deactivation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / build_backend.build_wheel(root)
            extracted = root / "extracted"
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(extracted)

            result = self._run_extracted_phase3c(extracted, root)

        self.assertEqual(0, result.returncode, result.stderr)

    def test_phase3c_wheel_scheduler_skill_and_fixture_evidence_contain_no_private_identifiers_or_secrets(
        self,
    ) -> None:
        forbidden = {
            str(Path.home()),
            str(REPO_ROOT),
            getpass.getuser(),
            socket.gethostname(),
            "fixture-owner@example.invalid",
            "sheet-wheel",
            "projectos/wheel",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / build_backend.build_wheel(root)
            extracted = root / "extracted"
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(extracted)
                wheel_searchable = b"\n".join(
                    archive.read(name) for name in archive.namelist()
                ).decode("utf-8", errors="replace")
                symlink_members = [
                    item.filename
                    for item in archive.infolist()
                    if (item.external_attr >> 16) & 0o170000 == 0o120000
                ]
            result = self._run_extracted_phase3c(extracted, root)
            self.assertEqual(0, result.returncode, result.stderr)
            evidence_roots = (
                root / "runtime/adoption",
                root / "contextos/context-os/extensions/projectos",
            )
            evidence_files = [
                path
                for evidence_root in evidence_roots
                if evidence_root.exists()
                for path in evidence_root.rglob("*")
                if path.is_file()
            ]
            evidence_searchable = b"\n".join(
                path.read_bytes() for path in evidence_files
            ).decode("utf-8", errors="replace")
            evidence_links = [path for path in evidence_files if path.is_symlink()]

        self.assertEqual([], symlink_members)
        self.assertEqual([], evidence_links)
        for identifier in forbidden:
            self.assertNotIn(identifier, wheel_searchable)
            self.assertNotIn(identifier, evidence_searchable)
        for searchable in (wheel_searchable, evidence_searchable):
            self.assertNotIn("-----BEGIN PRIVATE KEY-----", searchable)
            self.assertNotRegex(searchable, r"ghp_[A-Za-z0-9]{20,}")
            self.assertNotRegex(searchable, r"(?i)(password|access[_-]?token)\s*[:=]\s*[^\s]+")

    def test_wheel_and_fixture_evidence_contain_no_build_or_target_identifiers(self) -> None:
        forbidden = {
            str(Path.home()),
            str(REPO_ROOT),
            getpass.getuser(),
            socket.gethostname(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / build_backend.build_wheel(temporary)
            with zipfile.ZipFile(wheel) as archive:
                searchable = b"\n".join(
                    archive.read(name)
                    for name in archive.namelist()
                    if name.endswith((".py", ".sql", "METADATA", "WHEEL", "entry_points.txt"))
                ).decode("utf-8", errors="replace")

        for identifier in forbidden:
            self.assertNotIn(identifier, searchable)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / build_backend.build_wheel(root)
            extracted = root / "extracted"
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(extracted)
            result = self._run_extracted_fixture(extracted, root, "uninstall")
            self.assertEqual(0, result.returncode, result.stderr)
            artifact_roots = (
                root / "runtime/adoption/transactions",
                root / "runtime/adoption/archives",
            )
            fixture_searchable = b"\n".join(
                path.read_bytes()
                for artifact_root in artifact_roots
                if artifact_root.exists()
                for path in artifact_root.rglob("*")
                if path.is_file()
            ).decode("utf-8", errors="replace")

        for identifier in (*forbidden, str(root), "target-private-host"):
            self.assertNotIn(identifier, fixture_searchable)
        self.assertNotIn("-----BEGIN PRIVATE KEY-----", fixture_searchable)
        self.assertNotRegex(fixture_searchable, r"ghp_[A-Za-z0-9]{20,}")

    def test_extracted_wheel_completes_fixture_adopt_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / build_backend.build_wheel(root)
            extracted = root / "extracted"
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(extracted)

            result = self._run_extracted_fixture(extracted, root, "rollback")

        self.assertEqual(0, result.returncode, result.stderr)

    @staticmethod
    def _run_extracted_fixture(
        extracted: Path, root: Path, final_action: str
    ) -> subprocess.CompletedProcess[str]:
        program = textwrap.dedent(
            f"""
            import sys
            from pathlib import Path

            sys.path.insert(0, {str(extracted)!r})

            from projectos.adoption.bundle import ArtifactPolicy, ExtensionBundleBuilder
            from projectos.adoption.contextos import ContextOSLocator
            from projectos.adoption.fixture import FixtureInstallationTarget, issue_empty_fixture
            from projectos.adoption.host import HostFamily
            from projectos.adoption.manifest import (
                CommandDeclaration, CompatibilityDeclaration, ExtensionManifest,
                SkillDeclaration,
            )
            from projectos.adoption.profile import MachineProfile, SchedulerKind
            from projectos.adoption.store import AdoptionOperation, LocalAdoptionStore
            from projectos.adoption.transaction import AdoptionTransaction

            root = Path({str(root)!r})
            contextos = (root / "contextos").resolve()
            runtime = (root / "runtime").resolve()
            python = Path(sys.executable)
            profile = MachineProfile(
                1, "99999999-9999-9999-9999-999999999999", "target-private-host",
                HostFamily.MACOS, "0.1.0", "3.0.1", 1, contextos,
                contextos / "context-os/extensions", contextos / "skills", runtime,
                runtime / "projectos.db", runtime / "projectos.toml",
                runtime / "projectos.sync.lock", runtime / "logs", runtime / "staging",
                python, (str(python), "-m", "projectos.cli"), SchedulerKind.LAUNCHD,
                "com.contextos.projectos.sync", "PLANNED", None,
            )
            issue_empty_fixture(contextos, runtime, HostFamily.MACOS, profile.machine_id)
            installation = ContextOSLocator(HostFamily.MACOS, {{}}, root / "home").inspect(contextos)
            target = FixtureInstallationTarget.open(installation, runtime, "FIXTURE_ONLY")
            payload = root / "payload"
            skill = payload / "skills/projectos/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("# ProjectOS fixture skill\\n", encoding="utf-8")
            (payload / "projectos.whl").write_bytes(b"portable-wheel-payload")
            manifest = ExtensionManifest(
                1, 1, "projectos", "0.1.0", "2026-09-27T00:00:00Z",
                CompatibilityDeclaration(
                    "3.0.1", "4.0.0", 1, (HostFamily.MACOS, HostFamily.WINDOWS)
                ),
                SkillDeclaration("projectos", "0.1.0", "skills/projectos/SKILL.md", ("sync",)),
                (CommandDeclaration("health", ("projectos", "doctor"), False),),
                2, "CURRENT", "machine-profile.json", True, (), "STAGED", (),
            )
            bundle = root / "bundle.zip"
            ExtensionBundleBuilder().build(manifest, payload, bundle, ArtifactPolicy(()))
            store = LocalAdoptionStore.open(profile)
            transaction = AdoptionTransaction.begin(
                AdoptionOperation.ADOPT, target, profile, store, ArtifactPolicy(()),
                "tx-wheel-adopt", bundle,
            )
            transaction.preflight()
            transaction.snapshot()
            transaction.stage()
            transaction.verify()
            assert transaction.adopt_disabled().state.value == "ADOPTED"
            if {final_action!r} == "rollback":
                assert transaction.rollback().state.value == "ROLLED_BACK"
                assert not target.registry_path.exists()
            else:
                uninstall = AdoptionTransaction.begin(
                    AdoptionOperation.UNINSTALL, target, profile, store,
                    ArtifactPolicy(()), "tx-wheel-uninstall",
                )
                uninstall.preflight()
                uninstall.snapshot()
                assert uninstall.uninstall().state.value == "UNINSTALLED"
            """
        )
        return subprocess.run(
            [sys.executable, "-I", "-c", program],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _run_extracted_phase3c(
        extracted: Path, root: Path
    ) -> subprocess.CompletedProcess[str]:
        program = textwrap.dedent(
            f"""
            import json
            import sys
            from pathlib import Path
            from uuid import uuid4

            sys.path.insert(0, {str(extracted)!r})

            from projectos.adoption.activation import RuntimeActivation
            from projectos.adoption.activation_store import ActivationProofResult
            from projectos.adoption.bundle import ArtifactPolicy, ExtensionBundleBuilder
            from projectos.adoption.contextos import ContextOSLocator
            from projectos.adoption.fixture import FixtureInstallationTarget, issue_empty_fixture
            from projectos.adoption.host import HostFamily
            from projectos.adoption.manifest import (
                CommandDeclaration, CompatibilityDeclaration, ExtensionManifest,
                SkillDeclaration,
            )
            from projectos.adoption.profile import MachineProfile, SchedulerKind
            from projectos.adoption.scheduler import SchedulerState, adapter_for
            from projectos.adoption.scheduler_fixture import FixtureSchedulerRunner
            from projectos.adoption.skill import render_projectos_skill
            from projectos.adoption.store import AdoptionOperation, LocalAdoptionStore
            from projectos.adoption.transaction import AdoptionTransaction
            from projectos.bindings import GoogleBindingRepository
            from projectos.credentials import CredentialReferenceCreate, CredentialReferenceService
            from projectos.database import ProjectOSDatabase
            from projectos.google.fake_gateway import FakeGoogleGateway
            from projectos.google.types import GoogleBindingCreate
            from projectos.runtime import RuntimeTrigger
            from projectos.users import UserRepository

            root = Path({str(root)!r})
            contextos = (root / "contextos").resolve()
            runtime = (root / "runtime").resolve()
            python = Path(sys.executable)
            profile = MachineProfile(
                1, "99999999-9999-9999-9999-999999999999", "fixture-wheel",
                HostFamily.MACOS, "0.1.0", "3.0.1", 1, contextos,
                contextos / "context-os/extensions", contextos / "skills", runtime,
                runtime / "projectos.db", runtime / "projectos.toml",
                runtime / "projectos.sync.lock", runtime / "logs", runtime / "staging",
                python, (str(python), "-m", "projectos.cli"), SchedulerKind.LAUNCHD,
                "com.contextos.projectos.sync", "PLANNED", None,
            )
            issue_empty_fixture(contextos, runtime, HostFamily.MACOS, profile.machine_id)
            installation = ContextOSLocator(HostFamily.MACOS, {{}}, root / "home").inspect(contextos)
            target = FixtureInstallationTarget.open(installation, runtime, "FIXTURE_ONLY")
            store = LocalAdoptionStore.open(profile)
            policy = ArtifactPolicy(())
            manifest = ExtensionManifest(
                1, 1, "projectos", "0.1.0", "2026-09-27T00:00:00Z",
                CompatibilityDeclaration(
                    "3.0.1", "4.0.0", 1, (HostFamily.MACOS, HostFamily.WINDOWS)
                ),
                SkillDeclaration(
                    "projectos", "0.1.0", "skills/projectos/SKILL.md",
                    ("sync", "status", "inspect-project"),
                ),
                (CommandDeclaration("health", ("projectos", "doctor"), False),),
                2, "CURRENT", "machine-profile.json", True, (), "STAGED", (),
            )
            payload = root / "payload"
            skill = payload / "skills/projectos/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_bytes(render_projectos_skill(manifest))
            (payload / "projectos.whl").write_bytes(b"portable-wheel-payload")
            bundle = root / "bundle.zip"
            ExtensionBundleBuilder().build(manifest, payload, bundle, policy)

            database = ProjectOSDatabase(Path(profile.database_path)).initialize()
            owner = "fixture-owner@example.invalid"
            UserRepository(database, owner).seed_owner(owner, "Fixture Owner")
            credential = CredentialReferenceService(database).create(
                CredentialReferenceCreate(
                    "GOOGLE", "wheel", "ADC", "sync", "KEYCHAIN", "projectos/wheel"
                ),
                owner,
            )
            binding = GoogleBindingRepository(database).create(
                GoogleBindingCreate(
                    "DEV", "sheet-wheel", "ProjectOS", 1, credential.credential_id,
                    enabled=True, write_enabled=True,
                ),
                owner,
            )
            database.close()
            Path(profile.config_path).write_text(
                "\\n".join((
                    "contract_version = 1",
                    f'machine_id = "{{profile.machine_id}}"',
                    'environment = "DEV"',
                    f'binding_id = "{{binding.binding_id}}"',
                    'spreadsheet_id = "sheet-wheel"',
                    f'expected_owner_email = "{{owner}}"',
                    f'credential_reference_id = "{{credential.credential_id}}"',
                    "google_enabled = true",
                    "google_write_enabled = true",
                    "",
                )),
                encoding="utf-8",
            )

            definition = AdoptionTransaction.begin(
                AdoptionOperation.ADOPT, target, profile, store, policy,
                "tx-wheel-definition", bundle,
            )
            definition.preflight()
            definition.snapshot()
            definition.stage()
            definition.verify()
            adopted = definition.adopt_disabled()
            profile_path = store.root / "machine-profile.json"
            runner = FixtureSchedulerRunner.open(target, profile, store)

            class Proof:
                def run(self, discovered, coordinator):
                    gateway = FakeGoogleGateway.from_fixture({{
                        "contract_version": 1,
                        "tabs": {{}},
                        "requests": [],
                        "access_events": [],
                        "write_ready": True,
                    }})
                    statuses = []
                    for trigger in (RuntimeTrigger.SCHEDULER, RuntimeTrigger.SKILL):
                        result = coordinator.run(
                            profile_path, Path(profile.database_path), trigger, gateway,
                            wait_seconds=0,
                        )
                        statuses.append(result.status)
                    return ActivationProofResult(
                        True, ("scheduler", "skill"), tuple(statuses), None
                    )

            activation = RuntimeActivation(
                target, profile_path, store, runner, policy, Proof()
            )
            activated = activation.begin(adopted.transaction_id)
            assert activated.state.value == "PROVED"
            deactivated = activation.deactivate(activated.activation_id)
            assert deactivated.state.value == "DEACTIVATED"
            scheduler_definition = adapter_for(profile).render(profile, profile_path)
            assert runner.inspect(scheduler_definition).state is SchedulerState.ABSENT
            (root / "phase3c-result.json").write_text(
                json.dumps({{"activated": "PROVED", "deactivated": "DEACTIVATED"}}),
                encoding="utf-8",
            )
            """
        )
        return subprocess.run(
            [sys.executable, "-I", "-c", program],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_extracted_wheel_imports_with_fcntl_unavailable_until_posix_lock_selected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / build_backend.build_wheel(temporary)
            extracted = root / "extracted"
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(extracted)
            program = textwrap.dedent(
                f"""
                import importlib.abc
                import sys

                class DenyFcntl(importlib.abc.MetaPathFinder):
                    def find_spec(self, fullname, path, target=None):
                        if fullname == "fcntl":
                            raise ModuleNotFoundError("fcntl unavailable")
                        return None

                sys.modules.pop("fcntl", None)
                sys.meta_path.insert(0, DenyFcntl())
                sys.path.insert(0, {str(extracted)!r})
                import projectos.cli
                from projectos.adoption.lock import PosixLockBackend
                try:
                    PosixLockBackend()._native()
                except ModuleNotFoundError as exc:
                    assert str(exc) == "fcntl unavailable"
                else:
                    raise AssertionError("POSIX selection unexpectedly imported fcntl")
                """
            )
            result = subprocess.run(
                [sys.executable, "-I", "-c", program],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_wheel_rejects_symlinked_source_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src/projectos/adoption"
            source.mkdir(parents=True)
            external = root / "external.py"
            external.write_text("BUILD_HOST_SECRET = 'must-not-ship'\n", encoding="utf-8")
            (source / "leak.py").symlink_to(external)

            with patch.object(build_backend, "SOURCE", root / "src"):
                with self.assertRaisesRegex(RuntimeError, "symbolic link"):
                    build_backend.build_wheel(root / "dist")


if __name__ == "__main__":
    unittest.main()
