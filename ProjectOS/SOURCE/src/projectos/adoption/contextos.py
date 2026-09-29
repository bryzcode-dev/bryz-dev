from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Mapping

from projectos.adoption.host import HostFamily
from projectos.errors import ValidationError
from projectos.validation import require_text


CONTEXTOS_EXTENSION_CONTRACT_VERSION = 1
_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_MIN_CONTEXTOS_VERSION = (3, 0, 1)
_MAX_CONTEXTOS_VERSION = (4, 0, 0)


class ContextOSCompatibilityError(ValidationError):
    pass


def _version(value: object) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.fullmatch(str(value))
    if match is None:
        raise ContextOSCompatibilityError("ContextOS version is invalid")
    return tuple(int(item) for item in match.groups())


def _relative_path(value: object, field: str, family: HostFamily) -> str:
    text = require_text(str(value), field)
    path_type = PureWindowsPath if family is HostFamily.WINDOWS else PurePosixPath
    path = path_type(text)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ContextOSCompatibilityError(f"{field} must stay within the ContextOS root")
    return str(path)


@dataclass(frozen=True)
class ContextOSExtensionContract:
    contract_version: int
    contextos_version: str
    extensions_root: str
    skills_root: str
    runtime_root_template: str
    supported_hosts: tuple[HostFamily, ...]

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, object], family: HostFamily
    ) -> "ContextOSExtensionContract":
        try:
            contract_version = value["contract_version"]
            if type(contract_version) is not int:
                raise ContextOSCompatibilityError("ContextOS contract version is invalid")
            if contract_version != CONTEXTOS_EXTENSION_CONTRACT_VERSION:
                raise ContextOSCompatibilityError("ContextOS contract version is incompatible")
            contextos_version = require_text(str(value["contextos_version"]), "contextos_version")
            parsed_version = _version(contextos_version)
            if not (_MIN_CONTEXTOS_VERSION <= parsed_version < _MAX_CONTEXTOS_VERSION):
                raise ContextOSCompatibilityError("ContextOS version is incompatible")
            hosts_value = value["supported_hosts"]
            if not isinstance(hosts_value, list) or not hosts_value:
                raise ContextOSCompatibilityError("supported_hosts is invalid")
            try:
                supported_hosts = tuple(HostFamily(str(item)) for item in hosts_value)
            except ValueError as exc:
                raise ContextOSCompatibilityError("supported_hosts is invalid") from exc
            if family not in supported_hosts:
                raise ContextOSCompatibilityError(
                    f"ContextOS extension contract does not support {family.value}"
                )
            return cls(
                contract_version,
                contextos_version,
                _relative_path(value["extensions_root"], "extensions_root", family),
                _relative_path(value["skills_root"], "skills_root", family),
                require_text(str(value["runtime_root_template"]), "runtime_root_template"),
                supported_hosts,
            )
        except ContextOSCompatibilityError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ContextOSCompatibilityError("ContextOS extension contract is invalid") from exc


@dataclass(frozen=True)
class ContextOSInstallation:
    root: Path
    config_path: Path
    machine_profile_path: Path
    contract_path: Path
    contract: ContextOSExtensionContract
    machine_id: str | None

    @property
    def extensions_root(self) -> Path:
        return self.root / self.contract.extensions_root

    @property
    def skills_root(self) -> Path:
        return self.root / self.contract.skills_root


class ContextOSLocator:
    def __init__(
        self,
        family: HostFamily,
        environ: Mapping[str, str],
        home: str | PurePath,
    ) -> None:
        self.family = HostFamily(family)
        self.environ = dict(environ)
        self.home = home

    def _pure(self, value: str | PurePath) -> PurePath:
        path_type = PureWindowsPath if self.family is HostFamily.WINDOWS else PurePosixPath
        return path_type(str(value))

    def candidates(self, explicit_root: str | PurePath | None = None) -> tuple[str, ...]:
        if explicit_root is not None:
            selected = self._pure(explicit_root)
        elif self.environ.get("CONTEXTOS_ROOT"):
            selected = self._pure(self.environ["CONTEXTOS_ROOT"])
        else:
            selected = self._pure(self.home) / ".claude"
        if not selected.is_absolute():
            raise ContextOSCompatibilityError("ContextOS root must be absolute")
        if self.family is HostFamily.MACOS:
            return (str(Path(str(selected)).expanduser().resolve(strict=False)),)
        return (str(selected),)

    def inspect(self, explicit_root: str | PurePath | None = None) -> ContextOSInstallation:
        root_text = self.candidates(explicit_root)[0]
        root = Path(root_text).expanduser().resolve(strict=False)
        config_path = root / "context-os" / "config" / "context-os.json"
        contract_path = root / "context-os" / "config" / "extension-contract.json"
        machine_profile_path = root / "context-os-machine.json"
        if not contract_path.is_file():
            raise ContextOSCompatibilityError("ContextOS extension contract is missing")
        try:
            raw = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextOSCompatibilityError("ContextOS extension contract is invalid") from exc
        if not isinstance(raw, dict):
            raise ContextOSCompatibilityError("ContextOS extension contract is invalid")
        contract = ContextOSExtensionContract.from_mapping(raw, self.family)
        machine_id = None
        if machine_profile_path.exists():
            try:
                profile = json.loads(machine_profile_path.read_text(encoding="utf-8"))
                if not isinstance(profile, dict):
                    raise ValueError
                machine_id = require_text(str(profile["machine_id"]), "machine_id")
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
                ValidationError,
            ) as exc:
                raise ContextOSCompatibilityError("ContextOS machine profile is invalid") from exc
        return ContextOSInstallation(
            root,
            config_path,
            machine_profile_path,
            contract_path,
            contract,
            machine_id,
        )
