from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from projectos.acceptance.evidence import AcceptanceEvidenceVerifier, VerifiedHostEvidence
from projectos.acceptance.model import AcceptanceManifest
from projectos.acceptance.package import AcceptancePackageBuilder, verify_acceptance_package
from projectos.acceptance.reconcile import AcceptanceReconciler, ReconciliationReport
from projectos.adoption.host import HostFamily
from projectos.errors import ValidationError


@dataclass(frozen=True)
class HostPreflightPlan:
    host_family: HostFamily
    definition_sha256: str
    planned_actions: tuple[tuple[str, ...], ...]
    read_only: bool


def read_acceptance_manifest(path: Path) -> AcceptanceManifest:
    try:
        content = Path(path).read_bytes()
        value = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("acceptance manifest is unavailable or invalid") from exc
    manifest = AcceptanceManifest.from_mapping(value)
    if content != manifest.canonical_bytes():
        raise ValidationError("acceptance manifest is not canonical")
    return manifest


def run_acceptance_command(arguments) -> object:
    command = arguments.command
    if command == "acceptance package build":
        return AcceptancePackageBuilder().build(
            arguments.wheel,
            arguments.extension_bundle,
            arguments.source_revision,
            arguments.created_at,
            arguments.output,
        )
    if command == "acceptance package verify":
        return verify_acceptance_package(arguments.package)
    manifest = read_acceptance_manifest(arguments.manifest)
    if command == "acceptance evidence verify":
        return AcceptanceEvidenceVerifier().verify(arguments.evidence, manifest)
    if command == "acceptance reconcile":
        records: list[VerifiedHostEvidence] = [
            AcceptanceEvidenceVerifier().verify(path, manifest)
            for path in arguments.evidence
        ]
        report = AcceptanceReconciler().reconcile(manifest, records)
        if arguments.output is not None:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_bytes(report.canonical_bytes())
        return report
    raise ValidationError("unsupported acceptance command")
