from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from projectos.adoption.host import detect_host_family
from projectos.adoption.lock import NativeLockBackend, NativeLockUnavailable, backend_for
from projectos.database import utc_now


class LockUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class LockOwner:
    run_id: str
    trigger: str
    started_at: str
    pid_active: bool


class ProjectOSFileLock:
    def __init__(self, path: Path, trigger: str, run_id: str):
        self.path = Path(path)
        self.trigger = trigger
        self.run_id = run_id
        self._file: IO[str] | None = None
        self._backend: NativeLockBackend | None = None

    def __enter__(self) -> "ProjectOSFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        file = self.path.open("a+", encoding="utf-8")
        backend = backend_for(detect_host_family())
        try:
            backend.acquire(file)
        except NativeLockUnavailable as exc:
            file.close()
            raise LockUnavailable("ProjectOS sync is already running") from exc
        try:
            file.seek(0)
            content = file.read()
            if existed and content.strip():
                self._validate_prior_metadata(content)
            metadata = {
                "format": "projectos-lock-v1",
                "pid": os.getpid(),
                "started_at": utc_now(),
                "trigger": self.trigger,
                "run_id": self.run_id,
            }
            file.seek(0)
            file.truncate()
            json.dump(metadata, file, sort_keys=True, separators=(",", ":"))
            file.flush()
            os.fsync(file.fileno())
            self._file = file
            self._backend = backend
            return self
        except BaseException:
            backend.release(file)
            file.close()
            raise

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    @classmethod
    def read_owner(cls, path: Path) -> LockOwner | None:
        owner_path = Path(path)
        try:
            with owner_path.open("r", encoding="utf-8") as file:
                before = os.fstat(file.fileno())
                content = file.read()
                after = os.fstat(file.fileno())
            current = owner_path.stat()
        except (OSError, UnicodeError):
            return None
        identity = lambda value: (value.st_dev, value.st_ino)
        if identity(before) != identity(after) or identity(after) != identity(current):
            return None
        try:
            value = cls._parse_metadata(content)
        except LockUnavailable:
            return None
        return LockOwner(
            value["run_id"],
            value["trigger"],
            value["started_at"],
            cls._pid_alive(value["pid"]),
        )

    @staticmethod
    def _parse_metadata(content: str) -> dict[str, object]:
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LockUnavailable("ProjectOS lock metadata is malformed") from exc
        required = {"format", "pid", "started_at", "trigger", "run_id"}
        if (
            not isinstance(value, dict)
            or set(value) != required
            or value.get("format") != "projectos-lock-v1"
        ):
            raise LockUnavailable("ProjectOS lock metadata is not owned format")
        if type(value.get("pid")) is not int:
            raise LockUnavailable("ProjectOS lock PID is invalid")
        if any(
            not isinstance(value.get(field), str) or not value[field].strip()
            for field in ("started_at", "trigger", "run_id")
        ):
            raise LockUnavailable("ProjectOS lock metadata field is invalid")
        return value

    def _validate_prior_metadata(self, content: str) -> None:
        value = self._parse_metadata(content)
        pid = value["pid"]
        if pid != os.getpid() and self._pid_alive(pid):
            raise LockUnavailable("ProjectOS lock metadata names a live process")

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._file is None:
            return
        if self._backend is not None:
            self._backend.release(self._file)
        self._file.close()
        self._file = None
        self._backend = None
