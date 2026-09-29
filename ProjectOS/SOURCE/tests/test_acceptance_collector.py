from __future__ import annotations

import hashlib
import json
import unittest
import zipfile
from dataclasses import replace

import tests.test_host_acceptance_transaction as host_tests

from projectos.acceptance.collector import HostEvidenceCollector
from projectos.acceptance.model import REQUIRED_ACCEPTANCE_CASES
from projectos.acceptance.native_probe import NativeTriggerWindow
from projectos.acceptance.preparation import AcceptancePreparationRecord
from projectos.acceptance.probe import _append_event
from projectos.acceptance.transaction import HostAcceptanceTransaction
from projectos.errors import ValidationError


class AcceptanceCollectorTests(unittest.TestCase):
    def system(self, *, windows: bool = True):
        helper = host_tests.HostAcceptanceTransactionTests(
            "test_host_transaction_runs_every_state_in_exact_order"
        )
        helper.setUp()
        self.addCleanup(helper.tearDown)
        context, _events = helper.context()
        result = HostAcceptanceTransaction(context).begin()
        record = AcceptancePreparationRecord(
            context.profile.preparation_id,
            context.target.acceptance_id,
            context.target.receipt_id,
            "fixture-01",
            context.target.host_family.value,
            context.profile.release_sha256,
            "4" * 64,
            context.profile.wheel_sha256,
            context.profile.extension_bundle_sha256,
            context.profile.source_revision,
            hashlib.sha256(context.profile.canonical_bytes()).hexdigest(),
        )
        context = replace(
            context,
            preparation_record=record,
            preparation_record_bytes=record.canonical_bytes(),
            evidence_root=context.target.runtime_root / "acceptance/evidence",
            standard_user=True,
            non_elevated=True,
            structural_equivalence=True,
        )
        context.evidence_root.mkdir(parents=True, exist_ok=True)
        if windows:
            self.native_window(context, result.run_id, 1, "immediate_trigger", (
                ("COMPLETE", "SYNC_COMPLETE"),
            ))
            self.native_window(context, result.run_id, 2, "native_non_overlap", (
                ("STARTED", "BARRIER_STARTED"),
                ("LOCKED", "BARRIER_BUSY"),
                ("COMPLETE", "SYNC_COMPLETE"),
            ))
        return context, result

    def native_window(self, context, run_id, sequence, case_id, events):
        window = NativeTriggerWindow(
            f"window-{sequence}", run_id, sequence, case_id,
            context.target.receipt_id, context.profile.release_sha256,
            context.definition.sha256,
        )
        root = context.target.runtime_root / "acceptance/trigger-windows"
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{window.window_id}.json").write_bytes(window.canonical_bytes())
        for status, code in events:
            _append_event(
                context.profile, case_id, status, code,
                native_window=window.to_mapping(),
            )

    def test_collector_maps_every_required_case_from_one_typed_durable_fact(self) -> None:
        context, result = self.system()
        record = HostEvidenceCollector().collect(context, result)
        self.assertEqual(list(REQUIRED_ACCEPTANCE_CASES), [case.case_id for case in record.cases])
        self.assertTrue(all(case.status == "PASS" for case in record.cases))
        self.assertEqual(len(record.cases), len({case.code for case in record.cases}))
        self.assertEqual(
            [{f"fact_{case_id}": True} for case_id in REQUIRED_ACCEPTANCE_CASES],
            [dict(case.measurements) for case in record.cases],
        )

    def test_collector_rejects_an_unproved_named_durable_fact(self) -> None:
        context, result = self.system()
        cases = tuple(case for case in result.proved_cases if case != "skill_discovery")
        with self.assertRaisesRegex(ValidationError, "skill_discovery"):
            HostEvidenceCollector().collect(context, replace(result, proved_cases=cases))

    def test_collector_rejects_unverified_package_or_user_session(self) -> None:
        context, result = self.system()
        with self.assertRaisesRegex(ValidationError, "package_integrity"):
            HostEvidenceCollector().collect(replace(context, package_verified=False), result)
        with self.assertRaisesRegex(ValidationError, "standard_user_non_elevated"):
            HostEvidenceCollector().collect(replace(context, standard_user=False), result)

    def test_native_cases_require_matching_native_trigger_windows(self) -> None:
        context, result = self.system(windows=False)
        with self.assertRaisesRegex(ValidationError, "native trigger"):
            HostEvidenceCollector().collect(context, result)

    def test_record_binds_preparation_and_extension_bundle_hashes(self) -> None:
        context, result = self.system()
        record = HostEvidenceCollector().collect(context, result)
        self.assertEqual(context.profile.extension_bundle_sha256, record.extension_bundle_sha256)
        self.assertEqual(
            hashlib.sha256(context.preparation_record_bytes).hexdigest(),
            record.preparation_sha256,
        )

    def test_sealing_requires_absent_task_disabled_registry_rollback_and_database_health(self) -> None:
        context, result = self.system()
        context.activation_controller.active = True
        with self.assertRaisesRegex(ValidationError, "cleanup"):
            HostEvidenceCollector().seal(
                context, result, context.evidence_root / "failed.zip"
            )

    def test_collector_never_copies_commands_paths_identities_native_output_or_raw_logs(self) -> None:
        context, result = self.system()
        output = context.evidence_root / "sealed.zip"
        HostEvidenceCollector().seal(context, result, output)
        with zipfile.ZipFile(output) as archive:
            searchable = b"\n".join(archive.read(name) for name in archive.namelist()).decode()
        for forbidden in (
            str(context.target.runtime_root), "fixture-machine", "owner@example.com",
            "launchctl ", "schtasks.exe ", "stdout", "stderr", "raw log",
        ):
            self.assertNotIn(forbidden, searchable)


if __name__ == "__main__":
    unittest.main()
