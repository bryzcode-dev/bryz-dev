from __future__ import annotations

import hashlib
import unittest

from tests import helpers as _helpers  # noqa: F401 - installs the local src path

from projectos.google.bootstrap import WorkbookBootstrapPlanner
from projectos.google.contract import (
    WorkbookContract,
    WorkbookSnapshot,
    canonical_json_bytes,
    contract_hash,
)


class WorkbookContractTests(unittest.TestCase):
    def test_contract_v1_has_exact_tabs_headers_and_visibility_classes(self) -> None:
        contract = WorkbookContract.current()
        self.assertEqual(1, contract.version)
        self.assertEqual(
            (
                "_ProjectOS_Schema",
                "_ProjectOS_Sync",
                "Users",
                "Projects",
                "Locations",
                "Resources",
                "Deployments",
                "Connections",
                "Credential_References",
                "Looker_Assets",
                "Looker_Relationships",
                "Looker_Findings",
                "Looker_Analytics",
                "Change_Requests",
                "Owner_Drafts",
                "Access_Events",
                "Conflicts",
                "Audit_Summary",
            ),
            tuple(tab.name for tab in contract.tabs),
        )
        self.assertEqual("PUBLIC_FILTERED", contract.tab("Projects").exposure)
        self.assertTrue(all(contract.tab(name).exposure == "PUBLIC_FILTERED" for name in ("Looker_Assets", "Looker_Relationships", "Looker_Findings", "Looker_Analytics")))
        self.assertEqual("OWNER_ONLY", contract.tab("Credential_References").exposure)
        self.assertEqual("INTERNAL", contract.tab("Access_Events").exposure)

    def test_canonical_hash_matches_cross_language_golden_fixture(self) -> None:
        value = {"z": 1, "a": [3, {"x": "é"}]}
        expected_json = '{"a":[3,{"x":"é"}],"z":1}'.encode()
        self.assertEqual(expected_json, canonical_json_bytes(value))
        self.assertEqual(
            "02409bf80db1e51eeb7bdcf03f1d58fb3027fd9b83d8e901532b498522672dea",
            hashlib.sha256(canonical_json_bytes(value)).hexdigest(),
        )
        self.assertEqual(64, len(contract_hash(WorkbookContract.current())))

    def test_empty_workbook_plan_creates_without_mutating(self) -> None:
        contract = WorkbookContract.current()
        snapshot = WorkbookSnapshot(contract_version=None, tabs={})
        plan = WorkbookBootstrapPlanner().plan(snapshot, contract)
        self.assertEqual(len(contract.tabs), len([a for a in plan.actions if a.kind == "CREATE_TAB"]))
        self.assertFalse(snapshot.tabs)
        self.assertFalse(plan.blocked)

    def test_compliant_workbook_plan_is_noop(self) -> None:
        contract = WorkbookContract.current()
        snapshot = WorkbookSnapshot(
            contract_version=1,
            tabs={tab.name: (tab.headers, 0) for tab in contract.tabs},
        )
        plan = WorkbookBootstrapPlanner().plan(snapshot, contract)
        self.assertEqual((), plan.actions)
        self.assertFalse(plan.blocked)

    def test_reordered_or_missing_headers_are_explicit_drift(self) -> None:
        contract = WorkbookContract.current()
        expected = contract.tab("Projects").headers
        snapshot = WorkbookSnapshot(
            contract_version=1,
            tabs={"Projects": ((expected[1], expected[0]), 0)},
        )
        plan = WorkbookBootstrapPlanner().plan(snapshot, contract)
        action = next(a for a in plan.actions if a.tab == "Projects")
        self.assertEqual("BLOCKING_HEADER_DRIFT", action.kind)
        self.assertTrue(plan.blocked)

    def test_unknown_populated_tab_is_never_repurposed(self) -> None:
        plan = WorkbookBootstrapPlanner().plan(
            WorkbookSnapshot(contract_version=1, tabs={"Mystery": (("value",), 4)}),
            WorkbookContract.current(),
        )
        action = next(a for a in plan.actions if a.tab == "Mystery")
        self.assertEqual("UNKNOWN_DATA", action.kind)
        self.assertTrue(action.blocking)

    def test_owner_drafts_access_events_and_request_columns_match_spec(self) -> None:
        contract = WorkbookContract.current()
        requests = contract.tab("Change_Requests").headers
        self.assertEqual(
            (
                "request_id",
                "request_schema_version",
                "actor_email",
                "actor_role_claim",
                "entity_type",
                "entity_id",
                "operation",
                "base_version",
                "changes_json",
                "submitted_at",
                "client_request_hash",
                "gas_deployment_id",
                "status",
                "result_code",
                "result_message",
                "current_version",
                "resolved_at",
                "publication_revision",
            ),
            requests,
        )
        self.assertIn("submitted_request_id", contract.tab("Owner_Drafts").headers)
        self.assertEqual(
            ("event_id", "actor_email", "accessed_at", "payload_hash"),
            contract.tab("Access_Events").headers,
        )


if __name__ == "__main__":
    unittest.main()
