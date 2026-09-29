from __future__ import annotations

import errno
import importlib
import os
from typing import IO, Protocol, runtime_checkable

from projectos.adoption.host import HostFamily


class NativeLockUnavailable(RuntimeError):
    pass


@runtime_checkable
class NativeLockBackend(Protocol):
    def acquire(self, file: IO) -> None: ...

    def release(self, file: IO) -> None: ...


class PosixLockBackend:
    def __init__(self) -> None:
        self._module = None

    def _native(self):
        if self._module is None:
            self._module = importlib.import_module("fcntl")
        return self._module

    def acquire(self, file: IO) -> None:
        native = self._native()
        try:
            native.flock(file.fileno(), native.LOCK_EX | native.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise NativeLockUnavailable("lock is already locked") from exc
            raise

    def release(self, file: IO) -> None:
        native = self._native()
        native.flock(file.fileno(), native.LOCK_UN)


class WindowsLockBackend:
    def __init__(self) -> None:
        self._module = None

    def _native(self):
        if self._module is None:
            self._module = importlib.import_module("msvcrt")
        return self._module

    @staticmethod
    def _rewind_with_reserved_byte(file: IO) -> None:
        file.flush()
        file_number = file.fileno()
        if os.fstat(file_number).st_size == 0:
            os.lseek(file_number, 0, os.SEEK_SET)
            os.write(file_number, b" ")
            os.fsync(file_number)
        os.lseek(file_number, 0, os.SEEK_SET)

    def acquire(self, file: IO) -> None:
        native = self._native()
        self._rewind_with_reserved_byte(file)
        try:
            native.locking(file.fileno(), native.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise NativeLockUnavailable("lock is already locked") from exc
            raise

    def release(self, file: IO) -> None:
        native = self._native()
        os.lseek(file.fileno(), 0, os.SEEK_SET)
        native.locking(file.fileno(), native.LK_UNLCK, 1)


def backend_for(family: HostFamily) -> NativeLockBackend:
    if family is HostFamily.WINDOWS:
        return WindowsLockBackend()
    return PosixLockBackend()
