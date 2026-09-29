from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path, PurePath
from typing import Any, Sequence

from projectos.acceptance.authority import (
    ACCEPTANCE_ACKNOWLEDGEMENT,
    AcceptanceTarget,
    detect_host_session,
)
from projectos.acceptance.commands import HostPreflightPlan
from projectos.acceptance.equivalence import compare_scheduler_definitions
from projectos.acceptance.host_context import (
    HostAcceptanceContextFactory,
    recover_prepared_acceptance,
    run_prepared_acceptance,
)
from projectos.acceptance.journal import HostAcceptanceState
from projectos.acceptance.native import RecordingProcessExecutor
from projectos.acceptance.native_macos import MacOSNativeSchedulerRunner
from projectos.acceptance.native_windows import WindowsNativeSchedulerRunner
from projectos.acceptance.package import verify_acceptance_package
from projectos.acceptance.preparation import (
    AcceptancePreparationRequest,
    AcceptancePreparer,
)
from projectos.acceptance.profile import AcceptanceProfile, acceptance_machine_profile
from projectos.acceptance.store import LocalAcceptanceStore
from projectos.adoption.fixture import FIXTURE_MARKER
from projectos.adoption.host import HostFamily
from projectos.adoption.profile import machine_profile_from_mapping
from projectos.adoption.scheduler import adapter_for
from projectos.errors import ValidationError


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValidationError("invalid host acceptance arguments")


def _parser() -> _Parser:
    parser = _Parser(prog="python -m projectos.acceptance_host")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "preflight", "run", "recover"):
        selected = commands.add_parser(name)
        selected.add_argument("--acceptance-root", type=Path, required=True)
        selected.add_argument("--runtime-root", type=Path, required=True)
        selected.add_argument("--fixture-root", type=Path, required=True)
        selected.add_argument("--machine-profile", type=Path, required=True)
        selected.add_argument("--package", type=Path, required=True)
        selected.add_argument("--evidence-root", type=Path, required=True)
        selected.add_argument("--acceptance-ack", required=True)
        selected.add_argument("--fixture-ack", required=True)
        if name == "recover":
            selected.add_argument("--run-id", required=True)
    return parser


def _preparation_request(arguments) -> AcceptancePreparationRequest:
    return AcceptancePreparationRequest(
        arguments.acceptance_root,
        arguments.runtime_root,
        arguments.fixture_root,
        arguments.machine_profile,
        arguments.package,
        arguments.evidence_root,
        arguments.acceptance_ack,
        arguments.fixture_ack,
    )


def prepare_host(arguments) -> dict[str, str]:
    prepared = AcceptancePreparer().prepare(
        _preparation_request(arguments), session=detect_host_session()
    )
    return {
        "preparation_id": prepared.record.preparation_id,
        "support_state": "SIMULATED",
    }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _read_machine_profile(path: Path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("machine profile is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValidationError("machine profile is unavailable or invalid")
    return machine_profile_from_mapping(value)


def plan_host_preflight(arguments) -> HostPreflightPlan:
    return HostAcceptanceContextFactory().preflight(
        _preparation_request(arguments), session=detect_host_session()
    ).plan


def main(argv: Sequence[str] | None = None) -> int:
    command = "host"
    try:
        arguments = _parser().parse_args(argv)
        command = arguments.command
        if arguments.acceptance_ack != ACCEPTANCE_ACKNOWLEDGEMENT:
            raise ValidationError("clean-host acknowledgement is invalid")
        if arguments.fixture_ack != "FIXTURE_ONLY":
            raise ValidationError("fixture acknowledgement is invalid")
        if command == "prepare":
            data = prepare_host(arguments)
            payload = {"ok": True, "command": command, "data": data, "errors": []}
            code = 0
        elif command == "preflight":
            plan = plan_host_preflight(arguments)
            payload = {"ok": True, "command": command, "data": _jsonable(plan), "errors": []}
            code = 0
        elif command == "run":
            result = run_prepared_acceptance(
                _preparation_request(arguments), session=detect_host_session()
            )
            complete = result.state is HostAcceptanceState.EVIDENCE_SEALED
            payload = {
                "ok": complete,
                "command": command,
                "data": _jsonable(result),
                "errors": [] if complete else [{"code": "acceptance_incomplete", "message": "host acceptance recovered without sealed evidence"}],
            }
            code = 0 if complete else 3
        elif command == "recover":
            result = recover_prepared_acceptance(
                _preparation_request(arguments), arguments.run_id,
                session=detect_host_session(),
            )
            complete = result.state is HostAcceptanceState.EVIDENCE_SEALED
            payload = {
                "ok": complete,
                "command": command,
                "data": _jsonable(result),
                "errors": [] if complete else [{"code": "acceptance_recovered", "message": "host acceptance cleanup completed without sealed evidence"}],
            }
            code = 0 if complete else 3
    except ValidationError:
        payload = {"ok": False, "command": command, "data": None, "errors": [{"code": "validation_error", "message": "host acceptance validation failed"}]}
        code = 2
    except BaseException:
        payload = {"ok": False, "command": command, "data": None, "errors": [{"code": "internal_error", "message": "unexpected internal error"}]}
        code = 1
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
