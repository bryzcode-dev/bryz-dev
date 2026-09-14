from __future__ import annotations
import json, os, shutil, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from .classify import classify_section, looks_secret, split_markdown_sections
from .inventory import inventory_tree
from .settings import merge_context_os_settings, apply_security_permissions
from .config import resolve_paths, save_config, detect_storage_kind
from .integrity import build_manifest
from .util import write_json
from .secrets import scan_tree

KNOWN_NATIVE_DIRS={'projects','skills','rules','agents','commands','hooks','plugins'}
KNOWN_NATIVE_FILES={'settings.json','settings.local.json'}
MANAGED_SKILL_NAMES={'executive-assistant','context-memory','context-health','project-bootstrap','gas-engineering','sql-engineering','root-cause-debugging','context-adopt'}

@dataclass
class MigrationPaths:
    migration_id:str; source:Path; workspace:Path; backup:Path; stage:Path; rollback_root:Path

def _copy_item(src:Path,dst:Path):
    dst.parent.mkdir(parents=True,exist_ok=True)
    if src.is_symlink(): dst.symlink_to(src.readlink())
    elif src.is_dir(): shutil.copytree(src,dst,symlinks=True,dirs_exist_ok=True)
    else: shutil.copy2(src,dst)

def _snapshot_fingerprints(rows:list[dict])->dict[str,tuple]:
    out={}
    for r in rows:
        t=r.get('type')
        if t=='file': out[r['path']]=('file',r.get('sha256'))
        elif t=='symlink': out[r['path']]=('symlink',r.get('target'))
        elif t=='dir': out[r['path']]=('dir',)
        else: out[r['path']]=(t,r.get('size'))
    return out

def _changed_paths(a:list[dict],b:list[dict])->list[str]:
    af=_snapshot_fingerprints(a); bf=_snapshot_fingerprints(b)
    return sorted(k for k in set(af)|set(bf) if af.get(k)!=bf.get(k))

def _copy_snapshot_tree(source:Path,backup:Path,rows:list[dict]):
    backup.mkdir(parents=True)
    for row in rows:
        src=source/row['path']; dst=backup/row['path']; kind=row['type']
        if kind=='dir':
            dst.mkdir(parents=True,exist_ok=True)
        elif kind=='symlink':
            dst.parent.mkdir(parents=True,exist_ok=True)
            dst.symlink_to(row['target'])
        elif kind=='file':
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,dst)
        else:
            raise OSError(f'Unsupported source item during snapshot: {row["path"]} ({kind})')

