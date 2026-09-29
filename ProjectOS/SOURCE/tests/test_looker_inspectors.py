from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.helpers import REPO_ROOT

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from projectos.looker.model import CollectorPaths, LookerIntake


class Result:
    def __init__(self, code=0, stdout="", stderr="", timed_out=False):
        self.returncode, self.stdout, self.stderr, self.timed_out = code, stdout, stderr, timed_out


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses); self.calls = []

    def run(self, argv, timeout_seconds, working_directory):
        self.calls.append((tuple(argv), timeout_seconds, Path(working_directory)))
        return self.responses.pop(0)


class LookerInspectorTests(unittest.TestCase):
    def setUp(self):
        value = json.loads((REPO_ROOT / "tests/fixtures/looker/intake-macos.json").read_text())
        self.intake = LookerIntake.from_mapping(value)

    def test_git_uses_fixed_read_only_arrays_and_parses_state(self):
        from projectos.looker.inspectors import inspect_git

        recorder = Recorder(Result(stdout="a" * 40 + "\n"), Result(stdout="feature\n"), Result(stdout=" M model.lkml\n"), Result(stdout="2\t3\n"))
        result = inspect_git(self.intake, Path("/repo"), recorder)
        self.assertEqual(("git", "rev-parse", "HEAD"), recorder.calls[0][0])
        self.assertEqual("feature", result.branch)
        self.assertTrue(result.dirty)
        self.assertEqual((2, 3), (result.behind, result.ahead))
        self.assertEqual("a" * 40, result.head)

    def test_legacy_and_automation_inspection_use_declared_safe_metadata(self):
        from projectos.looker.inspectors import inspect_automation, inspect_legacy

        legacy_root = REPO_ROOT / "tests/fixtures/looker/legacy"
        intake = replace(self.intake, sync_script_paths=(str(legacy_root / "sync.py"),), scheduler_definition_paths=(str(legacy_root / "scheduler.txt"),))
        legacy = inspect_legacy(intake)
        self.assertEqual(("Models", "Views"), legacy.sheet_tabs)
        self.assertEqual(("deploy-safe-id",), legacy.deployment_ids)
        automation = inspect_automation(intake)
        self.assertEqual(("scheduler", "sync_script"), tuple(item.kind for item in automation.items))
        self.assertTrue(all(len(item.content_sha256) == 64 and item.byte_count > 0 for item in automation.items))

    def test_validations_are_bounded_and_parse_timeout_and_nonzero(self):
        from projectos.looker.inspectors import run_validations

        long_output = "tests=12 passed=11 failed=1 token=not-retained " + "x" * 5000
        recorder = Recorder(Result(1, long_output, "failure detail"), Result(-1, "", "", True))
        command = self.intake.validation_commands[0]
        timed = replace(command, command_id="timed")
        results = run_validations(replace(self.intake, validation_commands=(command, timed)), recorder)
        self.assertFalse(results[0].passed)
        self.assertLessEqual(len(results[0].summary), 512)
        self.assertTrue(results[1].timed_out)
        self.assertEqual((command.executable, *command.arguments), recorder.calls[0][0])

    def test_repository_content_cannot_introduce_commands(self):
        from projectos.looker.inspectors import run_validations

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / "evil.lkml").write_text('command: "rm -rf data"')
            recorder = Recorder(Result(stdout="OK"))
            run_validations(self.intake, recorder)
            self.assertEqual(1, len(recorder.calls))
            self.assertNotIn("rm", recorder.calls[0][0])


if __name__ == "__main__":
    unittest.main()
