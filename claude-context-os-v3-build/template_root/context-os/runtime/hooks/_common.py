from __future__ import annotations
import json, os, sys
from pathlib import Path

def payload():
    try:return json.load(sys.stdin)
    except Exception:return {}
def context_home():
    env=os.environ.get('CONTEXT_OS_HOME')
    if env:return Path(env)
    return Path(__file__).resolve().parents[2]
def claude_root():return context_home().parent
def runtime_root():
    env=os.environ.get('CONTEXT_OS_RUNTIME')
    if env:runtime=Path(env).expanduser().resolve()
    else:
        try:
            cfg=json.loads((context_home()/'config'/'context-os.json').read_text(encoding='utf-8'))
        except Exception:cfg={}
        runtime=Path(cfg.get('paths',{}).get('runtime_root','~/Library/Application Support/ClaudeContextOS/home')).expanduser().resolve()
    if str(runtime).startswith('/Volumes/BryzConfig/Claude'):
        raise RuntimeError(f'runtime path must be local: {runtime}')
    return runtime
def append_event(event_type,data):
    import datetime
    envlog=os.environ.get('CONTEXT_OS_ACTIVITY_LOG')
    p=Path(envlog) if envlog else runtime_root()/'hook-events.jsonl';p.parent.mkdir(parents=True,exist_ok=True)
    safe={k:v for k,v in (data or {}).items() if k.lower() not in {'content','source_code','tool_response','token','password','secret','credential'}}
    row={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'event_type':event_type,'payload':safe}
    with p.open('a',encoding='utf-8') as f:f.write(json.dumps(row,sort_keys=True)+'\n')
def app_path():
    p=context_home()/'runtime'/'app'
    if str(p) not in sys.path:sys.path.insert(0,str(p))
    return p
