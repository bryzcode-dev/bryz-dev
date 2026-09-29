from __future__ import annotations

import builtins
import errno
import json
import os
import sys
import unittest
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

from tests.helpers import TemporaryDirectoryMixin

import projectos.adoption.lock as lock_module
from projectos.adoption.host import HostFamily
from projectos.adoption.lock import NativeLockUnavailable, backend_for
from projectos.sync.lock import LockUnavailable, ProjectOSFileLock


class FakePosixModule:
    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def flock(self, file_number: int, operation: int) -> None:
        self.calls.append((file_number, operation))


class FakeWindowsModule:
    LK_NBLCK = 1
    LK_UNLCK = 2

    def __init__(self, failure: OSError | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[int, int, int, int]] = []

    def locking(self, file_number: int, operation: int, count: int) -> None:
        offset = os.lseek(file_number, 0, os.SEEK_CUR)
        self.calls.append((file_number, operation, count, offset))
        if self.failure is not None:
            raise self.failure


class ProcessLockTests(TemporaryDirectoryMixin, unittest.TestCase):
    def test_contention_returns_only_safe_owner_metadata(self) -> None:
        path = self.temp_path / "owner.lock"
        path.write_text(
            json.dumps(
                {
                    "format": "projectos-lock-v1",
                    "pid": os.getpid(),
                    "started_at": "2026-09-27T12:00:00Z",
                    "trigger": "scheduler",
                    "run_id": "run-safe",
                }
            ),
            encoding="utf-8",
        )

        owner = ProjectOSFileLock.read_owner(path)

        self.assertEqual(
            {
                "run_id": "run-safe",
                "trigger": "scheduler",
                "started_at": "2026-09-27T12:00:00Z",
                "pid_active": True,
            },
            asdict(owner),
        )

    def test_malformed_replaced_or_disappearing_owner_never_starts_duplicate_sync(self) -> None:
        path = self.temp_path / "unstable.lock"
        path.write_text("not-json", encoding="utf-8")
        self.assertIsNone(ProjectOSFileLock.read_owner(path))
        path.unlink()
        self.assertIsNone(ProjectOSFileLock.read_owner(path))

        path.write_text(
            json.dumps(
                {
                    "format": "projectos-lock-v1",
                    "pid": os.getpid(),
                    "started_at": "t",
                    "trigger": "skill",
                    "run_id": "held",
                }
            ),
            encoding="utf-8",
        )
        current = path.stat()
        replaced = SimpleNamespace(st_dev=current.st_dev, st_ino=current.st_ino + 1)
        with patch.object(type(path), "stat", return_value=replaced):
            self.assertIsNone(ProjectOSFileLock.read_owner(path))

    def test_posix_backend_is_loaded_lazily(self) -> None:
        imported: list[str] = []
        original = lock_module.importlib.import_module

        def tracked(name, *args, **kwargs):
            imported.append(name)
            return original(name, *args, **kwargs)

        with patch.object(lock_module.importlib, "import_module", side_effect=tracked):
            backend = backend_for(HostFamily.MACOS)
            self.assertEqual([], imported)
            path = self.temp_path / "posix.lock"
            with path.open("a+b") as handle:
                backend.acquire(handle)
                backend.release(handle)

        self.assertEqual(["fcntl"], imported)

    def test_windows_backend_is_loaded_without_importing_fcntl(self) -> None:
        fake = FakeWindowsModule()
        imported: list[str] = []
        original = builtins.__import__

        def guarded(name, *args, **kwargs):
            imported.append(name)
            if name == "fcntl":
                raise AssertionError("Windows lock imported fcntl")
            return original(name, *args, **kwargs)

        with patch.dict(sys.modules, {"msvcrt": fake}), patch.object(
            builtins, "__import__", side_effect=guarded
        ):
            backend = backend_for(HostFamily.WINDOWS)
            path = self.temp_path / "windows.lock"
            with path.open("a+b") as handle:
                backend.acquire(handle)
                backend.release(handle)

        self.assertNotIn("fcntl", imported)
        self.assertEqual([fake.LK_NBLCK, fake.LK_UNLCK], [row[1] for row in fake.calls])

    def test_windows_lock_rewinds_and_locks_one_metadata_byte(self) -> None:
        fake = FakeWindowsModule()
        backend = backend_for(HostFamily.WINDOWS)
        path = self.temp_path / "windows-byte.lock"

        with patch.dict(sys.modules, {"msvcrt": fake}):
            with path.open("a+b") as handle:
                handle.seek(0, os.SEEK_END)
                backend.acquire(handle)
                backend.release(handle)

        self.assertGreaterEqual(path.stat().st_size, 1)
        self.assertEqual([(fake.LK_NBLCK, 1, 0), (fake.LK_UNLCK, 1, 0)], [
            (operation, count, offset) for _fd, operation, count, offset in fake.calls
        ])

    def test_backend_contention_maps_to_lock_unavailable(self) -> None:
        fake = FakeWindowsModule(OSError(errno.EACCES, "busy"))
        backend = backend_for(HostFamily.WINDOWS)

        with patch.dict(sys.modules, {"msvcrt": fake}):
            with (self.temp_path / "busy.lock").open("a+b") as handle:
                with self.assertRaisesRegex(NativeLockUnavailable, "already locked"):
                    backend.acquire(handle)

    def test_malformed_prior_metadata_remains_fail_closed(self) -> None:
        path = self.temp_path / "malformed.lock"
        path.write_text(json.dumps({"pid": 999999}), encoding="utf-8")

        with self.assertRaisesRegex(LockUnavailable, "not owned format"):
            with ProjectOSFileLock(path, "manual", "new"):
                pass

    def test_existing_projectos_file_lock_api_is_unchanged(self) -> None:
        path = self.temp_path / "facade.lock"

        with ProjectOSFileLock(path, "skill", "run-1") as acquired:
            self.assertIsInstance(acquired, ProjectOSFileLock)
            metadata = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "format": "projectos-lock-v1",
                    "pid": os.getpid(),
                    "run_id": "run-1",
                    "trigger": "skill",
                },
                {key: metadata[key] for key in ("format", "pid", "run_id", "trigger")},
            )


if __name__ == "__main__":
    unittest.main()