def prepare_migration(source_root:Path,workspace:Path)->MigrationPaths:
    source=Path(source_root).expanduser().resolve(); work=Path(workspace).expanduser().resolve(); work.mkdir(parents=True,exist_ok=True)
    mid=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    mig=work/mid; backup=mig/'backup'; stage=mig/'stage'; rollback=source.parent/f'claude-pre-context-os-{mid}'
    mig.mkdir(parents=True,exist_ok=True)
    snapshot=[]; backup_inv=[]; drift=[]; attempts=[]
    if source.exists():
        for attempt in range(1,4):
            if backup.exists(): shutil.rmtree(backup)
            try:
                pre=inventory_tree(source)
                _copy_snapshot_tree(source,backup,pre)
                bkp=inventory_tree(backup)
                post=inventory_tree(source)
            except OSError as ex:
                attempts.append({'attempt':attempt,'matched_boundary':None,'changed_paths':[],'backup_vs_pre':[],'backup_vs_post':[],'copy_error':str(ex)})
                continue
            pre_fp=_snapshot_fingerprints(pre); post_fp=_snapshot_fingerprints(post); bkp_fp=_snapshot_fingerprints(bkp)
            matched=None
            if bkp_fp==pre_fp:
                matched='pre-copy'; snapshot=pre
            elif bkp_fp==post_fp:
                matched='post-copy'; snapshot=post
            changed=_changed_paths(pre,post)
            attempts.append({'attempt':attempt,'matched_boundary':matched,'changed_paths':changed,'backup_vs_pre':_changed_paths(pre,bkp),'backup_vs_post':_changed_paths(post,bkp)})
            if matched:
                backup_inv=bkp; drift=changed; break
        else:
            write_json(mig/'backup-verification.json',{'ok':False,'attempts':attempts,'message':'Source changed while backup was being copied; no complete boundary snapshot could be verified.'})
            last=attempts[-1] if attempts else {}
            sample=(last.get('backup_vs_pre') or last.get('backup_vs_post') or [])[:12]
            detail=', '.join(sample) if sample else last.get('copy_error','unknown paths')
            raise RuntimeError(f'Backup snapshot could not stabilize after 3 attempts. Changing paths: {detail}. Close Claude Code and retry, or inspect {mig / "backup-verification.json"}')
    else:
        backup.mkdir(parents=True); snapshot=[]; backup_inv=[]
    stage.mkdir(parents=True)
    write_json(mig/'source-manifest.json',snapshot); write_json(mig/'backup-manifest.json',backup_inv)
    write_json(mig/'backup-verification.json',{'ok':True,'matched_boundary':attempts[-1]['matched_boundary'] if attempts else 'empty-source','attempts':attempts,'live_drift_paths':drift})
    if drift: write_json(mig/'live-drift.json',{'changed_paths':drift,'note':'Source changed after/before the verified snapshot boundary. The backup itself matches a complete verified source boundary state.'})
    write_json(mig/'migration-paths.json',{'migration_id':mid,'source':str(source),'workspace':str(mig),'backup':str(backup),'stage':str(stage),'rollback_root':str(rollback)})
    return MigrationPaths(mid,source,mig,backup,stage,rollback)

def _preserve_native_dir(src:Path,stage:Path,name:str,report:dict):
    if not src.exists(): return
    dest_root=stage/name; dest_root.mkdir(parents=True,exist_ok=True)
    collisions=[]
    for child in src.iterdir():
        dst=dest_root/child.name
        if dst.exists():
            dest=stage/'context-os'/'legacy-preserved'/'native-collisions'/name/child.name
            _copy_item(child,dest); collisions.append(child.name)
        else:
            _copy_item(child,dst)
    report['mappings'].append({'source':name,'destination':name,'mode':'namespace-safe-preserve','collisions_preserved':collisions})

