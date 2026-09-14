from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def inventory_tree(root: Path) -> list[dict]:
    root = Path(root).expanduser().resolve()
    if not root.exists():
        return []
    rows: list[dict] = []
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root).as_posix()
        st = p.lstat()
        mode = stat.S_IMODE(st.st_mode)
        if p.is_symlink():
            rows.append({'path': rel, 'type': 'symlink', 'size': st.st_size, 'mode': oct(mode), 'target': os.readlink(p)})
        elif p.is_dir():
            rows.append({'path': rel, 'type': 'dir', 'size': 0, 'mode': oct(mode)})
        elif p.is_file():
            rows.append({'path': rel, 'type': 'file', 'size': st.st_size, 'mode': oct(mode), 'sha256': sha256_file(p)})
        else:
            rows.append({'path': rel, 'type': 'other', 'size': st.st_size, 'mode': oct(mode)})
    return rows


def file_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get('type') in {'file', 'symlink'}]
