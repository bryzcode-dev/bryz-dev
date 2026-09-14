#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, shutil, sys, uuid
from pathlib import Path

from context_os.inventory import inventory_tree
from context_os.knowledge import add_knowledge, search_knowledge, KnowledgeStore
from context_os.registry import register_project, find_projects, ProjectRegistry
from context_os.migrate import activate_verified_stage, build_stage, prepare_migration, mark_semantic_review, MigrationPaths
from context_os.rollback import rollback
from context_os.verify import health_root, verify_stage
from context_os.config import load_config
from context_os.db import ContextDB
from context_os.tasks import TaskLedger
from context_os.assistant import ExecutiveAssistant
from context_os.compiler import ContextCompiler
from context_os.ops import doctor, reindex, snapshot, maintain, runtime_for, ingest_hook_events
from context_os.brain import ProjectBrain
from context_os.local_only import audit_runtime_code, tool_status
from context_os.topology import detect_shared_nas
from context_os.shared_migrate import (
    SharedMigration, activate_shared, build_shared_stage, prepare_shared_migration,
    probe_shared_rollback, rollback_shared, verify_shared_stage,
)
from context_os.enrollment import (
    apply_machine_enrollment, plan_machine_enrollment,
    rollback_machine_enrollment, verify_machine_enrollment,
)

HERE=Path(__file__).resolve().parent
TEMPLATE=HERE/'template_root'
PROJECT_TEMPLATE=HERE/'project_template'

def pjson(x):print(json.dumps(x,indent=2,sort_keys=True))
def _db(root:Path):return ContextDB(runtime_for(root)/'context.db').initialize()
def find_migration(workspace:Path):
    workspace=workspace.expanduser().resolve()
    if (workspace/'stage').exists() and (workspace/'backup').exists():return workspace
    dirs=sorted([p for p in workspace.iterdir() if p.is_dir()],reverse=True) if workspace.exists() else []
    if not dirs:raise FileNotFoundError('No migration directory found')
    return dirs[0]
def paths_for_workspace(workspace:Path,root:Path):
    mig=find_migration(workspace); return MigrationPaths(mig.name,root,mig,mig/'backup',mig/'stage',root.parent/f'claude-pre-context-os-{mig.name}')
def current_project(db,cwd:Path):
    try: cwd=cwd.resolve()
    except Exception:pass
    rows=db.conn.execute('SELECT project_id,path FROM projects ORDER BY length(path) DESC').fetchall()
    for r in rows:
        try:
            p=Path(r['path']).resolve()
            if p==cwd or p in cwd.parents:return r['project_id']
        except Exception:pass
    return None

def current_machine_profile():
    value=os.environ.get('CONTEXT_OS_MACHINE_PROFILE')
    path=Path(value).expanduser() if value else Path.home()/'.claude'/'context-os-machine.json'
    try:data=json.loads(path.read_text(encoding='utf-8'))
    except Exception:return None
    allowed=('version','layout','machine_id','container_root','shared_root','machine_root','facade_root','runtime_root')
    return {key:data[key] for key in allowed if key in data}

def cmd_inventory(a):
    root=Path(a.root).expanduser().resolve(); rows=inventory_tree(root); pjson({'root':str(root),'items':len(rows),'files':sum(r['type']=='file' for r in rows),'inventory':rows});return 0

def cmd_adopt(a):
    if not TEMPLATE.exists():raise RuntimeError('adopt must be run from the deployable Context OS package because template_root is required')
    root=Path(a.root).expanduser().resolve(); workspace=Path(a.workspace).expanduser().resolve(); runtime=Path(a.runtime).expanduser().resolve() if a.runtime else None
    paths=prepare_migration(root,workspace); report=build_stage(paths,TEMPLATE,runtime_root=runtime,package_root=HERE,profile=a.profile); vr=verify_stage(paths)
    result={'migration_id':paths.migration_id,'workspace':str(paths.workspace),'stage':str(paths.stage),'backup':str(paths.backup),'verification':{'ok':vr.ok,'errors':vr.errors,'warnings':vr.warnings},'report':report}
    if not vr.ok:pjson(result);return 2
    if a.activate:
        meta=activate_verified_stage(paths,allow_pending_semantic_review=a.skip_semantic_review); result['activation']=meta
        try: result['reindex']=reindex(root)
        except Exception as ex: result['reindex']={'ok':False,'error':str(ex)}
        hr=health_root(root); result['post_activation_health']={'ok':hr.ok,'errors':hr.errors,'warnings':hr.warnings}
        if not hr.ok:pjson(result);return 3
    pjson(result);return 0

