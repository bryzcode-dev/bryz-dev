from __future__ import annotations
import json
from pathlib import Path
from .util import now_iso, uid

SENSITIVE_KEYS={'source_code','content','secret','password','token','credential','api_key'}
class EventLog:
    def __init__(self,root:Path,db): self.root=Path(root); self.db=db
    def emit(self,event_type,payload=None):
        payload=dict(payload or {})
        for k in list(payload):
            if k.lower() in SENSITIVE_KEYS: payload.pop(k,None)
        eid=uid('EVT'); self.db.conn.execute('INSERT INTO events(id,event_type,created_at,payload_json) VALUES(?,?,?,?)',(eid,event_type,now_iso(),json.dumps(payload))); self.db.conn.commit(); return eid
    def get(self,eid):
        r=self.db.conn.execute('SELECT * FROM events WHERE id=?',(eid,)).fetchone();
        if not r:return None
        d=dict(r); d['payload']=json.loads(d.pop('payload_json')); return d
    def recent(self,limit=50):
        return [self.get(r['id']) for r in self.db.conn.execute('SELECT id FROM events ORDER BY created_at DESC LIMIT ?',(limit,))]
