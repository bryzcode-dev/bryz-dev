from __future__ import annotations
import copy

MARKER='context-os-v3-managed'
HOOK_FILES={
    'session_start':'session_start',
    'pre_tool_guard':'pre_tool_guard',
    'post_tool_log':'post_tool_log',
    'pre_compact':'pre_compact',
    'post_compact':'post_compact',
    'session_end':'session_end',
}

def _hook(command, matcher=None):
    run=f'python3 "{command}"'
    if '$HOME/' in command:
        run=f'test ! -f "{command}" || {run}'
    entry={'hooks':[{'type':'command','command':run,'statusMessage':MARKER}]}
    if matcher: entry['matcher']=matcher
    return entry

def merge_context_os_settings(existing:dict, hook_paths:dict, context_home:str|None=None)->dict:
    out=copy.deepcopy(existing or {})
    hooks=out.setdefault('hooks',{})
    desired={}
    mapping=[('SessionStart','session_start',None),('PreToolUse','pre_tool_guard','Bash|Write|Edit'),('PostToolUse','post_tool_log',None),('PreCompact','pre_compact',None),('PostCompact','post_compact',None),('SessionEnd','session_end',None)]
    for event,key,matcher in mapping:
        if key in hook_paths: desired[event]=_hook(hook_paths[key],matcher)
    for event,entry in desired.items():
        items=hooks.setdefault(event,[]); cleaned=[]
        for item in items:
            hs=item.get('hooks',[]) if isinstance(item,dict) else []
            if any(isinstance(h,dict) and h.get('statusMessage')==MARKER for h in hs):continue
            cleaned.append(item)
        cleaned.append(entry);hooks[event]=cleaned
    if context_home:
        out.setdefault('env',{})['CONTEXT_OS_HOME']=context_home
    return out

def portable_hook_paths(context_home='$HOME/.claude/context-os'):
    base=context_home.rstrip('/')+'/runtime/hooks'
    return {key:f'{base}/{name}.py' for key,name in HOOK_FILES.items()}

def apply_security_permissions(settings:dict,context_home:str|None=None)->dict:
    out=copy.deepcopy(settings or {});perms=out.setdefault('permissions',{});deny=perms.setdefault('deny',[])
    for rule in ['Read(./.env)','Read(./.env.*)','Read(**/.env)','Read(**/.env.*)','Read(**/*credentials*)','Read(**/*private_key*)']:
        if rule not in deny:deny.append(rule)
    if context_home:
        allow=perms.setdefault('allow',[])
        portable_home=('~/'+context_home[len('$HOME/'):]) if context_home.startswith('$HOME/') else None
        executable=(f'{portable_home}/runtime/app/contextctl.py' if portable_home
                    else f'"{context_home}/runtime/app/contextctl.py"')
        base=f'python3 {executable}'
        for cmd in ['assistant-context *','assistant-brief *','assistant-investigate *','find-project *','impact *','brain *','task-list *','doctor *']:
            rule=f'Bash({base} {cmd})'
            if rule not in allow:allow.append(rule)
    return out
