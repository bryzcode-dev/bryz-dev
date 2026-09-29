from __future__ import annotations

import unittest
from pathlib import Path

import tests.test_activation_transaction as activation_tests
import tests.test_adoption_transaction as adoption_tests

from projectos.acceptance.controllers import (
    ActivationAcceptanceController,
    DefinitionAcceptanceController,
)
from projectos.adoption.activation import RuntimeActivation
from projectos.adoption.bundle import ArtifactPolicy
from projectos.adoption.registry import ExtensionRegistry
from projectos.adoption.store import LocalAdoptionStore, TransactionState
from projectos.errors import ValidationError


class AcceptanceControllerTests(unittest.TestCase):
    def adoption_system(self, suffix: str):
        helper = adoption_tests.AdoptionTransactionTests("test_adopt_requires_ordered_discover_preflight_snapshot_stage_verify")
        helper.setUp()
        self.addCleanup(helper.tearDown)
        profile, target, store = helper.environment(suffix)
        bundle = helper.bundle(suffix, "0.1.0")
        return helper, profile, target, store, bundle

    def activation_system(self, suffix: str):
        helper = activation_tests.ActivationTransactionTests("test_activation_requires_ordered_preflight_stage_runtime_scheduler_skill_proof")
        helper.setUp()
        self.addCleanup(helper.tearDown)
        return helper, helper.activation_system(suffix)

    def test_definition_controller_runs_existing_adoption_states_with_prepared_id(self) -> None:
        _, profile, target, store, bundle = self.adoption_system("definition")
        controller = DefinitionAcceptanceController(
            target, profile, store, ArtifactPolicy(()), "prepared-definition", bundle
        )
        self.assertFalse(controller.active)
        controller.adopt()
        self.assertTrue(controller.active)
        self.assertEqual(
            TransactionState.ADOPTED,
            store.load_journal("prepared-definition").state,
        )
        controller.rollback()
        self.assertFalse(controller.active)

    def test_activation_controller_runs_existing_activation_states_with_prepared_id(self) -> None:
        helper, system = self.activation_system("activation")
        runtime = helper.activation(system)
        controller = ActivationAcceptanceController(
            runtime, system["definition_transaction_id"], "prepared-activation"
        )
        controller.activate()
        self.assertTrue(controller.active)
        self.assertEqual("prepared-activation", runtime.result().activation_id)
        controller.deactivate()
        self.assertFalse(controller.active)

    def test_controllers_reconstruct_active_state_from_persisted_journals(self) -> None:
        _, profile, target, store, bundle = self.adoption_system("reconstruct")
        first = DefinitionAcceptanceController(
            target, profile, store, ArtifactPolicy(()), "definition-reconstruct", bundle
        )
        first.adopt()
        second = DefinitionAcceptanceController(
            target, profile, LocalAdoptionStore.open(profile), ArtifactPolicy(()),
            "definition-reconstruct", bundle,
        )
        self.assertTrue(second.active)

    def test_controller_recovery_is_idempotent_after_process_reconstruction(self) -> None:
        _, profile, target, store, bundle = self.adoption_system("recover")
        controller = DefinitionAcceptanceController(
            target, profile, store, ArtifactPolicy(()), "definition-recover", bundle
        )
        controller.adopt()
        controller.rollback()
        reconstructed = DefinitionAcceptanceController(
            target, profile, LocalAdoptionStore.open(profile), ArtifactPolicy(()),
            "definition-recover", bundle,
        )
        reconstructed.rollback()
        self.assertFalse(reconstructed.active)

    def test_controller_recovery_stops_on_registry_inventory_release_or_id_mismatch(self) -> None:
        _, profile, target, store, bundle = self.adoption_system("mismatch")
        controller = DefinitionAcceptanceController(
            target, profile, store, ArtifactPolicy(()), "definition-mismatch", bundle
        )
        controller.adopt()
        entry = ExtensionRegistry.load(target.registry_path).projectos_entry()
        installed = target.extensions_root / entry.manifest.removesuffix("/manifest.json")
        (installed / "skills/projectos/SKILL.md").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "inventory"):
            controller.rollback()
        _, profile2, target2, store2, bundle2 = self.adoption_system("release")
        release = DefinitionAcceptanceController(
            target2, profile2, store2, ArtifactPolicy(()), "definition-release", bundle2
        )
        release.adopt()
        bundle2.write_bytes(bundle2.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValidationError, "bundle"):
            release.rollback()
        helper, system = self.activation_system("id-mismatch")
        activation = helper.activation(system)
        prepared = ActivationAcceptanceController(
            activation, system["definition_transaction_id"], "prepared-id-mismatch"
        )
        prepared.activate()
        wrong = ActivationAcceptanceController(
            helper.activation(system), "different-definition", "prepared-id-mismatch"
        )
        with self.assertRaisesRegex(ValidationError, "reused"):
            wrong.activate()


if __name__ == "__main__":
    unittest.main()
