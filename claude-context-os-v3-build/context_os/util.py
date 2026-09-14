from __future__ import annotations
import hashlib, json, uuid
from datetime import datetime, timezone
from pathlib import Path

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def uid(prefix: str):
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"

def write_json(path: Path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding='utf-8')

def read_json(path: Path, default=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception: return default

def sha256_file(path: Path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()
