from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from projectos.acceptance.authority import AcceptanceTarget
from projectos.acceptance.profile import AcceptanceProfile
from projectos.errors import ValidationError


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class LocalAcceptanceStore:
    def __init__(self, target: AcceptanceTarget, profile: AcceptanceProfile):
        self.target = target
        self.profile = profile
        self.root = target.runtime_root / "acceptance" / "state"
        self.lock_path = target.runtime_root / "acceptance" / "acceptance.lock"

    @classmethod
    def open(
        cls, target: AcceptanceTarget, profile: AcceptanceProfile
    ) -> LocalAcceptanceStore:
        if profile.target != target:
            raise ValidationError("acceptance store target does not match profile")
        target.assert_runtime_path(profile.machine_profile.database_path)
        target.assert_runtime_path(profile.evidence_spool)
        runtime = target.runtime_root
        if runtime.is_symlink() or (runtime / "acceptance").is_symlink():
            raise ValidationError("acceptance store cannot use a symlink")
        return cls(target, profile)

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ValidationError("acceptance store is already in use") from exc
        try:
            os.write(descriptor, (self.target.acceptance_id + "\n").encode("ascii"))
            os.fsync(descriptor)
            yield
        finally:
            os.close(descriptor)
            self.lock_path.unlink(missing_ok=True)

    def save_profile(self, profile: AcceptanceProfile) -> Path:
        if profile.target != self.target:
            raise ValidationError("acceptance profile target does not match store")
        path = self.root / "acceptance-profile.json"
        _atomic_write(path, profile.canonical_bytes())
        return path

    @property
    def preparation_path(self) -> Path:
        return self.root / "preparation.json"

    def save_preparation(self, content: bytes) -> Path:
        if self.preparation_path.exists() or self.preparation_path.is_symlink():
            raise ValidationError("acceptance preparation already exists")
        _atomic_write(self.preparation_path, content)
        return self.preparation_path

    def load_preparation_bytes(self) -> bytes:
        try:
            return self.preparation_path.read_bytes()
        except OSError as exc:
            raise ValidationError("acceptance preparation is unavailable") from exc

    def load_profile(self) -> AcceptanceProfile:
        path = self.root / "acceptance-profile.json"
        try:
            content = path.read_bytes()
            value = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("acceptance profile is unavailable or invalid") from exc
        if not isinstance(value, dict):
            raise ValidationError("acceptance profile is unavailable or invalid")
        profile = AcceptanceProfile.from_mapping(value, self.target)
        if content != profile.canonical_bytes():
            raise ValidationError("acceptance profile is not canonical")
        return profile
