from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from projectos.acceptance.probe import AcceptanceProbe
from projectos.errors import ValidationError
from projectos.runtime import RuntimeTrigger


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m projectos.acceptance_probe")
    parser.add_argument("--db", required=True)
    parser.add_argument("command", choices=("runtime",))
    parser.add_argument("action", choices=("sync",))
    parser.add_argument("--machine-profile", required=True)
    parser.add_argument("--trigger", required=True, choices=(RuntimeTrigger.SCHEDULER.value,))
    return parser


def _active_case(profile_path: Path) -> tuple[str, dict[str, object] | None]:
    production_root = profile_path.parent.parent
    path = production_root / "acceptance/active-case.json"
    if not path.exists():
        return "immediate_trigger", None
    if path.is_symlink():
        raise ValidationError("acceptance active case cannot be a symlink")
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("acceptance active case is invalid") from exc
    if not isinstance(value, dict):
        raise ValidationError("acceptance active case is invalid")
    if value.get("format") == "projectos-active-acceptance-case-v1":
        if set(value) != {"case_id", "format"}:
            raise ValidationError("acceptance active case is invalid")
        native_window = None
    elif value.get("format") == "projectos-native-trigger-window-v1":
        expected = {
            "case_id", "definition_sha256", "format", "receipt_id", "release_sha256",
            "run_id", "sequence", "window_id",
        }
        if set(value) != expected:
            raise ValidationError("acceptance active case is invalid")
        native_window = value
    else:
        raise ValidationError("acceptance active case is invalid")
    canonical = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if content != canonical:
        raise ValidationError("acceptance active case is not canonical")
    return str(value["case_id"]), native_window


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        profile_path = Path(arguments.machine_profile)
        case_id, native_window = _active_case(profile_path)
        result = AcceptanceProbe().run(
            profile_path,
            Path(arguments.db),
            RuntimeTrigger(arguments.trigger),
            case_id,
            native_window=native_window,
        )
    except ValidationError as exc:
        print(json.dumps({"ok": False, "error": "VALIDATION_FAILED", "message": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": result.ok, "status": result.status, "code": result.code}, sort_keys=True))
    return 0 if result.ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
