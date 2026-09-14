from __future__ import annotations
import json, shutil, subprocess, tarfile, time
from pathlib import Path
from .config import expand_path_template, load_config
from .db import ContextDB
from .integrity import verify_manifest
from .secrets import scan_tree, gitleaks_available, scan_with_gitleaks
from .util import now_iso, read_json, write_json


def runtime_for(root:Path)->Path:
    cfg=load_config(Path(root)/'context-os'/'config'/'context-os.json')
    runtime=expand_path_template(cfg.get('paths',{}).get('runtime_root', Path(root)/'context-os'/'runtime-local'))
    if str(runtime).startswith('/Volumes/BryzConfig/Claude'):
        raise RuntimeError(f'runtime path must be local: {runtime}')
    return runtime

def reindex(root:Path)->dict:
    root=Path(root); runtime=runtime_for(root); db_path=runtime/'context.db'
    if db_path.exists():
        db_path.unlink()
    for suffix in ('-wal','-shm'):
        p=Path(str(db_path)+suffix)
        if p.exists():p.unlink()
    db=ContextDB(db_path).initialize()
    counts={'knowledge':0,'projects':0,'tasks':0}
    from .knowledge import KnowledgeStore
    from .registry import ProjectRegistry
    from .tasks import TaskLedger
    ks=KnowledgeStore(root,db); reg=ProjectRegistry(root,db); ledger=TaskLedger(root,db)
    for p in (root/'context-os'/'knowledge').glob('*.json') if (root/'context-os'/'knowledge').exists() else []:
        try:
            item=json.loads(p.read_text(encoding='utf-8')); ks.add(item); counts['knowledge']+=1
        except Exception: pass
    for p in (root/'context-os'/'projects').glob('*.json') if (root/'context-os'/'projects').exists() else []:
        try:
            item=json.loads(p.read_text(encoding='utf-8')); reg.register(item); counts['projects']+=1
            for r in item.get('resources',[]): reg.add_resource(item['project_id'],r.get('type','resource'),r.get('value',''),r.get('relation','uses'))
        except Exception: pass
    for p in (root/'context-os'/'tasks').glob('*.json') if (root/'context-os'/'tasks').exists() else []:
        try:
            row=json.loads(p.read_text(encoding='utf-8')); ledger._save(row); counts['tasks']+=1
        except Exception: pass
    db.close(); return {'ok':True,'db':str(db_path),'counts':counts}

def ingest_hook_events(root:Path, db=None)->dict:
    root=Path(root); runtime=runtime_for(root); log=runtime/'hook-events.jsonl'; state=runtime/'hook-events.offset'; own=False
    if db is None: db=ContextDB(runtime/'context.db').initialize(); own=True
    if not log.exists(): return {'ok':True,'ingested':0}
    try: offset=int(state.read_text()) if state.exists() else 0
    except Exception: offset=0
    count=0
    with log.open('r',encoding='utf-8',errors='replace') as f:
        f.seek(offset)
        for line in f:
            try:
                item=json.loads(line); eid='HOOK-'+str(abs(hash((item.get('at'),item.get('event_type'),line))))
                db.conn.execute('INSERT OR IGNORE INTO events(id,event_type,created_at,payload_json) VALUES(?,?,?,?)',(eid,item.get('event_type','hook.event'),item.get('at',now_iso()),json.dumps(item.get('payload',{})))); count+=1
            except Exception: pass
        offset=f.tell()
    db.conn.commit(); state.write_text(str(offset))
    if own: db.close()
    return {'ok':True,'ingested':count}

def doctor(root:Path)->dict:
    root=Path(root); cfg=load_config(root/'context-os'/'config'/'context-os.json'); errors=[];warnings=[];checks={}
    required=['CLAUDE.md','settings.json','context-os/VERSION','context-os/config/context-os.json','context-os/runtime/app/contextctl.py','context-os/runtime/hooks/session_start.py','skills/ea/SKILL.md','agents/context-executive-assistant.md']
    missing=[x for x in required if not (root/x).exists()]
    checks['required_files']={'ok':not missing,'missing':missing}; errors += [f'missing:{x}' for x in missing]
    mf=read_json(root/'context-os'/'integrity'/'managed-manifest.json')
    if mf:
        iv=verify_manifest(root,mf); checks['integrity']=iv
        if not iv['ok']:errors+=iv['errors']
    else: checks['integrity']={'ok':False,'errors':['manifest missing']}; errors.append('integrity manifest missing')
    runtime=runtime_for(root); checks['runtime']={'path':str(runtime),'exists':runtime.exists(),'db_exists':(runtime/'context.db').exists()}
    if not (runtime/'context.db').exists():warnings.append('runtime database missing; run reindex')
    sec=scan_tree(root,exclude_prefixes=['context-os/runtime/app','context-os/migration','context-os/logs','context-os/integrity']); checks['secret_scan']={'findings':len(sec),'gitleaks_available':gitleaks_available()}
    # secrets in source are warnings; indexing/exposure is what policy forbids.
    if sec:warnings.append(f'{len(sec)} sensitive/secret-like files detected; ensure they remain excluded from memory/indexing')
    stale=[]
    if (runtime/'context.db').exists():
        try:
            db=ContextDB(runtime/'context.db').initialize(); rows=db.conn.execute("SELECT project_id,name,updated_at FROM projects").fetchall();
            import datetime
            now=datetime.datetime.now(datetime.timezone.utc)
            for r in rows:
                try:
                    dt=datetime.datetime.fromisoformat(r['updated_at']); age=(now-dt).days
                    if age>60:stale.append({'project_id':r['project_id'],'name':r['name'],'days':age})
                except Exception:pass
            db.close()
        except Exception as ex:warnings.append(f'database health check failed: {ex}')
    checks['stale_projects']=stale
    return {'ok':not errors,'version':cfg.get('version'),'profile':cfg.get('profile'),'errors':errors,'warnings':warnings,'checks':checks}

def snapshot(root:Path,destination:Path|None=None)->dict:
    root=Path(root); dest=Path(destination) if destination else root/'context-os'/'backups'; dest.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime('%Y%m%d-%H%M%S'); archive=dest/f'context-os-snapshot-{stamp}.tar.gz'
    with tarfile.open(archive,'w:gz') as tf:
        for rel in ['CLAUDE.md','settings.json','rules','skills','commands','context-os/config','context-os/knowledge','context-os/projects','context-os/tasks','context-os/assistant','context-os/integrity']:
            p=root/rel
            if p.exists():tf.add(p,arcname=rel,recursive=True)
    return {'ok':True,'archive':str(archive),'created_at':now_iso()}

def maintain(root:Path,auto_repair=True)->dict:
    root=Path(root); actions=[];
    try: actions.append({'event_ingest':ingest_hook_events(root)})
    except Exception as ex: actions.append({'event_ingest':{'ok':False,'error':str(ex)}})
    before=doctor(root)
    if auto_repair and any('runtime database missing' in w for w in before['warnings']): actions.append({'reindex':reindex(root)})
    after=doctor(root)
    report={'at':now_iso(),'before':before,'actions':actions,'after':after}
    p=root/'context-os'/'logs'/'maintenance.json'; write_json(p,report); return report
