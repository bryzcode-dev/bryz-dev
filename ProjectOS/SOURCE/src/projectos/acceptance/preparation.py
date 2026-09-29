from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from projectos.acceptance.authority import (
    ACCEPTANCE_ACKNOWLEDGEMENT,
    ACCEPTANCE_MARKER,
    AcceptanceTarget,
    HostSession,
    _receipt_path,
)
from projectos.acceptance.package import AcceptancePackage, verify_acceptance_package
from projectos.acceptance.profile import AcceptanceProfile
from projectos.acceptance.store import LocalAcceptanceStore
from projectos.adoption.contextos import ContextOSLocator
from projectos.adoption.fixture import FixtureInstallationTarget
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, machine_profile_from_mapping
from projectos.errors import ValidationError


_FORMAT = "projectos-acceptance-preparation-v1"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_profile(path: Path) -> MachineProfile:
    try:
        content = Path(path).read_bytes()
        value = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("machine profile is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValidationError("machine profile is unavailable or invalid")
    return machine_profile_from_mapping(value)


@dataclass(frozen=True)
class AcceptancePreparationRequest:
    acceptance_root: Path
    runtime_root: Path
    fixture_root: Path
    machine_profile: Path
    package: Path
    evidence_root: Path
    acceptance_ack: str
    fixture_ack: str


@dataclass(frozen=True)
class AcceptancePreparationRecord:
    preparation_id: str
    acceptance_id: str
    receipt_id: str
    fixture_id: str
    host_family: str
    package_sha256: str
    manifest_sha256: str
    wheel_sha256: str
    extension_bundle_sha256: str
    source_revision: str
    profile_sha256: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "acceptance_id": self.acceptance_id,
            "extension_bundle_sha256": self.extension_bundle_sha256,
            "fixture_id": self.fixture_id,
            "format": _FORMAT,
            "host_family": self.host_family,
            "manifest_sha256": self.manifest_sha256,
            "package_sha256": self.package_sha256,
            "preparation_id": self.preparation_id,
            "profile_sha256": self.profile_sha256,
            "receipt_id": self.receipt_id,
            "source_revision": self.source_revision,
            "wheel_sha256": self.wheel_sha256,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AcceptancePreparationRecord:
        expected = {
            "acceptance_id", "extension_bundle_sha256", "fixture_id", "format",
            "host_family", "manifest_sha256", "package_sha256", "preparation_id",
            "profile_sha256", "receipt_id", "source_revision", "wheel_sha256",
        }
        if set(value) != expected or value.get("format") != _FORMAT:
            raise ValidationError("acceptance preparation fields are invalid")
        for field in (
            "extension_bundle_sha256", "manifest_sha256", "package_sha256",
            "profile_sha256", "wheel_sha256",
        ):
            digest = value.get(field)
            if not isinstance(digest, str) or len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValidationError("acceptance preparation digest is invalid")
        if value.get("host_family") not in {item.value for item in HostFamily}:
            raise ValidationError("acceptance preparation host is invalid")
        return cls(
            str(value["preparation_id"]), str(value["acceptance_id"]),
            str(value["receipt_id"]), str(value["fixture_id"]), str(value["host_family"]),
            str(value["package_sha256"]), str(value["manifest_sha256"]),
            str(value["wheel_sha256"]), str(value["extension_bundle_sha256"]),
            str(value["source_revision"]), str(value["profile_sha256"]),
        )


@dataclass(frozen=True)
class PreparedAcceptance:
    target: AcceptanceTarget
    profile: AcceptanceProfile
    store: LocalAcceptanceStore
    package: AcceptancePackage
    record: AcceptancePreparationRecord
    record_path: Path
    staged_extension_bundle: Path
    evidence_root: Path
    fixture_target: FixtureInstallationTarget


class AcceptancePreparer:
    @classmethod
    def boundaries(cls) -> tuple[str, ...]:
        return ("after_authority", "after_bundle", "after_profile", "after_record")

    def _validate_inputs(
        self,
        request: AcceptancePreparationRequest,
        session: HostSession,
        *,
        require_empty_evidence: bool,
    ) -> tuple[AcceptancePackage, MachineProfile, FixtureInstallationTarget, Path]:
        if request.acceptance_ack != ACCEPTANCE_ACKNOWLEDGEMENT:
            raise ValidationError("clean-host acknowledgement is invalid")
        if request.fixture_ack != "FIXTURE_ONLY":
            raise ValidationError("fixture acknowledgement is invalid")
        if session.elevated or not session.standard_user:
            raise ValidationError("acceptance preparation rejects an elevated session")
        package = verify_acceptance_package(request.package)
        if session.host_family.value not in package.manifest.supported_hosts:
            raise ValidationError("acceptance package does not support this host")
        profile = _read_profile(request.machine_profile)
        if profile.host_family is not session.host_family:
            raise ValidationError("machine profile host does not match session")
        if Path(str(profile.contextos_root)).resolve(strict=False) != Path(
            request.fixture_root
        ).resolve(strict=False):
            raise ValidationError("machine profile does not reference the fixture")
        if Path(str(profile.runtime_root)).resolve(strict=False) != Path(
            request.runtime_root
        ).resolve(strict=False):
            raise ValidationError("machine profile runtime does not match acceptance runtime")
        installation = ContextOSLocator(
            profile.host_family, dict(os.environ), Path.home()
        ).inspect(request.fixture_root)
        fixture_target = FixtureInstallationTarget.open(
            installation, profile.runtime_root, request.fixture_ack
        )
        evidence = Path(request.evidence_root).resolve(strict=False)
        runtime = Path(request.runtime_root).resolve(strict=False)
        if (
            not evidence.is_dir()
            or evidence.is_symlink()
            or evidence == runtime
            or runtime not in evidence.parents
            or require_empty_evidence and any(evidence.iterdir())
        ):
            raise ValidationError("evidence root must be a new empty local directory")
        return package, profile, fixture_target, evidence

    def prepare(
        self,
        request: AcceptancePreparationRequest,
        *,
        session: HostSession,
        boundary_hook: Callable[[str], None] = lambda name: None,
    ) -> PreparedAcceptance:
        package, machine_profile, fixture_target, evidence = self._validate_inputs(
            request, session, require_empty_evidence=True
        )
        target: AcceptanceTarget | None = None
        staged = Path(request.runtime_root) / "acceptance/staging/projectos-extension.zip"
        profile_path = Path(request.runtime_root) / "acceptance/state/acceptance-profile.json"
        record_path = Path(request.runtime_root) / "acceptance/state/preparation.json"
        try:
            target = AcceptanceTarget.issue(
                request.acceptance_root,
                request.runtime_root,
                machine_profile.host_family,
                excluded_roots=(request.fixture_root,),
            )
            boundary_hook("after_authority")
            package.extract_extension_bundle(staged)
            boundary_hook("after_bundle")
            preparation_id = str(uuid4())
            profile = AcceptanceProfile.from_machine_profile(
                machine_profile,
                target,
                source_revision=package.manifest.source_revision,
                release_sha256=package.sha256,
                wheel_sha256=package.manifest.wheel.sha256,
                extension_bundle_sha256=package.manifest.extension_bundle.sha256,
                preparation_id=preparation_id,
                definition_transaction_id=str(uuid4()),
                activation_id=str(uuid4()),
            )
            store = LocalAcceptanceStore.open(target, profile)
            written_profile = store.save_profile(profile)
            boundary_hook("after_profile")
            record = AcceptancePreparationRecord(
                preparation_id,
                target.acceptance_id,
                target.receipt_id,
                fixture_target.fixture_id,
                target.host_family.value,
                package.sha256,
                _sha256(package.manifest.canonical_bytes()),
                package.manifest.wheel.sha256,
                package.manifest.extension_bundle.sha256,
                package.manifest.source_revision,
                _sha256(profile.canonical_bytes()),
            )
            written_record = store.save_preparation(record.canonical_bytes())
            boundary_hook("after_record")
            return PreparedAcceptance(
                target, profile, store, package, record, written_record, staged,
                evidence, fixture_target,
            )
        except Exception:
            for path in (record_path, profile_path, staged):
                path.unlink(missing_ok=True)
            if target is not None:
                (target.root / ACCEPTANCE_MARKER).unlink(missing_ok=True)
                _receipt_path(target.runtime_root, target.receipt_id).unlink(missing_ok=True)
                try:
                    target.root.rmdir()
                except OSError:
                    pass
            for directory in (
                staged.parent,
                profile_path.parent,
                Path(request.runtime_root) / "acceptance/receipts",
            ):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise

    def open(
        self,
        request: AcceptancePreparationRequest,
        *,
        session: HostSession,
    ) -> PreparedAcceptance:
        package, machine_profile, fixture_target, evidence = self._validate_inputs(
            request, session, require_empty_evidence=False
        )
        target = AcceptanceTarget.open(
            request.acceptance_root,
            request.runtime_root,
            request.acceptance_ack,
            session,
            excluded_roots=(request.fixture_root,),
        )
        provisional = AcceptanceProfile.from_machine_profile(
            machine_profile,
            target,
            source_revision=package.manifest.source_revision,
            release_sha256=package.sha256,
            wheel_sha256=package.manifest.wheel.sha256,
            extension_bundle_sha256=package.manifest.extension_bundle.sha256,
            preparation_id="open-placeholder",
            definition_transaction_id="open-placeholder",
            activation_id="open-placeholder",
        )
        store = LocalAcceptanceStore.open(target, provisional)
        profile = store.load_profile()
        store = LocalAcceptanceStore.open(target, profile)
        content = store.load_preparation_bytes()
        try:
            mapping = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValidationError("acceptance preparation is invalid") from exc
        if not isinstance(mapping, dict):
            raise ValidationError("acceptance preparation is invalid")
        record = AcceptancePreparationRecord.from_mapping(mapping)
        if content != record.canonical_bytes():
            raise ValidationError("acceptance preparation is not canonical")
        staged = target.runtime_root / "acceptance/staging/projectos-extension.zip"
        if (
            record.acceptance_id != target.acceptance_id
            or record.receipt_id != target.receipt_id
            or record.fixture_id != fixture_target.fixture_id
            or record.package_sha256 != package.sha256
            or record.profile_sha256 != _sha256(profile.canonical_bytes())
            or profile.preparation_id != record.preparation_id
            or profile.extension_bundle_sha256 != record.extension_bundle_sha256
            or not staged.is_file()
            or _sha256(staged.read_bytes()) != record.extension_bundle_sha256
        ):
            raise ValidationError("acceptance preparation binding is invalid")
        return PreparedAcceptance(
            target, profile, store, package, record, store.preparation_path,
            staged, evidence, fixture_target,
        )
