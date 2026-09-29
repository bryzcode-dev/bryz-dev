from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.contextos import ContextOSLocator
from projectos.adoption.fixture import FixtureInstallationTarget, issue_empty_fixture
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import (
    MachineProfile,
    SchedulerKind,
    machine_profile_from_mapping,
    machine_profile_mapping,
)
from projectos.adoption.store import (
    AdoptionOperation,
    LocalAdoptionStore,
    TransactionState,
)
from projectos.errors import ValidationError


class AdoptionStoreTests(TemporaryDirectoryMixin, unittest.TestCase):
    def profile(self) -> MachineProfile:
        runtime = (self.temp_path / "runtime").resolve()
        contextos = (self.temp_path / "contextos-fixture").resolve()
        python = Path("/usr/bin/python3")
        return MachineProfile(
            1,
            "55555555-5555-5555-5555-555555555555",
            "fixture-mac",
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

    def target(self, profile: MachineProfile | None = None) -> FixtureInstallationTarget:
        selected = profile or self.profile()
        issue_empty_fixture(
            Path(selected.contextos_root),
            Path(selected.runtime_root),
            selected.host_family,
            selected.machine_id,
            selected.contextos_version,
        )
        installation = ContextOSLocator(
            selected.host_family, {}, self.temp_path / "home"
        ).inspect(selected.contextos_root)
        return FixtureInstallationTarget.open(
            installation, selected.runtime_root, "FIXTURE_ONLY"
        )

    def test_machine_profile_round_trip_is_strict_and_canonical(self) -> None:
        original = self.profile()
        mapping = machine_profile_mapping(original)

        loaded = machine_profile_from_mapping(mapping)

        self.assertEqual(original, loaded)
        self.assertEqual(mapping, machine_profile_mapping(loaded))
        for field, invalid in (("profile_schema_version", True), ("projectos_entrypoint", "bad")):
            with self.subTest(field=field):
                changed = dict(mapping)
                changed[field] = invalid
                with self.assertRaises(ValidationError):
                    machine_profile_from_mapping(changed)
        extra = dict(mapping)
        extra["unexpected"] = "value"
        with self.assertRaisesRegex(ValidationError, "fields"):
            machine_profile_from_mapping(extra)
        escaped = dict(mapping)
        escaped["extensions_root"] = str(self.temp_path / "outside-extensions")
        with self.assertRaisesRegex(ValidationError, "ContextOS root"):
            machine_profile_from_mapping(escaped)

    def test_store_is_derived_from_local_profile_and_rejects_shared_overlap(self) -> None:
        profile = self.profile()
        store = LocalAdoptionStore.open(profile)

        self.assertEqual(Path(profile.runtime_root) / "adoption", store.root)
        self.assertFalse(store.root.exists())

        for runtime in (
            Path(profile.contextos_root) / "runtime",
            Path(profile.contextos_root).parent,
        ):
            with self.subTest(runtime=runtime), self.assertRaisesRegex(
                ValidationError, "separate"
            ):
                LocalAdoptionStore.open(replace(profile, runtime_root=runtime))

        Path(profile.runtime_root).mkdir(parents=True)
        (Path(profile.runtime_root) / "adoption").symlink_to(
            self.temp_path / "redirected-adoption", target_is_directory=True
        )
        with self.assertRaisesRegex(ValidationError, "symlink"):
            LocalAdoptionStore.open(profile)

    def test_profile_and_journal_writes_are_atomic_and_canonical(self) -> None:
        profile = self.profile()
        target = self.target(profile)
        store = LocalAdoptionStore.open(profile)

        profile_path = store.save_profile(profile)
        journal = store.create_journal(
            AdoptionOperation.ADOPT, target, "a" * 64, "tx-0001"
        )
        store.save_journal(journal)

        self.assertEqual(profile, store.load_profile(profile_path))
        self.assertEqual(
            machine_profile_mapping(profile),
            json.loads(profile_path.read_text(encoding="utf-8")),
        )
        journal_path = store.transaction_root("tx-0001") / "journal.json"
        persisted = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual("DISCOVERED", persisted["state"])
        self.assertEqual(target.fixture_id, persisted["fixture_id"])
        self.assertNotIn(str(target.root), journal_path.read_text(encoding="utf-8"))
        self.assertEqual([], list(store.root.rglob("*.tmp")))

    def test_journal_transition_graph_rejects_skip_or_reversal(self) -> None:
        profile = self.profile()
        target = self.target(profile)
        store = LocalAdoptionStore.open(profile)
        discovered = store.create_journal(
            AdoptionOperation.ADOPT, target, "b" * 64, "tx-graph"
        )

        with self.assertRaisesRegex(ValidationError, "transition"):
            discovered.transition(TransactionState.STAGED)
        preflighted = discovered.transition(TransactionState.PREFLIGHTED)
        snapshotted = preflighted.transition(TransactionState.SNAPSHOTTED)
        staged = snapshotted.transition(
            TransactionState.STAGED,
            managed_paths=("context-os/extensions/projectos/versions/v1",),
        )
        verified = staged.transition(TransactionState.VERIFIED)
        adopted = verified.transition(TransactionState.ADOPTED)
        self.assertEqual(TransactionState.ADOPTED, adopted.state)
        with self.assertRaisesRegex(ValidationError, "transition"):
            adopted.transition(TransactionState.PREFLIGHTED)

    def test_snapshot_preserves_registry_exact_bytes_and_hashes_managed_files(self) -> None:
        profile = self.profile()
        target = self.target(profile)
        store = LocalAdoptionStore.open(profile)
        registry_bytes = b'{ "registry_version" : 1, "extensions" : {"other":{}} }\n'
        target.registry_path.write_bytes(registry_bytes)
        managed = target.extensions_root / "projectos/versions/v1/file.txt"
        managed.parent.mkdir(parents=True)
        managed.write_text("managed-definition", encoding="utf-8")
        unrelated = target.extensions_root / "other/keep.txt"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("unrelated", encoding="utf-8")

        snapshot = store.snapshot_target(target, "tx-snapshot")

        self.assertTrue(snapshot.registry_existed)
        self.assertEqual(hashlib.sha256(registry_bytes).hexdigest(), snapshot.registry_sha256)
        self.assertEqual(registry_bytes, snapshot.registry_bytes_path.read_bytes())
        self.assertEqual(1, len(snapshot.entries))
        self.assertEqual(
            "context-os/extensions/projectos/versions/v1/file.txt",
            snapshot.entries[0].path,
        )
        self.assertEqual(
            hashlib.sha256(b"managed-definition").hexdigest(),
            snapshot.entries[0].sha256,
        )
        self.assertNotIn("unrelated", snapshot.manifest_path.read_text(encoding="utf-8"))

    def test_snapshot_rejects_symlinks_and_secret_material(self) -> None:
        for case in ("symlink", "secret", "registry-secret"):
            with self.subTest(case=case):
                profile = replace(
                    self.profile(),
                    contextos_root=(self.temp_path / f"contextos-{case}").resolve(),
                )
                profile = replace(
                    profile,
                    extensions_root=Path(profile.contextos_root) / "context-os/extensions",
                    skills_root=Path(profile.contextos_root) / "skills",
                )
                target = self.target(profile)
                store = LocalAdoptionStore.open(profile)
                if case == "registry-secret":
                    target.registry_path.write_text(
                        '{"api_token":"do-not-store"}\n', encoding="utf-8"
                    )
                    managed = None
                else:
                    managed = target.extensions_root / "projectos/versions/v1"
                    managed.mkdir(parents=True)
                if case == "symlink":
                    external = self.temp_path / "external.txt"
                    external.write_text("outside", encoding="utf-8")
                    (managed / "linked.txt").symlink_to(external)
                elif case == "secret":
                    (managed / "unsafe.txt").write_text(
                        "ghp_abcdefghijklmnopqrstuvwxyz123456", encoding="utf-8"
                    )
                with self.assertRaises(ValidationError):
                    store.snapshot_target(target, f"tx-{case}")

    def test_archive_never_contains_database_lock_log_or_unrelated_contextos_files(self) -> None:
        profile = self.profile()
        target = self.target(profile)
        store = LocalAdoptionStore.open(profile)
        version = target.extensions_root / "projectos/versions/v1"
        version.mkdir(parents=True)
        (version / "manifest.json").write_text("{}\n", encoding="utf-8")
        Path(profile.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(profile.database_path).write_text("database", encoding="utf-8")
        Path(profile.lock_path).write_text("lock", encoding="utf-8")
        Path(profile.log_root).mkdir(parents=True)
        (Path(profile.log_root) / "run.log").write_text("log", encoding="utf-8")
        unrelated = target.extensions_root / "other/file.txt"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("other", encoding="utf-8")
        expected = store.inventory_managed_path(target, "projectos/versions/v1")

        archive = store.archive_managed_version(
            target, "projectos/versions/v1", expected, "tx-archive"
        )

        archived_names = {
            path.relative_to(archive).as_posix()
            for path in archive.rglob("*")
            if path.is_file()
        }
        self.assertEqual({"manifest.json"}, archived_names)
        with self.assertRaisesRegex(ValidationError, "managed version"):
            store.archive_managed_version(
                target, "other", (), "tx-unrelated"
            )


if __name__ == "__main__":
    unittest.main()
