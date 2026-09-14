from __future__ import annotations
import json
from pathlib import Path
from .config import load_config
from .registry import ProjectRegistry
from .tasks import TaskLedger
from .events import EventLog
from .knowledge import KnowledgeStore
from .policy import PolicyEngine
from .util import now_iso, uid

class ExecutiveAssistant:
    def __init__(self,root:Path,db):
        self.root=Path(root); self.db=db; self.cfg=load_config(self.root/'context-os'/'config'/'context-os.json')
        self.name=self.cfg.get('assistant',{}).get('name','Executive Assistant')
    def remember_preference(self,text,confirmed=False):
        pid=uid('PREF'); self.db.conn.execute('INSERT INTO assistant_preferences(id,text,confirmed,created_at) VALUES(?,?,?,?)',(pid,text,int(confirmed),now_iso())); self.db.conn.commit(); return {'id':pid,'text':text,'confirmed':confirmed}
    def preferences(self):
        return [dict(r) for r in self.db.conn.execute('SELECT id,text,confirmed,created_at,last_used_at FROM assistant_preferences ORDER BY confirmed DESC, created_at DESC')]
    def brief(self,project_id=None):
        reg=ProjectRegistry(self.root,self.db); ledger=TaskLedger(self.root,self.db)
        lines=[f'◆ {self.name}']
        if project_id:
            p=reg.get(project_id)
            if not p:return '\n'.join(lines+[f'Project {project_id} is not registered.'])
            lines += ['',p['name'],f"Status: {p['status']}"]
            tasks=ledger.list(project_id=project_id,limit=8)
            if tasks:
                lines.append('Current work:')
                for t in tasks: lines.append(f"- {t['id']} [{t['status']}] {t['title']}")
            else: lines.append('No tracked tasks are active for this project.')
            if p['resources']:
                lines.append(f"Resources registered: {len(p['resources'])}")
        else:
            rows=self.db.conn.execute("SELECT project_id,name,status FROM projects ORDER BY updated_at DESC LIMIT 12").fetchall()
            open_tasks=self.db.conn.execute("SELECT COUNT(*) c FROM tasks WHERE status NOT IN ('done','cancelled')").fetchone()['c']
            lines += ['',f'Projects registered: {len(rows)}',f'Open tasks: {open_tasks}']
            for r in rows: lines.append(f"- {r['name']} [{r['status']}]")
        return '\n'.join(lines)
    def investigate(self,query,project_id=None):
        hits=KnowledgeStore(self.root,self.db).search(query,project_id=project_id,limit=8)
        if not hits:return f'◆ {self.name}\n\nI found no verified or candidate knowledge matching that question.'
        lines=[f'◆ {self.name}','','I found these relevant records:']
        for h in hits: lines.append(f"- {h['id']} {h['title']}: {h['summary']}")
        return '\n'.join(lines)
    def status(self):
        projects=self.db.conn.execute('SELECT COUNT(*) c FROM projects').fetchone()['c']; knowledge=self.db.conn.execute('SELECT COUNT(*) c FROM knowledge').fetchone()['c']; tasks=self.db.conn.execute("SELECT COUNT(*) c FROM tasks WHERE status NOT IN ('done','cancelled')").fetchone()['c']
        return {'assistant':self.name,'projects':projects,'knowledge_records':knowledge,'open_tasks':tasks,'policy':'enabled'}
