from __future__ import annotations
import json
from pathlib import Path
from .util import now_iso, uid, write_json

class TaskLedger:
    def __init__(self,root:Path,db): self.root=Path(root); self.db=db; self.dir=self.root/'context-os'/'tasks'; self.dir.mkdir(parents=True,exist_ok=True)
    def create(self,project_id,title,constraints=None,meta=None):
        tid=uid('TASK'); now=now_iso(); row={'id':tid,'project_id':project_id,'title':title,'status':'pending','constraints':constraints or [],'journal':[],'created_at':now,'updated_at':now,'meta':meta or {}}
        self._save(row)
        try:
            from .events import EventLog; EventLog(self.root,self.db).emit('task.created',{'task_id':tid,'project_id':project_id,'title':title})
        except Exception: pass
        return row
    def _save(self,row):
        self.db.conn.execute('INSERT OR REPLACE INTO tasks(id,project_id,title,status,constraints_json,journal_json,created_at,updated_at,meta_json) VALUES(?,?,?,?,?,?,?,?,?)',(row['id'],row.get('project_id'),row['title'],row['status'],json.dumps(row.get('constraints',[])),json.dumps(row.get('journal',[])),row['created_at'],row['updated_at'],json.dumps(row.get('meta',{})))); self.db.conn.commit(); write_json(self.dir/f"{row['id']}.json",row)
    def get(self,tid):
        r=self.db.conn.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone();
        if not r:return None
        d=dict(r); d['constraints']=json.loads(d.pop('constraints_json')); d['journal']=json.loads(d.pop('journal_json')); d['meta']=json.loads(d.pop('meta_json')); return d
    def update(self,tid,status=None,note=None,meta=None):
        row=self.get(tid)
        if not row: raise KeyError(tid)
        if status: row['status']=status
        if note: row['journal'].append({'at':now_iso(),'note':note})
        if meta: row['meta'].update(meta)
        row['updated_at']=now_iso(); self._save(row)
        try:
            from .events import EventLog; EventLog(self.root,self.db).emit('task.updated',{'task_id':tid,'project_id':row.get('project_id'),'status':row.get('status')})
        except Exception: pass
        return row
    def list(self,project_id=None,status=None,limit=25):
        sql='SELECT id FROM tasks WHERE 1=1'; args=[]
        if project_id: sql+=' AND project_id=?';args.append(project_id)
        if status: sql+=' AND status=?';args.append(status)
        sql+=' ORDER BY updated_at DESC LIMIT ?';args.append(limit)
        return [self.get(r['id']) for r in self.db.conn.execute(sql,args)]
