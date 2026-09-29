from __future__ import annotations

import json
import unittest
from pathlib import Path
from uuid import uuid4

from tests.helpers import TemporaryDirectoryMixin
import tests.test_skill_discovery as discovery_tests

from projectos.adoption.activation import (
    ActivationProofResult,
    RuntimeActivation,
)
from projectos.adoption.activation_store import ActivationState, LocalActivationStore
from projectos.adoption.discovery import SkillDiscoveryService
from projectos.adoption.scheduler import SchedulerAction, SchedulerState
from projectos.adoption.store import AdoptionOperation, TransactionState
from projectos.errors import ValidationError
from projectos.google.fake_gateway import FakeGoogleGateway
from projectos.runtime import RuntimeTrigger


class InjectedCrash(BaseException):
    pass


class SyncingProof:
    def __init__(self, system, *, fail: bool = False) -> None:
        self.system = system
        self.fail = fail
        self.triggers: list[str] = []

    def run(self, discovered, coordinator):
        if self.fail:
            raise ValidationError("proof failed")
        gateway = FakeGoogleGateway.from_fixture(
            {
                "contract_version": 1,
                "tabs": {},
                "requests": [],
                "access_events": [],
                "write_ready": True,
            }
        )
        statuses = []
        for trigger in (RuntimeTrigger.SCHEDULER, RuntimeTrigger.SKILL):
            result = coordinator.run(
                self.system["profile_path"],
                Path(self.system["profile"].database_path),
                trigger,
                gateway,
                wait_seconds=0,
            )
            self.triggers.append(trigger.value)
            statuses.append(result.status)
        return ActivationProofResult(
            True,
            tuple(self.triggers),
            tuple(statuses),
            None,
        )


