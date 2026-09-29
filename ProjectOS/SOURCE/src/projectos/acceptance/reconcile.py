from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Sequence

from projectos.acceptance.evidence import VerifiedHostEvidence
from projectos.acceptance.model import AcceptanceManifest, SupportState
from projectos.errors import ValidationError


@dataclass(frozen=True)
class ReconciliationReport:
    support_state: SupportState
    projectos_version: str
    source_revision: str
    wheel_sha256: str
    extension_bundle_sha256: str
    package_sha256: str | None
    verified_hosts: tuple[str, ...]

    def canonical_bytes(self) -> bytes:
        value = {
            "format": "projectos-acceptance-reconciliation-v1",
            "package_sha256": self.package_sha256,
            "extension_bundle_sha256": self.extension_bundle_sha256,
            "projectos_version": self.projectos_version,
            "source_revision": self.source_revision,
            "support_state": self.support_state.value,
            "verified_hosts": list(self.verified_hosts),
            "wheel_sha256": self.wheel_sha256,
        }
        return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class AcceptanceReconciler:
    def reconcile(
        self,
        manifest: AcceptanceManifest,
        records: Sequence[VerifiedHostEvidence],
    ) -> ReconciliationReport:
        hosts = [item.record.host_family for item in records]
        if len(set(hosts)) != len(hosts):
            raise ValidationError("duplicate host acceptance records are prohibited")
        packages = {item.record.package_sha256 for item in records}
        for item in records:
            record = item.record
            if (
                record.projectos_version != manifest.projectos_version
                or record.source_revision != manifest.source_revision
                or record.wheel_sha256 != manifest.wheel.sha256
                or record.extension_bundle_sha256 != manifest.extension_bundle.sha256
                or record.manifest_sha256
                != hashlib.sha256(manifest.canonical_bytes()).hexdigest()
            ):
                raise ValidationError("host acceptance records contain a mixed release")
        if len(packages) > 1:
            raise ValidationError("host acceptance records contain a mixed release package")
        selected = frozenset(hosts)
        states = {
            frozenset(): SupportState.SIMULATED,
            frozenset({"macos"}): SupportState.MACOS_VERIFIED,
            frozenset({"windows"}): SupportState.WINDOWS_VERIFIED,
            frozenset({"macos", "windows"}): SupportState.CROSS_PLATFORM_VERIFIED,
        }
        try:
            state = states[selected]
        except KeyError as exc:
            raise ValidationError("host acceptance records contain an unsupported host") from exc
        return ReconciliationReport(
            state,
            manifest.projectos_version,
            manifest.source_revision,
            manifest.wheel.sha256,
            manifest.extension_bundle.sha256,
            next(iter(packages)) if packages else None,
            tuple(sorted(hosts)),
        )
