from __future__ import annotations
import json
from dataclasses import dataclass,field
from pathlib import Path
from .inventory import inventory_tree
from .integrity import verify_manifest
from .util import read_json

@dataclass
class VerificationReport:
    ok:bool; errors:list[str]=field(default_factory=list); warnings:list[str]=field(default_factory=list)

def verify_stage(paths)->VerificationReport:
    e=[]; w=[]
    required=['CLAUDE.md','settings.json','context-os/VERSION','context-os/config/context-os.json','context-os/runtime/hooks/session_start.py','context-os/runtime/hooks/pre_tool_guard.py','context-os/runtime/app/contextctl.py','skills/ea/SKILL.md','agents/context-executive-assistant.md']
    for rel in required:
        if not (paths.stage/rel).exists(): e.append(f'Missing required file: {rel}')
    try: json.loads((paths.stage/'settings.json').read_text(encoding='utf-8'))
    except Exception as ex:e.append(f'Invalid settings.json: {ex}')
    report=read_json(paths.stage/'context-os'/'migration'/'migration-report.json',{'mappings':[]})
    # Validate coverage and backup fidelity against the frozen snapshot manifest, never
    # against the still-live Claude root. A live root may legitimately change after backup.
    src_rows=read_json(paths.workspace/'source-manifest.json',[])
    top={r['path'].split('/')[0] for r in src_rows if r['type'] in {'file','symlink'}}
    mapped={m['source'].split('/')[0] for m in report.get('mappings',[])}
    missing=sorted(top-mapped)
    if missing:e.append('Unaccounted source top-level items: '+', '.join(missing))
    bf_rows=inventory_tree(paths.backup) if paths.backup.exists() else []
    def fp(rows):
        out={}
        for r in rows:
            if r['type']=='file': out[r['path']]=('file',r.get('sha256'))
            elif r['type']=='symlink': out[r['path']]=('symlink',r.get('target'))
            elif r['type']=='dir': out[r['path']]=('dir',)
            else: out[r['path']]=(r['type'],r.get('size'))
        return out
    if fp(src_rows)!=fp(bf_rows):e.append('Backup no longer matches frozen source snapshot manifest')
    if (paths.stage/'CLAUDE.md').exists() and len((paths.stage/'CLAUDE.md').read_text(encoding='utf-8').splitlines())>200:e.append('Global CLAUDE.md exceeds 200 lines')
    return VerificationReport(not e,e,w)

def health_root(root:Path)->VerificationReport:
    root=Path(root); e=[];w=[]
    for rel in ['CLAUDE.md','settings.json','context-os/VERSION','context-os/config/context-os.json','context-os/runtime/hooks/session_start.py','skills/context-health/SKILL.md','skills/ea/SKILL.md','agents/context-executive-assistant.md']:
        if not (root/rel).exists(): e.append(f'Missing {rel}')
    try: json.loads((root/'settings.json').read_text(encoding='utf-8'))
    except Exception as ex:e.append(f'Invalid settings.json: {ex}')
    mf=read_json(root/'context-os'/'integrity'/'managed-manifest.json')
    if mf:
        vr=verify_manifest(root,mf)
        if not vr['ok']: e.extend(vr['errors'])
    if (root/'CLAUDE.md').exists() and len((root/'CLAUDE.md').read_text(encoding='utf-8').splitlines())>200:e.append('CLAUDE.md exceeds 200 lines')
    return VerificationReport(not e,e,w)
