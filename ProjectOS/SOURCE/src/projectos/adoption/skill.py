from __future__ import annotations

from pathlib import Path

from projectos.adoption.bundle import ArtifactPolicy
from projectos.adoption.manifest import ExtensionManifest, LOOKER_CAPABILITIES
from projectos.errors import ValidationError


SKILL_DESCRIPTION = "ContextOS ProjectOS project and connection management."

_BODY = """# ProjectOS

Use only the adapter capabilities declared above. Do not embed or execute shell commands or resolved local paths.

Synchronize through the ProjectOS runtime adapter before answering state-dependent questions. Report lock contention using only the bounded adapter result.

Authorization: Owner has full access and is the only role allowed to change users. Admin may edit projects but cannot see the admin menu. User is view-only and cannot see the admin menu.

Visibility: PUBLIC projects are visible to all authorized users. PRIVATE projects are visible only to Owner.

Looker capabilities are unavailable in this skill.
"""

_LOOKER_BODY = """# ProjectOS

Use only the adapter capabilities declared above. Do not embed or execute shell commands or resolved local paths.

Synchronize through the ProjectOS runtime adapter before answering state-dependent questions. Report lock contention using only the bounded adapter result.

Authorization: Owner has full access and is the only role allowed to change users. Admin may edit projects but cannot see the admin menu. User is view-only and cannot see the admin menu.

Visibility: PUBLIC projects are visible to all authorized users. PRIVATE projects are visible only to Owner.

Looker queries are read-only. They may inspect status, assets, dependencies, findings, impact, and reconciliation reports. They never import evidence, create waivers, refresh data, perform cutover, execute arbitrary SQL, or resolve credentials.
"""


def effective_capabilities(
    manifest: ExtensionManifest, actual_schema_version: int
) -> tuple[str, ...]:
    capabilities = set(manifest.skill.capabilities)
    if manifest.database_schema_version < 3 or actual_schema_version < 3:
        capabilities.difference_update(LOOKER_CAPABILITIES)
    return tuple(sorted(capabilities))


def render_projectos_skill(manifest: ExtensionManifest) -> bytes:
    manifest.validate()
    capabilities = "".join(
        f"  - {capability}\n" for capability in sorted(manifest.skill.capabilities)
    )
    content = (
        "---\n"
        "name: projectos\n"
        f"description: {SKILL_DESCRIPTION}\n"
        f"version: {manifest.skill.version}\n"
        "capabilities:\n"
        f"{capabilities}"
        "---\n"
        f"{_LOOKER_BODY if LOOKER_CAPABILITIES.intersection(manifest.skill.capabilities) else _BODY}"
    )
    return content.encode("utf-8")


def verify_projectos_skill(
    content: bytes,
    manifest: ExtensionManifest,
    policy: ArtifactPolicy,
) -> None:
    expected = render_projectos_skill(manifest)
    if content != expected:
        raise ValidationError("ProjectOS skill is not canonical")
    policy.inspect(manifest.skill.path, Path(manifest.skill.path), content)
