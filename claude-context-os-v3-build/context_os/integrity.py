from __future__ import annotations
from pathlib import Path
from .util import sha256_file, write_json

def build_manifest(root:Path,rel_paths):
    root=Path(root); files={}
    for rel in rel_paths:
        p=root/rel
        if p.exists() and p.is_file(): files[str(rel)]={'sha256':sha256_file(p),'size':p.stat().st_size}
    return {'files':files}

def verify_manifest(root:Path,manifest:dict):
    errors=[]; root=Path(root)
    for rel,meta in manifest.get('files',{}).items():
        p=root/rel
        if not p.exists(): errors.append(f'missing:{rel}')
        elif sha256_file(p)!=meta['sha256']: errors.append(f'drift:{rel}')
    return {'ok':not errors,'errors':errors}