def cmd_verify(a):
    root=Path(a.root).expanduser().resolve() if a.root else Path.home()/'.claude'; vr=verify_stage(paths_for_workspace(Path(a.workspace),root));pjson({'ok':vr.ok,'errors':vr.errors,'warnings':vr.warnings});return 0 if vr.ok else 2

def cmd_health(a):
    vr=health_root(Path(a.root).expanduser().resolve());pjson({'ok':vr.ok,'errors':vr.errors,'warnings':vr.warnings});return 0 if vr.ok else 2

def cmd_doctor(a):r=doctor(Path(a.root).expanduser().resolve());pjson(r);return 0 if r['ok'] else 2
def cmd_reindex(a):pjson(reindex(Path(a.root).expanduser().resolve()));return 0
def cmd_snapshot(a):pjson(snapshot(Path(a.root).expanduser().resolve(),Path(a.destination).expanduser().resolve() if a.destination else None));return 0
def cmd_maintain(a):r=maintain(Path(a.root).expanduser().resolve(),not a.no_repair);pjson(r);return 0 if r['after']['ok'] else 2

def cmd_mark_reviewed(a):pjson(mark_semantic_review(paths_for_workspace(Path(a.workspace),Path(a.root).expanduser().resolve()),a.reviewer,a.notes or ''));return 0
def cmd_activate(a):
    root=Path(a.root).expanduser().resolve(); paths=paths_for_workspace(Path(a.workspace),root);vr=verify_stage(paths)
    if not vr.ok:pjson({'ok':False,'errors':vr.errors});return 2
    meta=activate_verified_stage(paths,a.skip_semantic_review); idx=reindex(root); hr=health_root(root);pjson({'ok':hr.ok,'activation':meta,'reindex':idx,'health_errors':hr.errors});return 0 if hr.ok else 3

def cmd_rollback(a):pjson(rollback(Path(a.root).expanduser().resolve(),Path(a.rollback_root).expanduser().resolve()));return 0

def topology_from_args(a):
    return detect_shared_nas(
        Path(a.root), a.primary_machine, tuple(a.secondary_machine or []),
        Path(a.facade), getattr(a,'runtime_template','~/Library/Application Support/ClaudeContextOS/home'),
    )

def shared_migration_from_args(a):
    topology=topology_from_args(a); mig=Path(a.workspace).expanduser().resolve()
    required=(mig/'stage',mig/'backup',mig/'topology-guard.json')
    if not all(path.exists() for path in required):
        raise RuntimeError('shared commands require the exact migration workspace returned by adopt-shared')
    source=topology.logical_root
    paths=MigrationPaths(mig.name,source,mig,mig/'backup',mig/'stage',source.parent/f'claude-pre-context-os-{mig.name}')
    return SharedMigration(topology,paths,mig/'topology-guard.json',mig/'primary-enrollment-plan.json')

def cmd_adopt_shared(a):
    topology=topology_from_args(a); migration=prepare_shared_migration(topology,Path(a.workspace));report=build_shared_stage(migration,TEMPLATE,HERE);vr=verify_shared_stage(migration)
    pjson({'migration_id':migration.paths.migration_id,'workspace':str(migration.paths.workspace),'stage':str(migration.paths.stage),'backup':str(migration.paths.backup),'verification':{'ok':vr.ok,'errors':vr.errors,'warnings':vr.warnings},'report':report,'enrollment_plan':str(migration.enrollment_plan)})
    return 0 if vr.ok else 2

def cmd_verify_shared(a):
    migration=shared_migration_from_args(a);vr=verify_shared_stage(migration,a.require_source_unchanged);pjson({'ok':vr.ok,'errors':vr.errors,'warnings':vr.warnings});return 0 if vr.ok else 2

