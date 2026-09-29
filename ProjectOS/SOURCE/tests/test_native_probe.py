from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path, PurePosixPath

from tests.helpers import TemporaryDirectoryMixin

from projectos.acceptance.authority import (
    ACCEPTANCE_ACKNOWLEDGEMENT,
    AcceptanceTarget,
    detect_host_session,
)
from projectos.acceptance.native_probe import NativeProbeController, NativeTriggerWindow
from projectos.acceptance.probe import _append_event
from projectos.acceptance.profile import AcceptanceProfile
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import MachineProfile, SchedulerKind
from projectos.adoption.scheduler import SchedulerInspection, SchedulerState, adapter_for
from projectos.errors import ValidationError


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        self.value += 0.05
        return self.value


class EventRunner:
    def __init__(self, profile, definition, statuses=()) -> None:
        self.profile = profile
        self.definition = definition
        self.statuses = list(statuses)
        self.triggers = 0

    def trigger(self, definition):
        self.triggers += 1
        if definition != self.definition:
            raise AssertionError("wrong definition")
        if self.statuses:
            status, code = self.statuses.pop(0)
            active = json.loads(
                (self.profile.target.runtime_root / "acceptance/active-case.json").read_text()
            )
            if status == "STARTED":
                barrier = (
                    self.profile.target.runtime_root
                    / "acceptance/barriers/native_non_overlap.active"
                )
                barrier.parent.mkdir(parents=True, exist_ok=True)
                barrier.write_text(self.profile.target.receipt_id + "\n", encoding="ascii")
            _append_event(
                self.profile, active["case_id"], status, code, native_window=active
            )
        return SchedulerInspection(
            definition.task_id, SchedulerState.ENABLED, definition.sha256
        )


class NativeProbeTests(TemporaryDirectoryMixin, unittest.TestCase):
    def prepare(self):
        runtime = (self.temp_path / "runtime").resolve()
        fixture = (self.temp_path / "fixture").resolve()
        production = MachineProfile(
            1, "99999999-9999-9999-9999-999999999999", "fixture", HostFamily.MACOS,
            "0.1.0", "3.0.1", 1, PurePosixPath(fixture),
            PurePosixPath(fixture / "context-os/extensions"), PurePosixPath(fixture / "skills"),
            PurePosixPath(runtime), PurePosixPath(runtime / "projectos.db"),
            PurePosixPath(runtime / "projectos.toml"), PurePosixPath(runtime / "projectos.sync.lock"),
            PurePosixPath(runtime / "logs"), PurePosixPath(runtime / "staging"),
            PurePosixPath(sys.executable), (sys.executable, "-m", "projectos.cli"),
            SchedulerKind.LAUNCHD, "com.contextos.projectos.sync", "ADOPTED", "a" * 64,
        )
        AcceptanceTarget.issue(self.temp_path / "authority", runtime, HostFamily.MACOS)
        target = AcceptanceTarget.open(
            self.temp_path / "authority", runtime, ACCEPTANCE_ACKNOWLEDGEMENT,
            detect_host_session(),
        )
        profile = AcceptanceProfile.from_machine_profile(
            production, target, source_revision="1" * 40, release_sha256="2" * 64,
            wheel_sha256="3" * 64, extension_bundle_sha256="4" * 64,
            preparation_id="preparation-01", definition_transaction_id="definition-01",
            activation_id="activation-01", max_probe_seconds=1,
        )
        definition = adapter_for(profile.machine_profile).render(
            profile.machine_profile, PurePosixPath(runtime / "adoption/machine-profile.json")
        )
        return profile, definition

    def controller(self, profile, definition, runner, *, sleep=lambda seconds: None):
        return NativeProbeController(
            profile, definition, runner, "run-01", monotonic=Clock(), sleep=sleep
        )

    def test_immediate_proof_requires_one_event_inside_native_trigger_window(self) -> None:
        profile, definition = self.prepare()
        runner = EventRunner(profile, definition, (("COMPLETE", "SYNC_COMPLETE"),))
        result = self.controller(profile, definition, runner).prove_immediate()
        self.assertTrue(result.ok)
        self.assertEqual("COMPLETE", result.status)
        windows = list((profile.target.runtime_root / "acceptance/trigger-windows").glob("*.json"))
        self.assertEqual(1, len(windows))
        self.assertIsInstance(NativeTriggerWindow.from_mapping(json.loads(windows[0].read_text())), NativeTriggerWindow)

    def test_non_overlap_proof_requires_started_then_second_native_trigger_then_locked(self) -> None:
        profile, definition = self.prepare()
        runner = EventRunner(
            profile, definition,
            (("STARTED", "BARRIER_STARTED"), ("LOCKED", "BARRIER_BUSY")),
        )
        released = False

        def sleep(_seconds):
            nonlocal released
            release = profile.target.runtime_root / "acceptance/barriers/native_non_overlap.release"
            if release.exists() and not released:
                released = True
                active = json.loads(
                    (profile.target.runtime_root / "acceptance/active-case.json").read_text()
                )
                _append_event(
                    profile, "native_non_overlap", "COMPLETE", "SYNC_COMPLETE",
                    native_window=active,
                )

        result = self.controller(profile, definition, runner, sleep=sleep).prove_non_overlap()
        self.assertTrue(result.ok)
        self.assertEqual("LOCKED", result.status)
        self.assertEqual(2, runner.triggers)

    def test_direct_probe_call_cannot_satisfy_native_case(self) -> None:
        profile, definition = self.prepare()
        _append_event(profile, "immediate_trigger", "COMPLETE", "SYNC_COMPLETE")
        with self.assertRaisesRegex(ValidationError, "timed out"):
            self.controller(profile, definition, EventRunner(profile, definition)).prove_immediate()

    def test_foreign_stale_duplicate_reordered_and_timed_out_events_fail_closed(self) -> None:
        cases = ("foreign", "stale", "duplicate", "reordered", "timed_out")
        for index, case in enumerate(cases):
            with self.subTest(case=case):
                profile, definition = self.prepare_again(str(index))

                class BadRunner(EventRunner):
                    def trigger(inner, selected):
                        active = json.loads(
                            (profile.target.runtime_root / "acceptance/active-case.json").read_text()
                        )
                        changed = dict(active)
                        if case == "foreign":
                            changed["receipt_id"] = "foreign-receipt"
                        elif case == "stale":
                            changed["window_id"] = "stale-window"
                        if case == "reordered":
                            statuses = (("LOCKED", "BARRIER_BUSY"),)
                        elif case == "timed_out":
                            statuses = ()
                        else:
                            statuses = (("COMPLETE", "SYNC_COMPLETE"),)
                        for status, code in statuses:
                            _append_event(profile, active["case_id"], status, code, native_window=changed)
                            if case == "duplicate":
                                _append_event(profile, active["case_id"], status, code, native_window=changed)
                        return SchedulerInspection(selected.task_id, SchedulerState.ENABLED, selected.sha256)

                with self.assertRaises(ValidationError):
                    self.controller(profile, definition, BadRunner(profile, definition)).prove_immediate()

    def prepare_again(self, name: str):
        original = self.temp_path
        self.temp_path = original / name
        self.temp_path.mkdir()
        try:
            return self.prepare()
        finally:
            self.temp_path = original


if __name__ == "__main__":
    unittest.main()
