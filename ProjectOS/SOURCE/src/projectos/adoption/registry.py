from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping

from projectos.adoption.manifest import ExtensionManifest
from projectos.errors import ValidationError
from projectos.validation import reject_secret_material, require_text


REGISTRY_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_ENTRY_FIELDS = {
    "extension_id",
    "product_version",
    "manifest",
    "bundle_sha256",
    "enabled",
    "adopted_at",
}


def _manifest_path(value: object) -> str:
    text = require_text(str(value), "manifest")
    posix = PurePosixPath(text)
    windows = PureWindowsPath(text)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or "\\" in text
        or any(part in {"", ".", ".."} for part in posix.parts)
        or len(posix.parts) < 4
        or posix.parts[:2] != ("projectos", "versions")
        or posix.name != "manifest.json"
    ):
        raise ValidationError("registry manifest path is invalid")
    return posix.as_posix()


@dataclass(frozen=True)
class ProjectOSExtensionEntry:
    extension_id: str
    product_version: str
    manifest: str
    bundle_sha256: str
    enabled: bool
    adopted_at: str

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, object]
    ) -> "ProjectOSExtensionEntry":
        if set(value) != _ENTRY_FIELDS:
            raise ValidationError("ProjectOS registry entry fields are invalid")
        if type(value.get("enabled")) is not bool:
            raise ValidationError("ProjectOS registry enabled state is invalid")
        string_fields = (
            "extension_id",
            "product_version",
            "manifest",
            "bundle_sha256",
            "adopted_at",
        )
        if any(not isinstance(value.get(field), str) for field in string_fields):
            raise ValidationError("ProjectOS registry entry field type is invalid")
        extension_id = require_text(value["extension_id"], "extension_id")
        product_version = require_text(value["product_version"], "product_version")
        bundle_sha256 = require_text(value["bundle_sha256"], "bundle_sha256")
        if extension_id != "projectos":
            raise ValidationError("ProjectOS registry extension_id is invalid")
        if not _VERSION.fullmatch(product_version):
            raise ValidationError("ProjectOS registry product_version is invalid")
        if not _SHA256.fullmatch(bundle_sha256):
            raise ValidationError("ProjectOS registry bundle_sha256 is invalid")
        return cls(
            extension_id,
            product_version,
            _manifest_path(value["manifest"]),
            bundle_sha256,
            value["enabled"],
            require_text(value["adopted_at"], "adopted_at"),
        )

    def with_enabled(self, enabled: bool) -> "ProjectOSExtensionEntry":
        if type(enabled) is not bool:
            raise ValidationError("ProjectOS registry enabled state is invalid")
        mapping = self.to_mapping()
        mapping["enabled"] = enabled
        return ProjectOSExtensionEntry.from_mapping(mapping)

    def to_mapping(self) -> dict[str, object]:
        return {
            "extension_id": self.extension_id,
            "product_version": self.product_version,
            "manifest": self.manifest,
            "bundle_sha256": self.bundle_sha256,
            "enabled": self.enabled,
            "adopted_at": self.adopted_at,
        }


@dataclass(frozen=True)
class ExtensionRegistry:
    _extensions_json: str

    @classmethod
    def empty(cls) -> "ExtensionRegistry":
        return cls("{}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ExtensionRegistry":
        reject_secret_material(value)
        if set(value) != {"registry_version", "extensions"}:
            raise ValidationError("extension registry fields are invalid")
        if type(value.get("registry_version")) is not int:
            raise ValidationError("extension registry version is invalid")
        if value["registry_version"] != REGISTRY_VERSION:
            raise ValidationError("extension registry version is incompatible")
        extensions = value.get("extensions")
        if not isinstance(extensions, Mapping):
            raise ValidationError("extension registry extensions are invalid")
        folded: set[str] = set()
        normalized: dict[str, object] = {}
        for key, nested in extensions.items():
            if not isinstance(key, str) or not key.strip():
                raise ValidationError("extension registry namespace is invalid")
            casefolded = key.casefold()
            if casefolded in folded:
                raise ValidationError("extension registry namespace is duplicated")
            folded.add(casefolded)
            if casefolded == "projectos" and key != "projectos":
                raise ValidationError("ProjectOS registry namespace is invalid")
            if key == "projectos":
                if not isinstance(nested, Mapping):
                    raise ValidationError("ProjectOS registry entry is invalid")
                normalized[key] = ProjectOSExtensionEntry.from_mapping(nested).to_mapping()
            else:
                normalized[key] = nested
        try:
            encoded = json.dumps(
                normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError("extension registry values are not JSON compatible") from exc
        return cls(encoded)

    @classmethod
    def load(cls, path: str | Path) -> "ExtensionRegistry":
        registry_path = Path(path)
        if not registry_path.exists():
            return cls.empty()
        try:
            value = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("extension registry is unavailable or invalid") from exc
        if not isinstance(value, dict):
            raise ValidationError("extension registry is unavailable or invalid")
        return cls.from_mapping(value)

    def _extensions(self) -> dict[str, object]:
        return json.loads(self._extensions_json)

    def to_mapping(self) -> dict[str, object]:
        return {
            "registry_version": REGISTRY_VERSION,
            "extensions": self._extensions(),
        }

    def canonical_bytes(self) -> bytes:
        return (
            json.dumps(
                self.to_mapping(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")

    def with_projectos(
        self, entry: ProjectOSExtensionEntry
    ) -> "ExtensionRegistry":
        validated = ProjectOSExtensionEntry.from_mapping(entry.to_mapping())
        extensions = self._extensions()
        extensions["projectos"] = validated.to_mapping()
        return ExtensionRegistry.from_mapping(
            {"registry_version": REGISTRY_VERSION, "extensions": extensions}
        )

    def without_projectos(self) -> "ExtensionRegistry":
        extensions = self._extensions()
        extensions.pop("projectos", None)
        return ExtensionRegistry.from_mapping(
            {"registry_version": REGISTRY_VERSION, "extensions": extensions}
        )

    def projectos_entry(self) -> ProjectOSExtensionEntry | None:
        nested = self._extensions().get("projectos")
        if nested is None:
            return None
        if not isinstance(nested, Mapping):
            raise ValidationError("ProjectOS registry entry is invalid")
        return ProjectOSExtensionEntry.from_mapping(nested)


def plan_projectos_entry(
    manifest: ExtensionManifest,
    bundle_sha256: str,
    relative_manifest_path: str,
    adopted_at: str,
    *,
    enabled: bool,
) -> ProjectOSExtensionEntry:
    manifest.validate()
    return ProjectOSExtensionEntry.from_mapping(
        {
            "extension_id": manifest.extension_id,
            "product_version": manifest.product_version,
            "manifest": relative_manifest_path,
            "bundle_sha256": bundle_sha256,
            "enabled": enabled,
            "adopted_at": adopted_at,
        }
    )


def plan_disabled_entry(
    manifest: ExtensionManifest,
    bundle_sha256: str,
    relative_manifest_path: str,
    adopted_at: str,
) -> ProjectOSExtensionEntry:
    return plan_projectos_entry(
        manifest,
        bundle_sha256,
        relative_manifest_path,
        adopted_at,
        enabled=False,
    )
