from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import TemporaryDirectoryMixin

from projectos.acceptance.authority import (
    ACCEPTANCE_ACKNOWLEDGEMENT,
    ACCEPTANCE_MARKER,
    AcceptanceTarget,
    HostSession,
)
from projectos.adoption.fixture import FIXTURE_MARKER
from projectos.adoption.host import HostFamily
from projectos.errors import ValidationError


class AcceptanceAuthorityTests(TemporaryDirectoryMixin, unittest.TestCase):
    def session(self, family: HostFamily = HostFamily.MACOS, *, elevated: bool = False) -> HostSession:
        return HostSession(family, "a" * 64, elevated, not elevated)

    def issue(self, name: str = "acceptance") -> tuple[AcceptanceTarget, Path, Path]:
        root = self.temp_path / name
        runtime = self.temp_path / f"{name}-runtime"
        with patch("projectos.acceptance.authority.detect_host_session", return_value=self.session()):
            target = AcceptanceTarget.issue(root, runtime, HostFamily.MACOS)
        return target, root, runtime

    def test_acceptance_target_requires_new_empty_non_symlink_root_and_exact_ack(self) -> None:
        occupied = self.temp_path / "occupied"
        occupied.mkdir()
        (occupied / "preserve.txt").write_text("preserve", encoding="utf-8")
        with patch("projectos.acceptance.authority.detect_host_session", return_value=self.session()):
            with self.assertRaisesRegex(ValidationError, "empty"):
                AcceptanceTarget.issue(occupied, self.temp_path / "runtime", HostFamily.MACOS)

        actual = self.temp_path / "actual"
        actual.mkdir()
        linked = self.temp_path / "linked"
        linked.symlink_to(actual, target_is_directory=True)
        with patch("projectos.acceptance.authority.detect_host_session", return_value=self.session()):
            with self.assertRaisesRegex(ValidationError, "symlink"):
                AcceptanceTarget.issue(linked, self.temp_path / "runtime-two", HostFamily.MACOS)

        target, root, runtime = self.issue()
        with self.assertRaisesRegex(ValidationError, "acknowledgement"):
            AcceptanceTarget.open(root, runtime, "wrong", self.session())
        reopened = AcceptanceTarget.open(root, runtime, ACCEPTANCE_ACKNOWLEDGEMENT, self.session())
        self.assertEqual(target.acceptance_id, reopened.acceptance_id)

    def test_acceptance_receipt_is_same_host_runtime_bound_and_canonical(self) -> None:
        target, root, runtime = self.issue()
        marker_bytes = (root / ACCEPTANCE_MARKER).read_bytes()
        receipt_path = runtime / "acceptance/receipts" / f"{target.receipt_id}.json"
        receipt_bytes = receipt_path.read_bytes()
        self.assertEqual(
            json.dumps(json.loads(marker_bytes), sort_keys=True, separators=(",", ":")) + "\n",
            marker_bytes.decode(),
        )
        self.assertEqual(
            json.dumps(json.loads(receipt_bytes), sort_keys=True, separators=(",", ":")) + "\n",
            receipt_bytes.decode(),
        )
        with self.assertRaisesRegex(ValidationError, "receipt"):
            AcceptanceTarget.open(root, self.temp_path / "other-runtime", ACCEPTANCE_ACKNOWLEDGEMENT, self.session())
        with self.assertRaisesRegex(ValidationError, "host"):
            AcceptanceTarget.open(
                root,
                runtime,
                ACCEPTANCE_ACKNOWLEDGEMENT,
                HostSession(HostFamily.MACOS, "b" * 64, False, True),
            )

    def test_acceptance_target_rejects_fixture_contextos_shared_or_overlapping_roots(self) -> None:
        fixture = self.temp_path / "fixture"
        fixture.mkdir()
        (fixture / FIXTURE_MARKER).write_text("{}", encoding="utf-8")
        contextos = self.temp_path / "contextos"
        (contextos / "context-os").mkdir(parents=True)
        shared = self.temp_path / "shared"
        shared.mkdir()
        cases = (
            (fixture, self.temp_path / "runtime-a", ()),
            (contextos, self.temp_path / "runtime-b", ()),
            (shared / "acceptance", self.temp_path / "runtime-c", (shared,)),
            (self.temp_path / "overlap", self.temp_path / "overlap/runtime", ()),
        )
        with patch("projectos.acceptance.authority.detect_host_session", return_value=self.session()):
            for root, runtime, excluded in cases:
                with self.subTest(root=root):
                    with self.assertRaises(ValidationError):
                        AcceptanceTarget.issue(root, runtime, HostFamily.MACOS, excluded_roots=excluded)

    def test_acceptance_authority_rejects_elevated_or_wrong_host_session(self) -> None:
        _target, root, runtime = self.issue()
        with self.assertRaisesRegex(ValidationError, "elevated"):
            AcceptanceTarget.open(
                root, runtime, ACCEPTANCE_ACKNOWLEDGEMENT, self.session(elevated=True)
            )
        with self.assertRaisesRegex(ValidationError, "host family"):
            AcceptanceTarget.open(
                root,
                runtime,
                ACCEPTANCE_ACKNOWLEDGEMENT,
                HostSession(HostFamily.WINDOWS, "a" * 64, False, True),
            )


if __name__ == "__main__":
    unittest.main()