def cmd_probe_shared_rollback(a):pjson(probe_shared_rollback(shared_migration_from_args(a)));return 0
def cmd_activate_shared(a):pjson(activate_shared(shared_migration_from_args(a)));return 0
def cmd_rollback_shared(a):
    mig=Path(a.workspace).expanduser().resolve();guard_path=mig/'topology-guard.json'
    if not (mig/'backup').exists() or not guard_path.exists():
        raise RuntimeError('shared commands require the exact migration workspace returned by adopt-shared')
    guard=json.loads(guard_path.read_text(encoding='utf-8'))
    container=Path(a.root).expanduser().resolve()
    if Path(guard.get('container_root','')).resolve()!=container:
        raise RuntimeError('rollback root does not match the staged topology guard')
    source=Path(guard['logical_root']).resolve();paths=MigrationPaths(mig.name,source,mig,mig/'backup',mig/'stage',source.parent/f'claude-pre-context-os-{mig.name}')
    result=rollback(source,paths.rollback_root)
    frozen=json.loads((mig/'source-manifest.json').read_text(encoding='utf-8'))
    if inventory_tree(source)!=frozen:raise RuntimeError('restored shared root does not match frozen source manifest')
    pjson({'ok':True,**result});return 0

def cmd_enroll_machine(a):
    topology=topology_from_args(a);runtime=Path(a.runtime) if a.runtime else None;plan=plan_machine_enrollment(topology,a.machine_id,Path(a.facade),Path(a.workspace),runtime)
    if not a.apply:pjson(plan);return 0 if plan['status']=='ready' else 2
    result=apply_machine_enrollment(plan);result['verification']=verify_machine_enrollment(Path(result['manifest']));pjson(result);return 0 if result['verification']['ok'] else 3

def cmd_rollback_machine(a):pjson(rollback_machine_enrollment(Path(a.manifest)));return 0

def cmd_bootstrap(a):
    project=Path(a.project).expanduser().resolve();project.mkdir(parents=True,exist_ok=True)
    if not PROJECT_TEMPLATE.exists():raise RuntimeError('project template unavailable in installed runtime; use deployable package')
    for src in PROJECT_TEMPLATE.rglob('*'):
        rel=src.relative_to(PROJECT_TEMPLATE);dst=project/rel
        if src.is_dir():dst.mkdir(parents=True,exist_ok=True)
        elif not dst.exists() or a.force:dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    pjson({'ok':True,'project':str(project)});return 0

def cmd_register_project(a):
    root=Path(a.root).expanduser().resolve();project=Path(a.project).expanduser().resolve();mp=project/'.claude'/'project.json'
    if not mp.exists():raise FileNotFoundError(mp)
    m=json.loads(mp.read_text(encoding='utf-8'));pjson(register_project(root,m,str(project)));return 0

def cmd_find_project(a):pjson({'results':find_projects(Path(a.root).expanduser().resolve(),a.query)});return 0

def cmd_project_resource(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);ProjectRegistry(root,db).add_resource(a.project_id,a.type,a.value,a.relation);db.close();pjson({'ok':True});return 0

def cmd_dependency(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);ProjectRegistry(root,db).add_dependency(a.source,a.target,a.relation);db.close();pjson({'ok':True});return 0

def cmd_impact(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);out=ProjectRegistry(root,db).impact(a.resource);db.close();pjson(out);return 0

def cmd_brain(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);out=ProjectBrain(root,db).compile(a.project_id);db.close();pjson(out or {});return 0

def cmd_search_knowledge(a):pjson({'results':search_knowledge(Path(a.root).expanduser().resolve(),a.query,a.project_id,a.domain)});return 0

def cmd_add_knowledge(a):pjson({'ok':True,'path':str(add_knowledge(Path(a.root).expanduser().resolve(),json.loads(Path(a.file).read_text(encoding='utf-8'))))});return 0

def cmd_supersede(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);KnowledgeStore(root,db).supersede(a.old_id,a.new_id);db.close();pjson({'ok':True,'superseded':a.old_id,'by':a.new_id});return 0

def cmd_task_create(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);row=TaskLedger(root,db).create(a.project_id,a.title,a.constraint or []);db.close();pjson(row);return 0

def cmd_task_update(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);row=TaskLedger(root,db).update(a.task_id,a.status,a.note);db.close();pjson(row);return 0

def cmd_task_list(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);rows=TaskLedger(root,db).list(a.project_id,a.status,a.limit);db.close();pjson({'tasks':rows});return 0

