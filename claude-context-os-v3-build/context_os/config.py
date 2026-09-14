from __future__ import annotations
import json
from pathlib import Path

DEFAULT_VERSION = '3.0.1'

def detect_storage_kind(path: Path) -> str:
    p = Path(path).expanduser()
    return 'network_or_removable' if str(p).startswith('/Volumes/') else 'local'

def load_config(path: Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding='utf-8'))

def save_config(path: Path, data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding='utf-8')

def expand_path_template(value: str | Path, home: Path | None = None) -> Path:
    text = str(value)
    base = Path(home) if home is not None else Path.home()
    if text == '~':
        return base.resolve()
    if text.startswith('~/'):
        return (base / text[2:]).resolve()
    return Path(text).expanduser().resolve()

def resolve_paths(claude_root: Path, runtime_root: Path | None = None) -> dict:
    root = Path(claude_root).expanduser().resolve()
    if runtime_root:
        runtime = Path(runtime_root).expanduser().resolve()
    else:
        runtime = Path.home() / 'Library' / 'Application Support' / 'ClaudeContextOS'
    return {
        'claude_root': str(root),
        'runtime_root': str(runtime),
        'storage_kind': detect_storage_kind(root),
    }
