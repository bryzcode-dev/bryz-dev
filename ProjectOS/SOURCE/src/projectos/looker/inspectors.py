from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from projectos.errors import ValidationError

from .model import LookerIntake


_MAX_SOURCE_BYTES = 1_048_576
_MAX_SUMMARY = 512
_SECRET = re.compile(r"(?i)(token|password|secret|api[_-]?key)\s*[:=]\s*\S+")


class ProcessResult(Protocol):
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


class ProcessExecutor(Protocol):
    def run(self, argv: tuple[str, ...], timeout_seconds: int, working_directory: Path) -> ProcessResult: ...


@dataclass(frozen=True)
class GitInspection:
    head: str
    branch: str
    dirty: bool
    behind: int
    ahead: int
    remote: str
    primary_branch: str


@dataclass(frozen=True)
class LegacyInspection:
    spreadsheet_id: str
    sheet_tabs: tuple[str, ...]
    script_id: str
    deployment_ids: tuple[str, ...]


@dataclass(frozen=True)
class AutomationItem:
    kind: str
    path_sha256: str
    content_sha256: str
    byte_count: int
    line_count: int


@dataclass(frozen=True)
class AutomationInspection:
    items: tuple[AutomationItem, ...]


@dataclass(frozen=True)
class ValidationResult:
    command_id: str
    passed: bool
    returncode: int
    timed_out: bool
    parser: str
    summary: str


def _git(executor: ProcessExecutor, root: Path, *arguments: str) -> str:
    result = executor.run(("git", *arguments), 30, root)
    if result.timed_out or result.returncode != 0:
        raise ValidationError("read-only Git inspection failed")
    return str(result.stdout).strip()


def inspect_git(intake: LookerIntake, repository_root: Path, executor: ProcessExecutor) -> GitInspection:
    root = Path(repository_root)
    head = _git(executor, root, "rev-parse", "HEAD")
    if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", head) is None:
        raise ValidationError("Git HEAD is invalid")
    branch = _git(executor, root, "branch", "--show-current")
    dirty = bool(_git(executor, root, "status", "--porcelain"))
    divergence = _git(executor, root, "rev-list", "--left-right", "--count", f"{intake.git['primary_branch']}...HEAD")
    try:
        behind_text, ahead_text = divergence.split()
        behind, ahead = int(behind_text), int(ahead_text)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Git divergence is invalid") from exc
    return GitInspection(head, branch, dirty, behind, ahead, str(intake.git["remote"]), str(intake.git["primary_branch"]))


def inspect_legacy(intake: LookerIntake) -> LegacyInspection:
    return LegacyInspection(str(intake.master_sheet["spreadsheet_id"]), tuple(str(item) for item in intake.master_sheet["tabs"]), str(intake.gas["script_id"]), tuple(str(item) for item in intake.gas["deployment_ids"]))


def _automation_item(kind: str, value: str) -> AutomationItem:
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise ValidationError("declared automation source must be a regular non-symlink file")
    content = path.read_bytes()
    if len(content) > _MAX_SOURCE_BYTES:
        raise ValidationError("declared automation source exceeds the size limit")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("declared automation source must be UTF-8 text") from exc
    return AutomationItem(kind, hashlib.sha256(str(path.resolve(strict=False)).encode()).hexdigest(), hashlib.sha256(content).hexdigest(), len(content), len(text.splitlines()))


def inspect_automation(intake: LookerIntake) -> AutomationInspection:
    items = [_automation_item("scheduler", path) for path in intake.scheduler_definition_paths]
    items.extend(_automation_item("sync_script", path) for path in intake.sync_script_paths)
    return AutomationInspection(tuple(sorted(items, key=lambda item: (item.kind, item.content_sha256))))


def _summary(result: ProcessResult, parser: str) -> str:
    if result.timed_out:
        return "TIMEOUT"
    text = f"{result.stdout}\n{result.stderr}".strip()
    text = _SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    if parser == "STATUS_ONLY":
        return "PASS" if result.returncode == 0 else "FAIL"
    return text[:_MAX_SUMMARY]


def run_validations(intake: LookerIntake, executor: ProcessExecutor) -> tuple[ValidationResult, ...]:
    results = []
    for command in intake.validation_commands:
        result = executor.run((command.executable, *command.arguments), command.timeout_seconds, Path(command.working_directory))
        results.append(ValidationResult(command.command_id, not result.timed_out and result.returncode in command.expected_exit_codes, int(result.returncode), bool(result.timed_out), command.parser, _summary(result, command.parser)))
    return tuple(results)