def build_stage(paths:MigrationPaths,template_root:Path,runtime_root:Path|None=None,package_root:Path|None=None,profile='default')->dict:
    template_root=Path(template_root).resolve();
    if package_root is None:
        candidate=Path(__file__).resolve().parents[1]
        if (candidate/'contextctl.py').exists(): package_root=candidate
    shutil.copytree(template_root,paths.stage,dirs_exist_ok=True,symlinks=True)
    review=paths.stage/'context-os'/'migration'/'review'; preserved=paths.stage/'context-os'/'legacy-preserved'; review.mkdir(parents=True,exist_ok=True); preserved.mkdir(parents=True,exist_ok=True)
    report={'migration_id':paths.migration_id,'version':'3.0.1','claude_sections':[],'mappings':[],'secrets':[],'storage_kind':detect_storage_kind(paths.source)}
    # Install self-contained runtime app under managed namespace.
    if package_root:
        package_root=Path(package_root)
        app=paths.stage/'context-os'/'runtime'/'app'; app.mkdir(parents=True,exist_ok=True)
        _copy_item(package_root/'context_os',app/'context_os'); shutil.copy2(package_root/'contextctl.py',app/'contextctl.py')
        for name in ['template_root','project_template','docs']:
            src=package_root/name
            if src.exists(): _copy_item(src,app/name)
        for name in ['README.md','ADOPTION_PROTOCOL.md','EXECUTIVE_ASSISTANT.md','PORTABLE_DEPLOYMENT.md']:
            src=package_root/name
            if src.exists(): shutil.copy2(src,app/name)
    final_runtime=Path(runtime_root).expanduser().resolve() if runtime_root else Path.home()/'Library'/'Application Support'/'ClaudeContextOS'/profile
    cfg={'version':'3.0.1','profile':profile,'paths':{'claude_root':str(paths.source),'runtime_root':str(final_runtime),'storage_kind':detect_storage_kind(paths.source)},'assistant':{'name':'Avery','personality':{'warmth':7,'humor':5,'directness':8,'verbosity':5,'technical_depth':'adaptive'}},'network':{'runtime_web_dependencies':False}}
    save_config(paths.stage/'context-os'/'config'/'context-os.json',cfg); (paths.stage/'context-os'/'VERSION').write_text('3.0.1\n',encoding='utf-8')
    if paths.source.exists():
        for name in KNOWN_NATIVE_DIRS:
            _preserve_native_dir(paths.source/name,paths.stage,name,report)
        existing={}; ssrc=paths.source/'settings.json'
        if ssrc.exists():
            try: existing=json.loads(ssrc.read_text(encoding='utf-8'))
            except Exception: _copy_item(ssrc,review/'settings.json.unparsed'); report['mappings'].append({'source':'settings.json','destination':'context-os/migration/review/settings.json.unparsed','mode':'review'})
        hook_base=paths.source/'context-os'/'runtime'/'hooks'
        hp={k:str(hook_base/f'{fn}.py') for k,fn in {'session_start':'session_start','pre_tool_guard':'pre_tool_guard','post_tool_log':'post_tool_log','pre_compact':'pre_compact','post_compact':'post_compact','session_end':'session_end'}.items()}
        merged=apply_security_permissions(merge_context_os_settings(existing,hp,str(paths.source/'context-os')),str(paths.source/'context-os'))
        write_json(paths.stage/'settings.json',merged)
        if ssrc.exists() and not any(m['source']=='settings.json' for m in report['mappings']): report['mappings'].append({'source':'settings.json','destination':'settings.json','mode':'merged'})
        legacy=paths.source/'CLAUDE.md'
        if legacy.exists():
            text=legacy.read_text(encoding='utf-8',errors='replace')
            for i,s in enumerate(split_markdown_sections(text),1): report['claude_sections'].append({**s,**classify_section(s['title'],s['body']),'source':'CLAUDE.md','section_id':f'legacy-claude-{i:03d}'})
            (review/'legacy-CLAUDE.md').write_text(text,encoding='utf-8'); write_json(review/'claude-sections.json',report['claude_sections']); report['mappings'].append({'source':'CLAUDE.md','destination':'context-os/migration/review/legacy-CLAUDE.md','mode':'semantic-review'})
        findings=scan_tree(paths.source)
        report['secrets']=findings; write_json(review/'secret-scan.json',{'findings':findings,'note':'Local heuristic scan. Sensitive files are excluded from knowledge indexing, not deleted.'})
        for src in sorted(paths.source.iterdir()):
            name=src.name
            if name in KNOWN_NATIVE_DIRS or name in KNOWN_NATIVE_FILES or name=='CLAUDE.md': continue
            if src.is_file() and not src.is_symlink():
                text=None
                try:
                    if src.stat().st_size<=2_000_000:text=src.read_text(encoding='utf-8')
                except Exception:pass
                if looks_secret(Path(name),text):
                    ref={'source':name,'reason':'likely-secret','copied_to_knowledge':False}; write_json(review/f'{name}.secret-ref.json',ref); report['mappings'].append({'source':name,'destination':f'context-os/migration/review/{name}.secret-ref.json','mode':'secret-reference'}); continue
            _copy_item(src,preserved/name); report['mappings'].append({'source':name,'destination':f'context-os/legacy-preserved/{name}','mode':'legacy-preserve'})
    else:
        hook_base=paths.source/'context-os'/'runtime'/'hooks'; hp={k:str(hook_base/f'{fn}.py') for k,fn in {'session_start':'session_start','pre_tool_guard':'pre_tool_guard','post_tool_log':'post_tool_log','pre_compact':'pre_compact','post_compact':'post_compact','session_end':'session_end'}.items()}; write_json(paths.stage/'settings.json',apply_security_permissions(merge_context_os_settings({},hp,str(paths.source/'context-os')),str(paths.source/'context-os')))
    write_json(paths.stage/'context-os'/'migration'/'migration-report.json',report)
    write_json(paths.stage/'context-os'/'migration'/'semantic-review.json',{'status':'pending' if report['claude_sections'] else 'not_required','migration_id':paths.migration_id,'reviewer':None})
    (paths.stage/'context-os'/'migration'/'ADOPTION_BRIEF.md').write_text('# Semantic Adoption Brief\n\nUse the context-adopt skill against this staged root only. Do not discard uncertain legacy content.\n',encoding='utf-8')
    regenerate_managed_manifest(paths.stage,template_root)
    return report

