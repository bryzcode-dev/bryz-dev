from __future__ import annotations
import json
from pathlib import Path
from .util import now_iso, write_json

class ProjectRegistry:
    def __init__(self,root:Path,db): self.root=Path(root); self.db=db; (self.root/'context-os'/'projects').mkdir(parents=True,exist_ok=True)
    def register(self,m:dict):
        pid=m['project_id']; row={'project_id':pid,'name':m.get('name',pid),'path':m.get('path',''),'types':m.get('types',m.get('type',[])),'status':m.get('status','active'),'updated_at':now_iso(),'meta':{k:v for k,v in m.items() if k not in {'project_id','name','path','types','type','status'}}}
        self.db.conn.execute('INSERT OR REPLACE INTO projects(project_id,name,path,types_json,status,updated_at,meta_json) VALUES(?,?,?,?,?,?,?)',(pid,row['name'],row['path'],json.dumps(row['types']),row['status'],row['updated_at'],json.dumps(row['meta']))); self.db.conn.commit(); write_json(self.root/'context-os'/'projects'/f'{pid}.json',row)
        try:
            from .events import EventLog; EventLog(self.root,self.db).emit('project.registered',{'project_id':pid,'name':row['name'],'path':row['path']})
        except Exception: pass
        return row
    def add_resource(self,pid,type_,value,relation='uses',meta=None):
        self.db.conn.execute('INSERT OR IGNORE INTO resources(project_id,type,value,relation,meta_json) VALUES(?,?,?,?,?)',(pid,type_,value,relation,json.dumps(meta or {}))); self.db.conn.commit()
        try:
            from .events import EventLog; EventLog(self.root,self.db).emit('resource.changed',{'project_id':pid,'type':type_,'value':value,'relation':relation})
        except Exception: pass
    def add_dependency(self,src,dst,relation='depends_on',meta=None):
        self.db.conn.execute('INSERT OR IGNORE INTO dependencies(src_project,dst_project,relation,meta_json) VALUES(?,?,?,?)',(src,dst,relation,json.dumps(meta or {}))); self.db.conn.commit()
        try:
            from .events import EventLog; EventLog(self.root,self.db).emit('dependency.changed',{'source':src,'target':dst,'relation':relation})
        except Exception: pass
    def get(self,pid):
        r=self.db.conn.execute('SELECT * FROM projects WHERE project_id=?',(pid,)).fetchone()
        if not r:return None
        d=dict(r); d['types']=json.loads(d.pop('types_json')); d['meta']=json.loads(d.pop('meta_json')); d['resources']=[dict(x) for x in self.db.conn.execute('SELECT type,value,relation FROM resources WHERE project_id=?',(pid,))]; return d
    def find(self,q):
        like=f'%{q}%'; rows=self.db.conn.execute('''SELECT DISTINCT p.* FROM projects p LEFT JOIN resources r ON p.project_id=r.project_id WHERE p.project_id LIKE ? OR p.name LIKE ? OR p.path LIKE ? OR r.value LIKE ? ORDER BY p.updated_at DESC''',(like,like,like,like)).fetchall(); return [self.get(r['project_id']) for r in rows]
    def related(self,pid):
        rows=self.db.conn.execute('SELECT src_project,dst_project FROM dependencies WHERE src_project=? OR dst_project=?',(pid,pid)).fetchall(); out=set();
        for r in rows: out.add(r['dst_project'] if r['src_project']==pid else r['src_project'])
        return sorted(out)
    def impact(self,resource_text):
        rows=self.db.conn.execute('SELECT DISTINCT project_id FROM resources WHERE value LIKE ?',(f'%{resource_text}%',)).fetchall(); direct=[r['project_id'] for r in rows]; indirect=set()
        for p in direct: indirect.update(self.related(p))
        indirect.difference_update(direct); return {'resource':resource_text,'direct_projects':sorted(direct),'related_projects':sorted(indirect),'risk':'high' if len(direct)>2 else 'medium' if direct else 'low'}

# V1 compatibility helpers
def _open(root:Path):
    from .db import ContextDB
    from .ops import runtime_for
    runtime=runtime_for(root)
    return ContextDB(runtime/'context.db').initialize()
def register_project(root:Path,manifest:dict,path:str):
    db=_open(root); m=dict(manifest); m['path']=path; row=ProjectRegistry(root,db).register(m)
    for k,v in (manifest.get('resources') or {}).items():
        if isinstance(v,str): ProjectRegistry(root,db).add_resource(row['project_id'],k,v)
        elif isinstance(v,list):
            for x in v:
                if isinstance(x,str): ProjectRegistry(root,db).add_resource(row['project_id'],k,x)
    db.close(); return row
def find_projects(root:Path,query:str):
    db=_open(root); out=ProjectRegistry(root,db).find(query); db.close(); return out
