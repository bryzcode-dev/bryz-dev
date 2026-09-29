from __future__ import annotations

import hashlib
from dataclasses import dataclass

from projectos.acceptance.model import ACCEPTANCE_TASKS
from projectos.adoption.scheduler import SchedulerDefinition


_PRODUCTION_TASKS = {
    "macos": "com.contextos.projectos.sync",
    "windows": r"ContextOS\ProjectOS\Sync",
}


@dataclass(frozen=True)
class DefinitionEquivalence:
    equivalent: bool
    allowed_differences: tuple[str, ...]
    differences: tuple[str, ...]


def _normalized_content(definition: SchedulerDefinition) -> bytes:
    content = definition.content
    replacements = (
        (b"projectos.acceptance_probe", b"projectos.__ENTRYPOINT__"),
        (b"projectos.cli", b"projectos.__ENTRYPOINT__"),
        (ACCEPTANCE_TASKS["macos"].encode(), b"__PROJECTOS_TASK__"),
        (b"com.contextos.projectos.sync", b"__PROJECTOS_TASK__"),
    )
    for old, new in replacements:
        content = content.replace(old, new)
    return content


def _normalized_argv(definition: SchedulerDefinition) -> tuple[str, ...]:
    return tuple(
        "projectos.__ENTRYPOINT__"
        if value in {"projectos.cli", "projectos.acceptance_probe"}
        else value
        for value in definition.argv
    )


def compare_scheduler_definitions(
    production: SchedulerDefinition,
    acceptance: SchedulerDefinition,
) -> DefinitionEquivalence:
    differences: list[str] = []
    if production.host_family is not acceptance.host_family:
        differences.append("host_family")
    if production.scheduler_kind is not acceptance.scheduler_kind:
        differences.append("scheduler_kind")
    if production.task_id != _PRODUCTION_TASKS.get(production.host_family.value):
        differences.append("production_task_id")
    if acceptance.task_id != ACCEPTANCE_TASKS.get(acceptance.host_family.value):
        differences.append("acceptance_task_id")
    if production.interval_seconds != acceptance.interval_seconds:
        differences.append("interval_seconds")
    if production.execution_limit_seconds != acceptance.execution_limit_seconds:
        differences.append("execution_limit_seconds")
    if production.enabled != acceptance.enabled:
        differences.append("enabled")
    if hashlib.sha256(production.content).hexdigest() != production.sha256:
        differences.append("production_definition_hash")
    if hashlib.sha256(acceptance.content).hexdigest() != acceptance.sha256:
        differences.append("acceptance_definition_hash")
    if _normalized_argv(production) != _normalized_argv(acceptance):
        differences.append("argv")
    if _normalized_content(production) != _normalized_content(acceptance):
        differences.append("content")
    return DefinitionEquivalence(
        not differences,
        ("entrypoint_module", "task_id"),
        tuple(differences),
    )
