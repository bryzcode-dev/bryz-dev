from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from projectos.acceptance.model import REQUIRED_ACCEPTANCE_CASES, AcceptanceManifest
from projectos.errors import ValidationError
from projectos.validation import reject_secret_material


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\")
_POSIX_PATH = re.compile(r"(?:^|[\s\"'])/(?:Users|home|Volumes|private|var|tmp)/")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValidationError(f"{field} is invalid")
    return value


def _portable(name: str) -> str:
    if not name or "\\" in name:
        raise ValidationError("evidence path must be portable and relative")
    posix = PurePosixPath(name)
    windows = PureWindowsPath(name)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or any(
        part in {"", ".", ".."} for part in posix.parts
    ):
        raise ValidationError("evidence path must be portable and relative")
    return posix.as_posix()


def _inspect(name: str, content: bytes) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"evidence member {name} must be UTF-8 text") from exc
    reject_secret_material(text)
    if _EMAIL.search(text) or _WINDOWS_PATH.search(text) or _POSIX_PATH.search(text):
        raise ValidationError(f"evidence member {name} contains private data")
    lowered = text.casefold()
    if any(term in lowered for term in ("launchctl ", "schtasks.exe ", "native_stdout", "native_stderr")):
        raise ValidationError(f"evidence member {name} contains prohibited native output")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


