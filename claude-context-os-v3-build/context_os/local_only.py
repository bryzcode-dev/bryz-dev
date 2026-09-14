from __future__ import annotations
import ast, shutil, subprocess
from pathlib import Path

NETWORK_IMPORTS={'requests','httpx','aiohttp','urllib.request','socket'}
OPTIONAL_TOOLS=['gitleaks','opa','ast-grep','restic','basic-memory','serena']

def audit_runtime_code(package_root:Path)->dict:
    root=Path(package_root); findings=[]
    for p in [root/'context_os', root/'contextctl.py']:
        files=[p] if p.is_file() else list(p.rglob('*.py')) if p.exists() else []
        for f in files:
            try: tree=ast.parse(f.read_text(encoding='utf-8'))
            except Exception as ex: findings.append({'file':str(f),'kind':'parse_error','detail':str(ex)});continue
            for n in ast.walk(tree):
                if isinstance(n,ast.Import):
                    for a in n.names:
                        if a.name in NETWORK_IMPORTS or any(a.name.startswith(x+'.') for x in NETWORK_IMPORTS):findings.append({'file':str(f),'kind':'network_import','detail':a.name})
                elif isinstance(n,ast.ImportFrom):
                    mod=n.module or ''
                    if mod in NETWORK_IMPORTS or any(mod.startswith(x+'.') for x in NETWORK_IMPORTS):findings.append({'file':str(f),'kind':'network_import','detail':mod})
    return {'ok':not findings,'runtime_web_dependencies':False if not findings else 'review','findings':findings}

def _version(path):
    try:
        cp=subprocess.run([path,'--version'],capture_output=True,text=True,timeout=3)
        return (cp.stdout or cp.stderr).strip().splitlines()[0][:200] if (cp.stdout or cp.stderr).strip() else 'installed'
    except Exception:
        return 'installed'

def tool_status()->dict:
    out={}
    for name in OPTIONAL_TOOLS:
        path=shutil.which(name)
        if path:
            out[name]={'installed':True,'path':path,'version':_version(path)}
        else:
            out[name]={'installed':False}
    # ast-grep also ships the short binary name `sg`, but macOS/Linux may have an unrelated /usr/bin/sg.
    if not out['ast-grep']['installed']:
        alias=shutil.which('sg')
        if alias:
            ver=_version(alias)
            if 'ast-grep' in ver.lower():
                out['ast-grep']={'installed':True,'path':alias,'version':ver,'alias':'sg'}
    return out
