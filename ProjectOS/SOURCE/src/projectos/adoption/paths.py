from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Mapping

from projectos.adoption.host import HostFamily, detect_host_family
from projectos.adoption.path_policy import HostPathPolicy
from projectos.errors import ValidationError


HostPath = PurePosixPath | PureWindowsPath


@dataclass(frozen=True)
class PlatformPathOverrides:
    runtime_root: str | PurePath | None = None
    database_path: str | PurePath | None = None
    config_path: str | PurePath | None = None


@dataclass(frozen=True)
class PlatformPaths:
    runtime_root: HostPath
    database_path: HostPath
    config_path: HostPath
    lock_path: HostPath
    log_root: HostPath
    staging_root: HostPath


def _path_type(family: HostFamily):
    return PureWindowsPath if family is HostFamily.WINDOWS else PurePosixPath


def _absolute(
    family: HostFamily, value: str | PurePath, home: str | PurePath
) -> HostPath:
    path_type = _path_type(family)
    text = str(value)
    if text == "~":
        path = path_type(str(home))
    elif text.startswith("~/") or text.startswith("~\\"):
        path = path_type(str(home)) / text[2:]
    else:
        path = path_type(text)
    HostPathPolicy(family).normalize(path)
    return path


def resolve_platform_paths(
    family: HostFamily,
    environ: Mapping[str, str],
    home: str | PurePath,
    overrides: PlatformPathOverrides | None = None,
) -> PlatformPaths:
    family = HostFamily(family)
    values = dict(environ)
    selected = overrides or PlatformPathOverrides()
    path_type = _path_type(family)
    if selected.runtime_root is not None:
        runtime_value = selected.runtime_root
    elif values.get("PROJECTOS_HOME"):
        runtime_value = values["PROJECTOS_HOME"]
    elif family is HostFamily.MACOS:
        runtime_value = path_type(str(home)) / "Library" / "Application Support" / "ProjectOS"
    else:
        local_app_data = values.get("LOCALAPPDATA", "").strip()
        if not local_app_data:
            raise ValidationError("LOCALAPPDATA is required unless PROJECTOS_HOME is explicit")
        runtime_value = path_type(local_app_data) / "ProjectOS"
    runtime = _absolute(family, runtime_value, home)
    database = _absolute(
        family,
        selected.database_path or values.get("PROJECTOS_DB") or runtime / "projectos.db",
        home,
    )
    config = _absolute(
        family,
        selected.config_path or values.get("PROJECTOS_CONFIG") or runtime / "projectos.toml",
        home,
    )
    log_root = (
        path_type(str(home)) / "Library" / "Logs" / "ProjectOS"
        if family is HostFamily.MACOS
        else runtime / "logs"
    )
    return PlatformPaths(
        runtime,
        database,
        config,
        runtime / "projectos.sync.lock",
        _absolute(family, log_root, home),
        runtime / "staging",
    )


def default_database_path(
    family: HostFamily | None = None,
    environ: Mapping[str, str] | None = None,
    home: str | PurePath | None = None,
) -> Path:
    selected_family = family or detect_host_family()
    values = dict(os.environ if environ is None else environ)
    selected_home = home or values.get("HOME") or values.get("USERPROFILE") or Path.home()
    resolved = resolve_platform_paths(selected_family, values, selected_home).database_path
    return Path(resolved)