class ActivationTransactionTests(TemporaryDirectoryMixin, unittest.TestCase):
    manifest = discovery_tests.SkillDiscoveryTests.manifest
    _profile = discovery_tests.SkillDiscoveryTests._profile
    _database_and_config = discovery_tests.SkillDiscoveryTests._database_and_config
    system = discovery_tests.SkillDiscoveryTests.system

    def activation_system(self, name: str, *, proof_fail: bool = False):
        system = self.system(
            name,
            enable_registry=False,
            enable_scheduler=False,
        )
        transaction_id = str(uuid4())
        store = system["store"]
        store.transaction_root(transaction_id).mkdir(parents=True)
        journal = store.create_journal(
            AdoptionOperation.ADOPT,
            system["target"],
            system["staged"].bundle_sha256,
            transaction_id,
        )
        managed = system["installed_root"].relative_to(system["target"].root).as_posix()
        for state in (
            TransactionState.PREFLIGHTED,
            TransactionState.SNAPSHOTTED,
            TransactionState.STAGED,
            TransactionState.VERIFIED,
            TransactionState.ADOPTED,
        ):
            journal = journal.transition(
                state,
                managed_paths=(managed,) if state is TransactionState.STAGED else None,
            )
        store.save_journal(journal)
        proof = SyncingProof(system, fail=proof_fail)
        system["definition_transaction_id"] = transaction_id
        system["proof"] = proof
        return system

    def activation(self, system, *, hook=lambda name: None):
        return RuntimeActivation(
            system["target"],
            system["profile_path"],
            system["store"],
            system["runner"],
            system["policy"],
            system["proof"],
            boundary_hook=hook,
        )

    def activation_id(self, system) -> str:
        activation_store = LocalActivationStore.open(system["store"])
        roots = [path for path in activation_store.root.iterdir() if path.is_dir()]
        self.assertEqual(1, len(roots))
        return roots[0].name

    def test_activation_requires_completed_matching_phase3b_transaction(self) -> None:
        system = self.activation_system("requires-definition")
        with self.assertRaisesRegex(ValidationError, "definition transaction"):
            self.activation(system).begin(str(uuid4()))

        journal = system["store"].load_journal(system["definition_transaction_id"])
        system["store"].save_journal(journal.__class__(
            journal.transaction_id,
            journal.operation,
            TransactionState.FAILED,
            journal.fixture_id,
            journal.bundle_sha256,
            journal.managed_paths,
            ("failed",),
            journal.created_at,
            journal.updated_at,
        ))
        with self.assertRaisesRegex(ValidationError, "completed"):
            self.activation(system).begin(system["definition_transaction_id"])

    def test_activation_requires_ordered_preflight_stage_runtime_scheduler_skill_proof(self) -> None:
        system = self.activation_system("ordered")
        boundaries: list[str] = []

        result = self.activation(system, hook=boundaries.append).begin(
            system["definition_transaction_id"]
        )

        self.assertEqual(ActivationState.PROVED, result.state)
        self.assertEqual(
            [
                "after_preflight",
                "after_scheduler_stage",
                "after_runtime_verify",
                "after_scheduler_enable",
                "before_registry_replace",
                "after_registry_replace",
                "after_skill_enable",
                "after_proof",
            ],
            boundaries,
        )

    def test_existing_activation_callers_still_generate_ids(self) -> None:
        system = self.activation_system("generated-id")
        result = self.activation(system).begin(system["definition_transaction_id"])
        self.assertRegex(result.activation_id, r"^[0-9a-f-]{36}$")


    def test_activation_enables_scheduler_before_atomically_enabling_only_projectos(self) -> None:
        system = self.activation_system("ordering")
        registry_before = system["target"].registry_path.read_bytes()
        observed = []

        def hook(name: str) -> None:
            if name == "before_registry_replace":
                inspection = system["runner"].inspect(system["definition"])
                registry = json.loads(system["target"].registry_path.read_text())
                observed.append((inspection.state, registry["extensions"]["projectos"]["enabled"]))

        result = self.activation(system, hook=hook).begin(
            system["definition_transaction_id"]
        )
        registry_after = json.loads(system["target"].registry_path.read_text())

        self.assertEqual(ActivationState.PROVED, result.state)
        self.assertEqual([(SchedulerState.ENABLED, False)], observed)
        before = json.loads(registry_before)
        before["extensions"]["projectos"]["enabled"] = True
        self.assertEqual(before, registry_after)

    def test_activation_proof_resolves_skill_and_runs_both_triggers_with_fake_gateway(self) -> None:
        system = self.activation_system("proof")

        result = self.activation(system).begin(system["definition_transaction_id"])

        self.assertEqual(ActivationState.PROVED, result.state)
        self.assertEqual(["scheduler", "skill"], system["proof"].triggers)
        proof = LocalActivationStore.open(system["store"]).load_proof(result.activation_id)
        self.assertEqual(("COMPLETE", "COMPLETE"), proof.statuses)

    def test_failure_before_and_after_registry_enable_restores_exact_disabled_bytes_first(self) -> None:
        for boundary in ("before_registry_replace", "after_registry_replace"):
            with self.subTest(boundary=boundary):
                system = self.activation_system(f"crash-{boundary}")
                disabled = system["target"].registry_path.read_bytes()

                def hook(name: str) -> None:
                    if name == boundary:
                        raise InjectedCrash(name)

                with self.assertRaises(InjectedCrash):
                    self.activation(system, hook=hook).begin(
                        system["definition_transaction_id"]
                    )
                activation_id = self.activation_id(system)
                recovered = self.activation(system).recover(activation_id)

                self.assertEqual(ActivationState.ROLLED_BACK, recovered.state)
                self.assertEqual(disabled, system["target"].registry_path.read_bytes())
                self.assertEqual(
                    SchedulerState.ABSENT,
                    system["runner"].inspect(system["definition"]).state,
                )

    def test_resume_after_registry_replace_completes_activation(self) -> None:
        system = self.activation_system("resume-after-registry")

        def hook(name: str) -> None:
            if name == "after_registry_replace":
                raise InjectedCrash(name)

        with self.assertRaises(InjectedCrash):
            self.activation(system, hook=hook).begin(
                system["definition_transaction_id"]
            )
        activation_id = self.activation_id(system)

        resumed = self.activation(system).resume(activation_id)

        self.assertEqual(ActivationState.PROVED, resumed.state)

    def test_scheduler_enabled_then_skill_or_proof_failure_leaves_no_discovery_or_active_fixture(self) -> None:
        skill = self.activation_system("skill-failure")

        def corrupt_skill(name: str) -> None:
            if name == "after_scheduler_enable":
                (skill["installed_root"] / "skills/projectos/SKILL.md").write_text(
                    "changed", encoding="utf-8"
                )

        with self.assertRaises(ValidationError):
            self.activation(skill, hook=corrupt_skill).begin(
                skill["definition_transaction_id"]
            )
        proof = self.activation_system("proof-failure", proof_fail=True)
        with self.assertRaises(ValidationError):
            self.activation(proof).begin(proof["definition_transaction_id"])

        for system in (skill, proof):
            result = SkillDiscoveryService().resolve(
                system["target"],
                system["profile_path"],
                system["store"],
                system["runner"],
                system["policy"],
            )
            self.assertFalse(result.ok)
            self.assertEqual(
                SchedulerState.ABSENT,
                system["runner"].inspect(system["definition"]).state,
            )

    def test_recovery_at_every_activation_boundary_is_idempotent(self) -> None:
        boundaries = (
            "after_preflight",
            "after_scheduler_stage",
            "after_runtime_verify",
            "after_scheduler_enable",
            "before_registry_replace",
            "after_registry_replace",
            "after_skill_enable",
        )
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                system = self.activation_system(f"recover-{boundary}")
                disabled = system["target"].registry_path.read_bytes()

                def hook(name: str) -> None:
                    if name == boundary:
                        raise InjectedCrash(name)

                with self.assertRaises(InjectedCrash):
                    self.activation(system, hook=hook).begin(
                        system["definition_transaction_id"]
                    )
                activation_id = self.activation_id(system)
                first = self.activation(system).recover(activation_id)
                second = self.activation(system).recover(activation_id)
                self.assertEqual(ActivationState.ROLLED_BACK, first.state)
                self.assertEqual(first, second)
                self.assertEqual(disabled, system["target"].registry_path.read_bytes())

    def test_deactivation_disables_discovery_before_scheduler_teardown(self) -> None:
        system = self.activation_system("deactivate")
        activated = self.activation(system).begin(system["definition_transaction_id"])
        observed = []

        def hook(name: str) -> None:
            if name == "before_scheduler_disable":
                discovery = SkillDiscoveryService().resolve(
                    system["target"],
                    system["profile_path"],
                    system["store"],
                    system["runner"],
                    system["policy"],
                )
                observed.append((discovery.diagnostic.code, system["runner"].inspect(system["definition"]).state))

        deactivated = self.activation(system, hook=hook).deactivate(
            activated.activation_id
        )

        self.assertEqual(ActivationState.DEACTIVATED, deactivated.state)
        self.assertEqual([("REGISTRY_DISABLED", SchedulerState.ENABLED)], observed)
        self.assertEqual(SchedulerState.ABSENT, system["runner"].inspect(system["definition"]).state)

    def test_activation_journal_contains_only_bounded_local_metadata(self) -> None:
        system = self.activation_system("metadata")
        result = self.activation(system).begin(system["definition_transaction_id"])
        activation_store = LocalActivationStore.open(system["store"])
        root = activation_store.activation_root(result.activation_id)
        journal = (root / "journal.json").read_text(encoding="utf-8")

        self.assertNotIn(str(system["target"].root), journal)
        self.assertNotIn(str(system["profile"].database_path), journal)
        self.assertNotIn("owner@example.com", journal)
        self.assertNotIn("sheet-discovery", journal)
        self.assertNotIn("credential", journal.lower())
        self.assertLess(len(journal), 4096)


if __name__ == "__main__":
    unittest.main()