def cmd_compile(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);pack=ContextCompiler(root,db).compile(a.project_id,a.query,a.max_chars);db.close(); print(pack['rendered'] if not a.json else json.dumps(pack,indent=2));return 0

def _ea_context(root:Path,cwd:Path,query:str):
    db=_db(root)
    try: ingest_hook_events(root,db)
    except Exception: pass
    pid=current_project(db,cwd);ea=ExecutiveAssistant(root,db); comp=ContextCompiler(root,db).compile(pid,query,max_chars=7000) if pid else {'rendered':'No registered current project.','knowledge':[],'tasks':[]}
    recent=[dict(r) for r in db.conn.execute('SELECT event_type,created_at,payload_json FROM events ORDER BY created_at DESC LIMIT 12')]
    for r in recent:
        try:r['payload']=json.loads(r.pop('payload_json'))
        except Exception:r['payload']={}
    out={'assistant':ea.status(),'personality':load_config(root/'context-os'/'config'/'context-os.json').get('assistant',{}),'machine':current_machine_profile(),'current_project_id':pid,'compiled_context':comp['rendered'],'preferences':ea.preferences()[:10],'recent_events':recent};db.close();return out

def cmd_assistant_context(a):pjson(_ea_context(Path(a.root).expanduser().resolve(),Path(a.cwd).expanduser().resolve(),a.query or 'current project'));return 0

def cmd_assistant_brief(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);pid=a.project_id or current_project(db,Path(a.cwd).expanduser().resolve());ea=ExecutiveAssistant(root,db);print(ea.brief(pid));db.close();return 0

def cmd_assistant_investigate(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);pid=a.project_id or current_project(db,Path(a.cwd).expanduser().resolve());ea=ExecutiveAssistant(root,db);print(ea.investigate(a.query,pid));db.close();return 0

def cmd_assistant_remember(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);row=ExecutiveAssistant(root,db).remember_preference(a.text,a.confirmed);db.close();pjson(row);return 0

def cmd_assistant(a):
    root=Path(a.root).expanduser().resolve();db=_db(root);ea=ExecutiveAssistant(root,db);print(f'◆ {ea.name}\nLocal Executive Assistant. Commands: brief, find <text>, status, quit.')
    while True:
        try:q=input('EA › ').strip()
        except EOFError:break
        if q.lower() in {'quit','exit','/return'}:break
        if q.lower()=='brief':print(ea.brief())
        elif q.lower()=='status':pjson(ea.status())
        elif q.lower().startswith('find '):print(ea.investigate(q[5:]))
        else:print('◆ EA\n\nUse Claude Code /ea for personality-driven reasoning. This terminal shell exposes deterministic local OS queries only.')
    db.close();return 0

def cmd_storage_validate(a):
    root=Path(a.root).expanduser().resolve(); parent=root.parent; result={'root':str(root),'exists':root.exists(),'readable':os.access(root,os.R_OK) if root.exists() else False,'writable':os.access(root,os.W_OK) if root.exists() else False,'probe':None}
    if root.exists() and result['writable']:
        probe=parent/f'.context-os-probe-{uuid.uuid4().hex[:8]}'; renamed=parent/f'{probe.name}-renamed'
        try:
            probe.mkdir();(probe/'probe.txt').write_text('context-os-storage-probe',encoding='utf-8');probe.rename(renamed);txt=(renamed/'probe.txt').read_text(encoding='utf-8');result['probe']={'create':True,'rename':True,'readback':txt=='context-os-storage-probe'}
        finally:
            shutil.rmtree(probe,ignore_errors=True);shutil.rmtree(renamed,ignore_errors=True)
    result['ok']=bool(result['exists'] and result['readable'] and (result['probe'] or {}).get('readback'));pjson(result);return 0 if result['ok'] else 2

def cmd_service_plist(a):
    root=Path(a.root).expanduser().resolve();runtime=runtime_for(root);src=root/'context-os'/'runtime'/'launchd'/'com.contextos.v3.maintain.plist.template';text=src.read_text().replace('__CONTEXT_OS_HOME__',str(root/'context-os')).replace('__CLAUDE_ROOT__',str(root)).replace('__RUNTIME_ROOT__',str(runtime));out=Path(a.output).expanduser() if a.output else Path.home()/'Library'/'LaunchAgents'/'com.contextos.v3.maintain.plist';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(text);pjson({'ok':True,'plist':str(out),'loaded':False,'note':'Generated only; load with launchctl when you are ready.'});return 0

