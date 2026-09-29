from __future__ import annotations

import unittest
from dataclasses import replace

from tests.test_acceptance_evidence import manifest, record

from projectos.acceptance.evidence import VerifiedHostEvidence
from projectos.acceptance.model import SupportState
from projectos.acceptance.reconcile import AcceptanceReconciler
from projectos.errors import ValidationError


class AcceptanceReconcileTests(unittest.TestCase):
    def verified(self, host: str) -> VerifiedHostEvidence:
        return VerifiedHostEvidence(record(host), "a" * 64, 3)

    def test_reconcile_zero_macos_windows_and_both_records_to_exact_support_states(self) -> None:
        reconciler = AcceptanceReconciler()
        release = manifest()
        self.assertEqual(SupportState.SIMULATED, reconciler.reconcile(release, ()).support_state)
        self.assertEqual(SupportState.MACOS_VERIFIED, reconciler.reconcile(release, (self.verified("macos"),)).support_state)
        self.assertEqual(SupportState.WINDOWS_VERIFIED, reconciler.reconcile(release, (self.verified("windows"),)).support_state)
        self.assertEqual(
            SupportState.CROSS_PLATFORM_VERIFIED,
            reconciler.reconcile(release, (self.verified("macos"), self.verified("windows"))).support_state,
        )

    def test_reconcile_rejects_mixed_release_or_duplicate_host_records(self) -> None:
        release = manifest()
        macos = self.verified("macos")
        with self.assertRaisesRegex(ValidationError, "duplicate"):
            AcceptanceReconciler().reconcile(release, (macos, macos))
        mixed = VerifiedHostEvidence(replace(record("windows"), package_sha256="b" * 64), "c" * 64, 3)
        with self.assertRaisesRegex(ValidationError, "release"):
            AcceptanceReconciler().reconcile(release, (macos, mixed))

        extension_mismatch = VerifiedHostEvidence(
            replace(record("windows"), extension_bundle_sha256="b" * 64), "d" * 64, 3
        )
        with self.assertRaisesRegex(ValidationError, "release"):
            AcceptanceReconciler().reconcile(release, (macos, extension_mismatch))


if __name__ == "__main__":
    unittest.main()
