from __future__ import annotations

import unittest
from dataclasses import replace

from tests.test_acceptance_preparation import AcceptancePreparationTests
from tests.test_skill_discovery import SkillDiscoveryTests

from projectos.acceptance.host_context import HostAcceptanceContextFactory
from projectos.acceptance.native import RecordingProcessExecutor
from projectos.errors import ValidationError


class AcceptanceHostContextTests(unittest.TestCase):
    def system(self, suffix: str = ""):
        helper = AcceptancePreparationTests(
            "test_prepare_binds_package_wheel_extension_source_profile_and_host"
        )
        helper.setUp()
        self.addCleanup(helper.tearDown)
        request, profile = helper.system(suffix)
        SkillDiscoveryTests._database_and_config(self, profile)
        prepared = helper.prepare(request)
        return helper, request, prepared

    def test_preflight_constructs_no_subprocess_executor_and_returns_exact_actions(self) -> None:
        helper, request, prepared = self.system("-preflight")
        calls = []
        factory = HostAcceptanceContextFactory()
        result = factory.preflight(
            request, session=helper.session(), executor_factory=lambda: calls.append(True)
        )
        self.assertEqual([], calls)
        self.assertEqual(prepared.profile.machine_profile.host_family, result.plan.host_family)
        self.assertTrue(result.plan.read_only)
        self.assertEqual(prepared.profile, result.prepared.profile)
        verbs = [argv[1] for argv in result.plan.planned_actions]
        self.assertEqual(
            ["print", "bootstrap", "enable", "kickstart", "print", "print-disabled", "disable", "bootout"],
            verbs,
        )

    def test_run_constructs_executor_only_after_complete_preflight(self) -> None:
        helper, request, _ = self.system("-executor")
        calls = []

        def executor_factory():
            calls.append("constructed")
            return RecordingProcessExecutor()

        with self.assertRaises(ValidationError):
            HostAcceptanceContextFactory().execution(
                replace(request, package=request.package.with_name("missing.zip")),
                executor_factory,
                session=helper.session(),
            )
        self.assertEqual([], calls)
        context = HostAcceptanceContextFactory().execution(
            request, executor_factory, session=helper.session()
        )
        self.assertEqual(["constructed"], calls)
        self.assertFalse(context.definition_controller.active)
        self.assertFalse(context.activation_controller.active)

    def test_recover_reconstructs_all_ownership_from_durable_state(self) -> None:
        helper, request, prepared = self.system("-reconstruct")
        factory = HostAcceptanceContextFactory()
        first = factory.execution(
            request, RecordingProcessExecutor, session=helper.session()
        )
        second = factory.execution(
            request, RecordingProcessExecutor, session=helper.session()
        )
        self.assertIsNot(first.definition_controller, second.definition_controller)
        self.assertEqual(
            prepared.profile.definition_transaction_id,
            second.definition_controller.transaction_id,
        )
        self.assertEqual(
            prepared.profile.activation_id,
            second.activation_controller.activation_id,
        )


if __name__ == "__main__":
    unittest.main()
