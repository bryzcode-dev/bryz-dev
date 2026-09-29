from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Mapping
from uuid import UUID

from projectos.errors import ValidationError
from projectos.adoption.host import HostFamily, detect_host_family
from projectos.adoption.paths import PlatformPathOverrides, resolve_platform_paths
from projectos.users import normalize_email
from projectos.validation import require_text


@dataclass(frozen=True)
class ProjectOSGoogleConfig:
    path: Path
    machine_id: str
    environment: str
    binding_id: UUID
    spreadsheet_id: str
    expected_owner_email: str
    contract_version: int
    credential_reference_id: UUID
    google_enabled: bool
    google_write_enabled: bool

    @classmethod
    def load(
        cls,
        path: Path | str | None = None,
        environ: Mapping[str, str] | None = None,
        family: HostFamily | None = None,
        home: Path | PurePath | None = None,
    ) -> "ProjectOSGoogleConfig":
        values = dict(os.environ if environ is None else environ)
        resolved = Path(cls.resolve_path(path, values, family=family, home=home))
        try:
            data = tomllib.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValidationError(f"ProjectOS Google configuration is unavailable: {resolved}") from exc
        try:
            contract_version = int(data["contract_version"])
            if contract_version < 1:
                raise ValueError
            google_enabled = data.get("google_enabled", False)
            google_write_enabled = data.get("google_write_enabled", False)
            if type(google_enabled) is not bool or type(google_write_enabled) is not bool:
                raise TypeError
            return cls(
                resolved,
                require_text(str(data["machine_id"]), "machine_id"),
                require_text(str(data["environment"]), "environment"),
                UUID(str(data["binding_id"])),
                require_text(str(data["spreadsheet_id"]), "spreadsheet_id"),
                normalize_email(str(data["expected_owner_email"])),
                contract_version,
                UUID(str(data["credential_reference_id"])),
                google_enabled,
                google_write_enabled,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("ProjectOS Google configuration is invalid") from exc

    @staticmethod
    def resolve_path(
        path: Path | str | None,
        environ: Mapping[str, str],
        family: HostFamily | None = None,
        home: Path | PurePath | None = None,
    ) -> PurePath:
        selected_family = family or detect_host_family()
        selected_home = home or environ.get("HOME") or environ.get("USERPROFILE") or Path.home()
        return resolve_platform_paths(
            selected_family,
            environ,
            selected_home,
            PlatformPathOverrides(config_path=path),
        ).config_path
