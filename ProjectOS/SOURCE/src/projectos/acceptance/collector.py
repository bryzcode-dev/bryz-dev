from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from projectos import __version__
from projectos.acceptance.evidence import (
    AcceptanceCaseResult,
    AcceptanceEvidence,
    AcceptanceEvidenceBuilder,
    HostAcceptanceRecord,
)
from projectos.acceptance.journal import HostAcceptanceJournal, HostAcceptanceState
from projectos.acceptance.model import REQUIRED_ACCEPTANCE_CASES
from projectos.acceptance.native_probe import NativeTriggerWindow
from projectos.acceptance.transaction import HostAcceptanceContext, HostAcceptanceResult
from projectos.adoption.scheduler import SchedulerAction, SchedulerState
from projectos.errors import ValidationError


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _utc_seconds() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class HostEvidenceCollector:
    def _native_events(
        self,
        context: HostAcceptanceContext,
        result: HostAcceptanceResult,
        case_id: str,
        statuses: tuple[str, ...],
    ) -> None:
        windows_root = context.target.runtime_root / "acceptance/trigger-windows"
        if not windows_root.is_dir() or windows_root.is_symlink():
            raise ValidationError("matching native trigger window is unavailable")
        matching: list[NativeTriggerWindow] = []
        for path in sorted(windows_root.glob("*.json")):
            if path.is_symlink():
                raise ValidationError("native trigger window is invalid")
            try:
                content = path.read_bytes()
                value = json.loads(content)
            except (OSError, json.JSONDecodeError) as exc:
                raise ValidationError("native trigger window is invalid") from exc
            window = NativeTriggerWindow.from_mapping(value)
            if content != window.canonical_bytes():
                raise ValidationError("native trigger window is not canonical")
            if (
                window.run_id == result.run_id
                and window.case_id == case_id
                and window.receipt_id == context.target.receipt_id
                and window.release_sha256 == context.profile.release_sha256
                and window.definition_sha256 == context.definition.sha256
            ):
                matching.append(window)
        if len(matching) != 1:
            raise ValidationError("matching native trigger window is unavailable or duplicated")
        window = matching[0]
        event_path = Path(str(context.profile.evidence_spool)) / "probe-events.jsonl"
        try:
            lines = event_path.read_bytes().splitlines()
        except OSError as exc:
            raise ValidationError("native probe events are unavailable") from exc
        observed: list[str] = []
        expected = window.to_mapping()
        for raw in lines:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValidationError("native probe event is invalid") from exc
            canonical = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
            if raw + b"\n" != canonical:
                raise ValidationError("native probe event is not canonical")
            if not isinstance(value, dict) or value.get("format") != "projectos-probe-event-v2":
                continue
            if all(value.get(field) == expected[field] for field in expected if field != "format"):
                observed.append(str(value.get("status")))
        if tuple(observed) != statuses:
            raise ValidationError("native trigger events do not prove the required case")

    def _assert_cleanup(
        self, context: HostAcceptanceContext, result: HostAcceptanceResult
    ) -> None:
        if result.state is not HostAcceptanceState.EVIDENCE_SEALED or not result.cleanup_complete:
            raise ValidationError("host acceptance cleanup is incomplete")
        if context.activation_controller.active or context.definition_controller.active:
            raise ValidationError("host acceptance cleanup did not disable registry and rollback definition")
        inspection = context.native_runner.perform(SchedulerAction.INSPECT, context.definition)
        if inspection.state is not SchedulerState.ABSENT or inspection.definition_sha256 is not None:
            raise ValidationError("host acceptance cleanup did not remove the native task")
        if not context.database_health():
            raise ValidationError("host acceptance cleanup did not retain a healthy database")
        if not context.structural_equivalence:
            raise ValidationError("host acceptance structural equivalence is unproved")

    def collect(
        self, context: HostAcceptanceContext, result: HostAcceptanceResult
    ) -> HostAcceptanceRecord:
        if (
            context.preparation_record is None
            or context.preparation_record_bytes is None
            or context.evidence_root is None
        ):
            raise ValidationError("host acceptance preparation facts are unavailable")
        self._assert_cleanup(context, result)
        journal_path = context.store.root / "runs" / result.run_id / "journal.json"
        try:
            journal_bytes = journal_path.read_bytes()
            journal_value = json.loads(journal_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("host acceptance journal facts are unavailable") from exc
        if not isinstance(journal_value, dict):
            raise ValidationError("host acceptance journal facts are unavailable")
        journal = HostAcceptanceJournal.from_mapping(journal_value)
        if (
            journal_bytes != journal.canonical_bytes()
            or journal.run_id != result.run_id
            or journal.acceptance_id != context.target.acceptance_id
            or journal.receipt_id != context.target.receipt_id
            or journal.release_sha256 != context.profile.release_sha256
            or journal.wheel_sha256 != context.profile.wheel_sha256
            or journal.definition_sha256 != context.definition.sha256
        ):
            raise ValidationError("host acceptance journal facts are not bound to this run")
        self._native_events(context, result, "immediate_trigger", ("COMPLETE",))
        self._native_events(
            context, result, "native_non_overlap", ("STARTED", "LOCKED", "COMPLETE")
        )
        preparation = context.preparation_record
        if context.preparation_record_bytes != preparation.canonical_bytes():
            raise ValidationError("host acceptance preparation fact is not canonical")
        completed = journal.completed_states
        completed_set = set(completed)
        proved = set(result.proved_cases)
        database = Path(str(context.profile.machine_profile.database_path))
        context.target.assert_runtime_path(database)
        evidence_root = Path(context.evidence_root)
        context.target.assert_runtime_path(evidence_root)

        def ordered(*states: HostAcceptanceState) -> bool:
            try:
                positions = tuple(completed.index(state.value) for state in states)
            except ValueError:
                return False
            return positions == tuple(sorted(positions)) and len(set(positions)) == len(positions)

        facts = {
            "package_integrity": bool(
                context.package_verified
                and preparation.package_sha256 == context.profile.release_sha256
                and preparation.wheel_sha256 == context.profile.wheel_sha256
                and preparation.extension_bundle_sha256 == context.profile.extension_bundle_sha256
                and preparation.source_revision == context.profile.source_revision
            ),
            "standard_user_non_elevated": context.standard_user and context.non_elevated,
            "fixture_authority": bool(
                preparation.fixture_id
                and preparation.acceptance_id == context.target.acceptance_id
                and preparation.receipt_id == context.target.receipt_id
                and preparation.host_family == context.target.host_family.value
            ),
            "local_path_separation": database != evidence_root and evidence_root.is_dir(),
            "definition_structural_equivalence": context.structural_equivalence,
            "native_install_disabled": HostAcceptanceState.NATIVE_STAGED.value in completed_set,
            "native_enable": HostAcceptanceState.NATIVE_ENABLED.value in completed_set,
            "immediate_trigger": "immediate_trigger" in proved,
            "common_lock_contention": "common_lock_contention" in proved,
            "native_non_overlap": "native_non_overlap" in proved,
            "two_hour_configuration": "two_hour_configuration" in proved,
            "eligible_resume_configuration": "eligible_resume_configuration" in proved,
            "skill_discovery": "skill_discovery" in proved,
            "deactivation_order": ordered(
                HostAcceptanceState.SCHEDULE_PROVED,
                HostAcceptanceState.DEACTIVATED,
                HostAcceptanceState.NATIVE_REMOVED,
                HostAcceptanceState.DEFINITION_ROLLED_BACK,
            ),
            "native_disable_remove": (
                "native_disable_remove" in proved
                and HostAcceptanceState.NATIVE_REMOVED.value in completed_set
            ),
            "definition_rollback": (
                "definition_rollback" in proved
                and HostAcceptanceState.DEFINITION_ROLLED_BACK.value in completed_set
            ),
            "retained_database_health": (
                "retained_database_health" in proved and context.database_health()
            ),
            "identifier_secret_symlink_scan": bool(
                context.package_verified
                and not journal_path.is_symlink()
                and not database.is_symlink()
                and not evidence_root.is_symlink()
            ),
        }
        for case_id in REQUIRED_ACCEPTANCE_CASES:
            if not facts.get(case_id, False):
                raise ValidationError(f"host acceptance durable fact failed: {case_id}")
        timestamp = _utc_seconds()
        cases = tuple(
            AcceptanceCaseResult(
                index,
                case_id,
                "PASS",
                f"CASE_{index:02d}_{case_id.upper()}",
                "NATIVE",
                timestamp,
                timestamp,
                {f"fact_{case_id}": facts[case_id]},
            )
            for index, case_id in enumerate(REQUIRED_ACCEPTANCE_CASES, 1)
        )
        return HostAcceptanceRecord(
            "projectos-host-acceptance-v2",
            __version__,
            context.profile.source_revision,
            context.profile.wheel_sha256,
            context.profile.extension_bundle_sha256,
            preparation.package_sha256,
            preparation.manifest_sha256,
            _sha256(context.preparation_record_bytes),
            context.definition.sha256,
            context.target.host_family.value,
            platform.release(),
            platform.machine(),
            platform.python_version(),
            result.run_id,
            context.standard_user,
            context.non_elevated,
            cases,
            ("installed-disabled", "enabled", "installed-disabled", "absent"),
            "DEACTIVATED",
            "DEFINITION_ROLLED_BACK",
            True,
            True,
            True,
            ("database", "local-journals", "native-diagnostics", "probe-spool", "raw-logs"),
            (),
        )

    def seal(
        self,
        context: HostAcceptanceContext,
        result: HostAcceptanceResult,
        output_path: Path,
    ) -> AcceptanceEvidence:
        output = Path(output_path)
        if context.evidence_root is None:
            raise ValidationError("host acceptance evidence root is unavailable")
        root = Path(context.evidence_root).resolve(strict=False)
        if output.exists() or output.is_symlink():
            raise ValidationError("host acceptance evidence output must be new")
        try:
            output.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise ValidationError("host acceptance evidence output must stay below its root") from exc
        return AcceptanceEvidenceBuilder().build(self.collect(context, result), {}, output)
