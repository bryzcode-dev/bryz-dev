#!/usr/bin/env python3
from pathlib import Path
import json,os
from _common import payload,append_event,claude_root,context_home,app_path,runtime_root
p=payload();cwd=Path(p.get('cwd') or os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()).resolve();append_event('session.started',{'cwd':str(cwd),'session_id':p.get('session_id')})
# Project-local fallback works even before registry initialization.
local_manifest=cwd/'.claude'/'project.json'; local_state=cwd/'.claude'/'state.md'
if local_manifest.exists():
    try:
        m=json.loads(local_manifest.read_text());lines=['<context-os-v3>',f"Project: {m.get('name',m.get('project_id'))} ({m.get('project_id')})",f"Types: {', '.join(m.get('types',m.get('type',[])))}"]
        if local_state.exists():
            text=local_state.read_text(encoding='utf-8',errors='replace');
            if '## Current Objective' in text:
                obj=text.split('## Current Objective',1)[1].split('##',1)[0].strip();lines.append(f'Current objective: {obj}')
        lines+=['Use /ea for the on-demand Executive Assistant.','</context-os-v3>'];print('\n'.join(lines));raise SystemExit(0)
    except SystemExit:raise
    except Exception:pass
try:
    app_path();from context_os.db import ContextDB;from context_os.tasks import TaskLedger
    db=ContextDB(runtime_root()/'context.db').initialize();rows=db.conn.execute('SELECT project_id,name,status,path FROM projects ORDER BY length(path) DESC').fetchall();project=None
    for r in rows:
        try:
            rp=Path(r['path']).resolve()
            if rp==cwd or rp in cwd.parents:project=dict(r);break
        except Exception:pass
    lines=['<context-os-v3>','Context OS V3 is active. Use /ea for the on-demand Executive Assistant.']
    if project:
        lines += [f"Project: {project['name']} ({project['project_id']})",f"Project status: {project['status']}"]
        for t in TaskLedger(claude_root(),db).list(project_id=project['project_id'],limit=5):lines.append(f"Task: {t['id']} [{t['status']}] {t['title']}")
    lines+=['Retrieve cross-project knowledge selectively; do not preload the archive.','</context-os-v3>'];print('\n'.join(lines));db.close()
except Exception:print('<context-os-v3>Context OS available; runtime index not hydrated. Use contextctl doctor if needed.</context-os-v3>')