@dataclass(frozen=True)
class AcceptanceCaseResult:
    sequence: int
    case_id: str
    status: str
    code: str
    execution: str
    started_at: str
    ended_at: str
    measurements: Mapping[str, int | bool]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "code": self.code,
            "ended_at": self.ended_at,
            "execution": self.execution,
            "measurements": dict(self.measurements),
            "sequence": self.sequence,
            "started_at": self.started_at,
            "status": self.status,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> AcceptanceCaseResult:
        expected = {"case_id", "code", "ended_at", "execution", "measurements", "sequence", "started_at", "status"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValidationError("acceptance case fields are invalid")
        measurements = value["measurements"]
        if not isinstance(measurements, dict) or any(
            not isinstance(key, str) or type(item) not in {int, bool}
            for key, item in measurements.items()
        ):
            raise ValidationError("acceptance case measurements are invalid")
        if type(value["sequence"]) is not int or value["sequence"] < 1:
            raise ValidationError("acceptance case sequence is invalid")
        for field in ("started_at", "ended_at"):
            if not isinstance(value[field], str) or _TIMESTAMP.fullmatch(value[field]) is None:
                raise ValidationError("acceptance case timestamp is invalid")
        return cls(
            value["sequence"], str(value["case_id"]), str(value["status"]), str(value["code"]),
            str(value["execution"]), value["started_at"], value["ended_at"], dict(measurements),
        )


@dataclass(frozen=True)
class EvidenceAttachment:
    path: str
    sha256: str
    size: int

    def to_mapping(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}

    @classmethod
    def from_mapping(cls, value: Any) -> EvidenceAttachment:
        if not isinstance(value, dict) or set(value) != {"path", "sha256", "size"}:
            raise ValidationError("evidence attachment fields are invalid")
        if type(value["size"]) is not int or value["size"] < 0:
            raise ValidationError("evidence attachment size is invalid")
        return cls(_portable(str(value["path"])), _digest(value["sha256"], "attachment sha256"), value["size"])


@dataclass(frozen=True)
class HostAcceptanceRecord:
    format: str
    projectos_version: str
    source_revision: str
    wheel_sha256: str
    extension_bundle_sha256: str
    package_sha256: str
    manifest_sha256: str
    preparation_sha256: str
    definition_sha256: str
    host_family: str
    os_version: str
    architecture: str
    python_version: str
    acceptance_run_id: str
    standard_user: bool
    non_elevated: bool
    cases: tuple[AcceptanceCaseResult, ...]
    scheduler_states: tuple[str, ...]
    activation_terminal_state: str
    definition_terminal_state: str
    cleanup_complete: bool
    task_absent: bool
    registry_disabled: bool
    excluded_artifacts: tuple[str, ...]
    attachments: tuple[EvidenceAttachment, ...]

    def validate(self) -> None:
        if self.format != "projectos-host-acceptance-v2":
            raise ValidationError("host acceptance record format is invalid")
        for field, value in (
            ("wheel sha256", self.wheel_sha256),
            ("extension bundle sha256", self.extension_bundle_sha256),
            ("package sha256", self.package_sha256),
            ("manifest sha256", self.manifest_sha256), ("definition sha256", self.definition_sha256),
            ("preparation sha256", self.preparation_sha256),
        ):
            _digest(value, field)
        if self.host_family not in {"macos", "windows"}:
            raise ValidationError("host acceptance family is invalid")
        if not self.standard_user or not self.non_elevated:
            raise ValidationError("host acceptance must be non-elevated standard-user execution")
        if [item.case_id for item in self.cases] != list(REQUIRED_ACCEPTANCE_CASES):
            raise ValidationError("host acceptance cases are missing, duplicated, or unknown")
        if [item.sequence for item in self.cases] != list(range(1, len(self.cases) + 1)):
            raise ValidationError("host acceptance case sequence is invalid")
        if any(item.status != "PASS" or item.execution != "NATIVE" for item in self.cases):
            raise ValidationError("host acceptance cases must be native passes")
        if self.scheduler_states != ("installed-disabled", "enabled", "installed-disabled", "absent"):
            raise ValidationError("host acceptance scheduler transitions are invalid")
        if (
            self.activation_terminal_state != "DEACTIVATED"
            or self.definition_terminal_state != "DEFINITION_ROLLED_BACK"
            or not self.cleanup_complete
            or not self.task_absent
            or not self.registry_disabled
        ):
            raise ValidationError("host acceptance cleanup proof is invalid")
        if len(set(self.excluded_artifacts)) != len(self.excluded_artifacts):
            raise ValidationError("excluded artifacts are invalid")
        attachment_paths = [item.path for item in self.attachments]
        if attachment_paths != sorted(attachment_paths) or len(set(path.casefold() for path in attachment_paths)) != len(attachment_paths):
            raise ValidationError("evidence attachments are invalid")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "acceptance_run_id": self.acceptance_run_id,
            "architecture": self.architecture,
            "attachments": [item.to_mapping() for item in self.attachments],
            "cases": [item.to_mapping() for item in self.cases],
            "cleanup_complete": self.cleanup_complete,
            "definition_sha256": self.definition_sha256,
            "definition_terminal_state": self.definition_terminal_state,
            "excluded_artifacts": list(self.excluded_artifacts),
            "format": self.format,
            "host_family": self.host_family,
            "manifest_sha256": self.manifest_sha256,
            "extension_bundle_sha256": self.extension_bundle_sha256,
            "non_elevated": self.non_elevated,
            "os_version": self.os_version,
            "package_sha256": self.package_sha256,
            "preparation_sha256": self.preparation_sha256,
            "projectos_version": self.projectos_version,
            "python_version": self.python_version,
            "registry_disabled": self.registry_disabled,
            "scheduler_states": list(self.scheduler_states),
            "source_revision": self.source_revision,
            "standard_user": self.standard_user,
            "task_absent": self.task_absent,
            "activation_terminal_state": self.activation_terminal_state,
            "wheel_sha256": self.wheel_sha256,
        }

    def canonical_bytes(self) -> bytes:
        self.validate()
        return _canonical(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Any) -> HostAcceptanceRecord:
        expected = {
            "acceptance_run_id", "activation_terminal_state", "architecture", "attachments",
            "cases", "cleanup_complete", "definition_sha256", "definition_terminal_state",
            "excluded_artifacts", "extension_bundle_sha256", "format", "host_family",
            "manifest_sha256", "non_elevated",
            "os_version", "package_sha256", "projectos_version", "python_version",
            "preparation_sha256", "registry_disabled", "scheduler_states", "source_revision", "standard_user",
            "task_absent", "wheel_sha256",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValidationError("host acceptance record fields are invalid")
        for field in ("cases", "attachments", "excluded_artifacts", "scheduler_states"):
            if not isinstance(value[field], list):
                raise ValidationError("host acceptance record sequence is invalid")
        record = cls(
            str(value["format"]), str(value["projectos_version"]), str(value["source_revision"]),
            str(value["wheel_sha256"]), str(value["extension_bundle_sha256"]),
            str(value["package_sha256"]), str(value["manifest_sha256"]),
            str(value["preparation_sha256"]),
            str(value["definition_sha256"]), str(value["host_family"]), str(value["os_version"]),
            str(value["architecture"]), str(value["python_version"]), str(value["acceptance_run_id"]),
            value["standard_user"], value["non_elevated"],
            tuple(AcceptanceCaseResult.from_mapping(item) for item in value["cases"]),
            tuple(str(item) for item in value["scheduler_states"]),
            str(value["activation_terminal_state"]), str(value["definition_terminal_state"]),
            value["cleanup_complete"], value["task_absent"], value["registry_disabled"],
            tuple(str(item) for item in value["excluded_artifacts"]),
            tuple(EvidenceAttachment.from_mapping(item) for item in value["attachments"]),
        )
        if any(type(value[field]) is not bool for field in ("standard_user", "non_elevated", "cleanup_complete", "task_absent", "registry_disabled")):
            raise ValidationError("host acceptance boolean field is invalid")
        record.validate()
        return record


@dataclass(frozen=True)
class AcceptanceEvidence:
    path: Path
    sha256: str
    size: int
    member_count: int
    record: HostAcceptanceRecord


@dataclass(frozen=True)
class VerifiedHostEvidence:
    record: HostAcceptanceRecord
    archive_sha256: str
    member_count: int


class AcceptanceEvidenceBuilder:
    def build(
        self,
        record: HostAcceptanceRecord,
        attachments: Mapping[str, bytes],
        output_path: Path,
    ) -> AcceptanceEvidence:
        record.validate()
        entries: dict[str, bytes] = {}
        attachment_entries: list[EvidenceAttachment] = []
        folded: set[str] = set()
        for name, content in sorted(attachments.items()):
            portable = _portable(name)
            if not portable.endswith(".json"):
                raise ValidationError("evidence attachments must be JSON files")
            archive_name = f"attachments/{portable}"
            if archive_name.casefold() in folded:
                raise ValidationError("evidence attachments contain duplicate paths")
            folded.add(archive_name.casefold())
            _inspect(archive_name, content)
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValidationError("evidence attachment is invalid JSON") from exc
            if content != _canonical(parsed):
                raise ValidationError("evidence attachment is not canonical")
            entries[archive_name] = content
            attachment_entries.append(EvidenceAttachment(archive_name, _sha256(content), len(content)))
        finalized = replace(record, attachments=tuple(attachment_entries))
        record_bytes = finalized.canonical_bytes()
        _inspect("projectos-host-acceptance-v2.json", record_bytes)
        entries["projectos-host-acceptance-v2.json"] = record_bytes
        entries["SHA256SUMS.txt"] = "".join(
            f"{_sha256(content)}  {name}\n" for name, content in sorted(entries.items())
        ).encode("ascii")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
            with zipfile.ZipFile(temporary_path, "w") as archive:
                for name, content in sorted(entries.items()):
                    archive.writestr(_zip_info(name), content)
            verified = _verify_archive(temporary_path)
            os.replace(temporary_path, output)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        content = output.read_bytes()
        return AcceptanceEvidence(output, _sha256(content), len(content), verified.member_count, finalized)


def _verify_archive(path: Path) -> VerifiedHostEvidence:
    archive_path = Path(path)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            names: list[str] = []
            folded: set[str] = set()
            for member in members:
                name = _portable(member.filename)
                if name.casefold() in folded:
                    raise ValidationError("evidence archive contains duplicate paths")
                folded.add(name.casefold())
                if stat.S_ISLNK(member.external_attr >> 16) or not stat.S_ISREG(member.external_attr >> 16):
                    raise ValidationError("evidence archive members must be regular files")
                names.append(name)
            if names.count("projectos-host-acceptance-v2.json") != 1 or names.count("SHA256SUMS.txt") != 1:
                raise ValidationError("evidence archive control files are invalid")
            record_bytes = archive.read("projectos-host-acceptance-v2.json")
            try:
                mapping = json.loads(record_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationError("host acceptance record is invalid") from exc
            record = HostAcceptanceRecord.from_mapping(mapping)
            if record_bytes != record.canonical_bytes():
                raise ValidationError("host acceptance record is not canonical")
            expected_names = {"projectos-host-acceptance-v2.json", "SHA256SUMS.txt"} | {
                item.path for item in record.attachments
            }
            if set(names) != expected_names or len(names) != len(expected_names):
                raise ValidationError("evidence archive inventory is invalid")
            for attachment in record.attachments:
                content = archive.read(attachment.path)
                _inspect(attachment.path, content)
                if len(content) != attachment.size or _sha256(content) != attachment.sha256:
                    raise ValidationError("evidence attachment hash or size mismatch")
            expected_sums = "".join(
                f"{_sha256(archive.read(name))}  {name}\n"
                for name in sorted(expected_names - {"SHA256SUMS.txt"})
            ).encode("ascii")
            if archive.read("SHA256SUMS.txt") != expected_sums:
                raise ValidationError("evidence checksum inventory is invalid")
            _inspect("projectos-host-acceptance-v2.json", record_bytes)
            if archive.testzip() is not None:
                raise ValidationError("evidence archive contains a corrupt member")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValidationError("acceptance evidence is unavailable or invalid") from exc
    return VerifiedHostEvidence(record, _sha256(archive_path.read_bytes()), len(members))


class AcceptanceEvidenceVerifier:
    def verify(
        self,
        path: Path,
        manifest: AcceptanceManifest,
        *,
        expected_definition_sha256: str | None = None,
    ) -> VerifiedHostEvidence:
        verified = _verify_archive(path)
        record = verified.record
        if (
            record.projectos_version != manifest.projectos_version
            or record.source_revision != manifest.source_revision
            or record.wheel_sha256 != manifest.wheel.sha256
            or record.extension_bundle_sha256 != manifest.extension_bundle.sha256
            or record.manifest_sha256 != _sha256(manifest.canonical_bytes())
            or record.host_family not in manifest.supported_hosts
        ):
            raise ValidationError("acceptance evidence release or host does not match manifest")
        if expected_definition_sha256 is not None and record.definition_sha256 != _digest(expected_definition_sha256, "expected definition sha256"):
            raise ValidationError("acceptance evidence definition does not match")
        record.validate()
        return verified