def cmd_conflicts(a):
    root=Path(a.root).expanduser().resolve(); db=_db(root); rows=KnowledgeStore(root,db).conflicts(a.limit); db.close(); pjson({'conflicts':rows,'count':len(rows)}); return 0

def cmd_local_only_audit(a):
    package=Path(a.package).expanduser().resolve() if a.package else HERE
    r=audit_runtime_code(package); pjson(r); return 0 if r['ok'] else 2

def cmd_tool_status(a): pjson(tool_status()); return 0

def cmd_export_portable(a):
    import zipfile, hashlib
    src=HERE
    required=['context_os','contextctl.py','template_root','project_template']
    if not all((src/x).exists() for x in required): raise RuntimeError('portable export requires a complete installed/deployable runtime app')
    out=Path(a.output).expanduser().resolve(); out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name in required+['docs','README.md','ADOPTION_PROTOCOL.md','EXECUTIVE_ASSISTANT.md','PORTABLE_DEPLOYMENT.md']:
            p=src/name
            if not p.exists(): continue
            files=[p] if p.is_file() else [x for x in p.rglob('*') if x.is_file() and '__pycache__' not in x.parts]
            for f in files: z.write(f,Path('claude-context-os-v3')/f.relative_to(src))
    h=hashlib.sha256(out.read_bytes()).hexdigest(); pjson({'ok':True,'archive':str(out),'sha256':h,'contains_personal_knowledge':False}); return 0

