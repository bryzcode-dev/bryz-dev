from __future__ import annotations

import platform
from dataclasses import dataclass
from enum import Enum

from projectos.errors import ValidationError
from projectos.validation import require_text


class HostFamily(str, Enum):
    MACOS = "macos"
    WINDOWS = "windows"


@dataclass(frozen=True)
class HostIdentity:
    family: HostFamily
    machine_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "machine_id", require_text(self.machine_id, "machine_id"))


def detect_host_family(system_name: str | None = None) -> HostFamily:
    name = (system_name or platform.system()).strip().casefold()
    if name in {"darwin", "macos"}:
        return HostFamily.MACOS
    if name in {"windows", "win32"}:
        return HostFamily.WINDOWS
    raise ValidationError("ProjectOS supports macOS and Windows hosts")
