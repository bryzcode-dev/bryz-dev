"""Minimal dependency-free PEP 517 backend for ProjectOS's pure-Python wheel."""

from __future__ import annotations

import base64
import hashlib
import os
import tomllib
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "src"


def _project() -> dict[str, Any]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def _normalized_name(name: str) -> str:
    return name.replace("-", "_").replace(".", "_")


def _dist_info() -> str:
    project = _project()
    return f"{_normalized_name(project['name'])}-{project['version']}.dist-info"


def _metadata() -> bytes:
    project = _project()
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {project['name']}",
        f"Version: {project['version']}",
        f"Summary: {project['description']}",
        f"Requires-Python: {project['requires-python']}",
    ]
    for extra, requirements in sorted(project.get("optional-dependencies", {}).items()):
        lines.append(f"Provides-Extra: {extra}")
        for requirement in requirements:
            lines.append(f"Requires-Dist: {requirement}; extra == '{extra}'")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _dist_info_files() -> dict[str, bytes]:
    directory = _dist_info()
    return {
        f"{directory}/METADATA": _metadata(),
        f"{directory}/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: projectos-build-backend\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ).encode("utf-8"),
        f"{directory}/entry_points.txt": (
            "[console_scripts]\nprojectos = projectos.cli:main\n"
        ).encode("utf-8"),
        f"{directory}/top_level.txt": b"projectos\n",
    }


def get_requires_for_build_wheel(config_settings: dict[str, Any] | None = None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str, config_settings: dict[str, Any] | None = None
) -> str:
    destination = Path(metadata_directory)
    for archive_path, content in _dist_info_files().items():
        relative = Path(archive_path).relative_to(_dist_info())
        target = destination / _dist_info() / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return _dist_info()


def _hash(content: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=")
    return "sha256=" + digest.decode("ascii")


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100644 & 0xFFFF) << 16
    return info


def _source_entries() -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    for source in sorted((SOURCE / "projectos").rglob("*")):
        if source.is_symlink():
            raise RuntimeError("wheel source must not contain a symbolic link")
        relative = source.relative_to(SOURCE).as_posix()
        acceptance_asset = relative.startswith("projectos/acceptance/assets/") and source.suffix in {
            ".sh",
            ".ps1",
            ".md",
        }
        if source.is_file() and (source.suffix in {".py", ".sql"} or acceptance_asset):
            entries[relative] = source.read_bytes()
    return entries


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    project = _project()
    wheel_name = (
        f"{_normalized_name(project['name'])}-{project['version']}-py3-none-any.whl"
    )
    destination = Path(wheel_directory)
    destination.mkdir(parents=True, exist_ok=True)
    entries = _source_entries()
    entries.update(_dist_info_files())
    record_path = f"{_dist_info()}/RECORD"
    record_lines = [
        f"{path},{_hash(content)},{len(content)}" for path, content in sorted(entries.items())
    ]
    record_lines.append(f"{record_path},,")
    entries[record_path] = ("\n".join(record_lines) + "\n").encode("utf-8")
    temporary = destination / f".{wheel_name}.{os.getpid()}.tmp"
    with zipfile.ZipFile(temporary, "w") as archive:
        for path, content in sorted(entries.items()):
            archive.writestr(_zip_info(path), content)
    os.replace(temporary, destination / wheel_name)
    return wheel_name