def main():
    ap=argparse.ArgumentParser(description='Context OS V3 control utility - local only');sp=ap.add_subparsers(dest='command',required=True)
    p=sp.add_parser('inventory');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_inventory)
    p=sp.add_parser('adopt');p.add_argument('--root',default='~/.claude');p.add_argument('--workspace',default='~/.context-os-migrations');p.add_argument('--runtime');p.add_argument('--profile',default='default');p.add_argument('--activate',action='store_true');p.add_argument('--skip-semantic-review',action='store_true');p.set_defaults(func=cmd_adopt)
    p=sp.add_parser('verify');p.add_argument('--workspace',required=True);p.add_argument('--root');p.set_defaults(func=cmd_verify)
    p=sp.add_parser('health');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_health)
    p=sp.add_parser('doctor');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_doctor)
    p=sp.add_parser('reindex');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_reindex)
    p=sp.add_parser('snapshot');p.add_argument('--root',default='~/.claude');p.add_argument('--destination');p.set_defaults(func=cmd_snapshot)
    p=sp.add_parser('maintain');p.add_argument('--root',default='~/.claude');p.add_argument('--no-repair',action='store_true');p.set_defaults(func=cmd_maintain)
    p=sp.add_parser('mark-reviewed');p.add_argument('--workspace',required=True);p.add_argument('--root',default='~/.claude');p.add_argument('--reviewer',default='claude-code');p.add_argument('--notes');p.set_defaults(func=cmd_mark_reviewed)
    p=sp.add_parser('activate');p.add_argument('--workspace',required=True);p.add_argument('--root',default='~/.claude');p.add_argument('--skip-semantic-review',action='store_true');p.set_defaults(func=cmd_activate)
    p=sp.add_parser('rollback');p.add_argument('--root',default='~/.claude');p.add_argument('--rollback-root',required=True);p.set_defaults(func=cmd_rollback)
    def add_topology_args(p,workspace=True):
        p.add_argument('--root',required=True);p.add_argument('--primary-machine',required=True);p.add_argument('--secondary-machine',action='append',default=[]);p.add_argument('--facade',required=True);p.add_argument('--runtime-template',default='~/Library/Application Support/ClaudeContextOS/home')
        if workspace:p.add_argument('--workspace',required=True)
    p=sp.add_parser('adopt-shared');add_topology_args(p);p.set_defaults(func=cmd_adopt_shared)
    p=sp.add_parser('verify-shared');add_topology_args(p);p.add_argument('--require-source-unchanged',action='store_true');p.set_defaults(func=cmd_verify_shared)
    p=sp.add_parser('probe-shared-rollback');add_topology_args(p);p.set_defaults(func=cmd_probe_shared_rollback)
    p=sp.add_parser('activate-shared');add_topology_args(p);p.set_defaults(func=cmd_activate_shared)
    p=sp.add_parser('rollback-shared');add_topology_args(p);p.set_defaults(func=cmd_rollback_shared)
    p=sp.add_parser('enroll-machine');add_topology_args(p);p.add_argument('--machine-id',required=True);p.add_argument('--runtime');p.add_argument('--apply',action='store_true');p.set_defaults(func=cmd_enroll_machine)
    p=sp.add_parser('rollback-machine');p.add_argument('--manifest',required=True);p.set_defaults(func=cmd_rollback_machine)
    p=sp.add_parser('bootstrap-project');p.add_argument('--project',default='.');p.add_argument('--force',action='store_true');p.set_defaults(func=cmd_bootstrap)
    p=sp.add_parser('register-project');p.add_argument('--project',default='.');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_register_project)
    p=sp.add_parser('find-project');p.add_argument('query');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_find_project)
    p=sp.add_parser('project-resource');p.add_argument('project_id');p.add_argument('type');p.add_argument('value');p.add_argument('--relation',default='uses');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_project_resource)
    p=sp.add_parser('dependency');p.add_argument('source');p.add_argument('target');p.add_argument('--relation',default='depends_on');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_dependency)
    p=sp.add_parser('impact');p.add_argument('resource');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_impact)
    p=sp.add_parser('brain');p.add_argument('project_id');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_brain)
    p=sp.add_parser('search-knowledge');p.add_argument('query');p.add_argument('--root',default='~/.claude');p.add_argument('--project-id');p.add_argument('--domain');p.set_defaults(func=cmd_search_knowledge)
    p=sp.add_parser('add-knowledge');p.add_argument('--file',required=True);p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_add_knowledge)
    p=sp.add_parser('supersede-knowledge');p.add_argument('old_id');p.add_argument('new_id');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_supersede)
    p=sp.add_parser('task-create');p.add_argument('project_id');p.add_argument('title');p.add_argument('--constraint',action='append');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_task_create)
    p=sp.add_parser('task-update');p.add_argument('task_id');p.add_argument('--status');p.add_argument('--note');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_task_update)
    p=sp.add_parser('task-list');p.add_argument('--project-id');p.add_argument('--status');p.add_argument('--limit',type=int,default=25);p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_task_list)
    p=sp.add_parser('compile');p.add_argument('project_id');p.add_argument('query');p.add_argument('--max-chars',type=int,default=9000);p.add_argument('--json',action='store_true');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_compile)
    p=sp.add_parser('assistant-context');p.add_argument('--query',default='current project');p.add_argument('--cwd',default='.');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_assistant_context)
    p=sp.add_parser('assistant-brief');p.add_argument('--project-id');p.add_argument('--cwd',default='.');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_assistant_brief)
    p=sp.add_parser('assistant-investigate');p.add_argument('query');p.add_argument('--project-id');p.add_argument('--cwd',default='.');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_assistant_investigate)
    p=sp.add_parser('assistant-remember');p.add_argument('text');p.add_argument('--confirmed',action='store_true');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_assistant_remember)
    p=sp.add_parser('assistant');p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_assistant)
    p=sp.add_parser('storage-validate');p.add_argument('--root',required=True);p.set_defaults(func=cmd_storage_validate)
    p=sp.add_parser('service-plist');p.add_argument('--root',default='~/.claude');p.add_argument('--output');p.set_defaults(func=cmd_service_plist)
    p=sp.add_parser('conflicts');p.add_argument('--limit',type=int,default=50);p.add_argument('--root',default='~/.claude');p.set_defaults(func=cmd_conflicts)
    p=sp.add_parser('local-only-audit');p.add_argument('--package');p.set_defaults(func=cmd_local_only_audit)
    p=sp.add_parser('tool-status');p.set_defaults(func=cmd_tool_status)
    p=sp.add_parser('export-portable');p.add_argument('--output',required=True);p.set_defaults(func=cmd_export_portable)
    a=ap.parse_args()
    try:return a.func(a)
    except Exception as e:print(json.dumps({'ok':False,'error':str(e)},indent=2),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