def semantic_review_complete(paths):
    try:return json.loads((paths.stage/'context-os'/'migration'/'semantic-review.json').read_text())['status'] in {'complete','not_required'}
    except Exception:return False

def mark_semantic_review(paths,reviewer,notes=''):
    p=paths.stage/'context-os'/'migration'/'semantic-review.json'; d=json.loads(p.read_text()); d.update({'status':'complete','reviewer':reviewer,'notes':notes,'completed_at':datetime.now(timezone.utc).isoformat()}); write_json(p,d); return d

def regenerate_managed_manifest(stage:Path,template_root:Path)->dict:
    managed=[]
    for p in Path(template_root).rglob('*'):
        if not p.is_file(): continue
        rel=p.relative_to(template_root)
        rels=str(rel)
        if rels.startswith('context-os/config/') or rels.startswith('context-os/assistant/') or rels.startswith('context-os/knowledge/') or rels.startswith('context-os/registry/') or rels.startswith('context-os/events/') or rels.startswith('context-os/backups/') or rels.startswith('context-os/logs/'):
            continue
        managed.append(rel)
    app_root=Path(stage)/'context-os'/'runtime'/'app'
    if app_root.exists():
        managed.extend(p.relative_to(stage) for p in app_root.rglob('*') if p.is_file())
    manifest=build_manifest(Path(stage),managed)
    write_json(Path(stage)/'context-os'/'integrity'/'managed-manifest.json',manifest)
    return manifest

def activate_verified_stage(paths,allow_pending_semantic_review=False):
    if not allow_pending_semantic_review and not semantic_review_complete(paths): raise RuntimeError('Semantic adoption review is still pending')
    if paths.rollback_root.exists(): raise FileExistsError(paths.rollback_root)
    lock=paths.workspace/'activation.lock'
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        raise RuntimeError(f'activation already in progress: {lock}')
    with os.fdopen(fd,'w',encoding='utf-8') as f:
        json.dump({'pid':os.getpid(),'migration_id':paths.migration_id,'started_at':datetime.now(timezone.utc).isoformat()},f)
    try:
        old=paths.source.exists(); prepared=paths.source.parent/f'.context-os-stage-{paths.migration_id}'
        if prepared.exists():
            abandoned=paths.source.parent/f'.context-os-abandoned-stage-{paths.migration_id}-{uuid.uuid4().hex[:8]}'
            prepared.rename(abandoned)
        # Copy the stage onto the destination filesystem first. This avoids cross-device rename failures for NAS roots.
        expected=inventory_tree(paths.stage)
        shutil.copytree(paths.stage,prepared,symlinks=True)
        actual=inventory_tree(prepared)
        changed=_changed_paths(expected,actual)
        if changed:
            raise RuntimeError('prepared stage verification failed: '+', '.join(changed[:12]))
        if old: paths.source.rename(paths.rollback_root)
        try: prepared.rename(paths.source)
        except Exception:
            if old and paths.rollback_root.exists() and not paths.source.exists(): paths.rollback_root.rename(paths.source)
            raise
        meta={'migration_id':paths.migration_id,'activated_at':datetime.now(timezone.utc).isoformat(),'rollback_root':str(paths.rollback_root),'backup_root':str(paths.backup),'workspace':str(paths.workspace),'storage_kind':detect_storage_kind(paths.source)}
        write_json(paths.source/'context-os'/'migration'/'ACTIVE_MIGRATION.json',meta); return meta
    finally:
        lock.unlink(missing_ok=True)
