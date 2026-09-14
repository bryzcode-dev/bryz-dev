from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def rollback(active_root: Path, rollback_root: Path) -> dict:
    active = Path(active_root).resolve()
    old = Path(rollback_root).resolve()
    if not old.exists():
        raise FileNotFoundError(f'Rollback root not found: {old}')
    displaced = active.parent / f'claude-context-os-failed-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}'
    if active.exists():
        active.rename(displaced)
    try:
        old.rename(active)
    except Exception:
        if displaced.exists() and not active.exists():
            displaced.rename(active)
        raise
    return {'restored': str(active), 'displaced_context_os': str(displaced) if displaced.exists() else None}
