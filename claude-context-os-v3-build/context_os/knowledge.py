from __future__ import annotations
import json, re
from pathlib import Path
from .util import now_iso, uid, write_json

class KnowledgeStore:
    def __init__(self, root: Path, db):
        self.root=Path(root); self.db=db
        self.dir=self.root/'context-os'/'knowledge'; self.dir.mkdir(parents=True, exist_ok=True)
    def add(self, item: dict) -> dict:
        kid=item.get('id') or uid(item.get('type','MEM'))
        row={
          'id':kid,'type':item.get('type','NOTE'),'title':item['title'],'summary':item['summary'],
          'status':item.get('status','candidate'),'verified':bool(item.get('verified',False)),
          'confidence':float(item.get('confidence',1.0 if item.get('verified') else .5)),
          'project_id':item.get('project_id'),'domain':item.get('domain'),'tags':item.get('tags',[]),
          'evidence':item.get('evidence',[]),'created_at':item.get('created_at',now_iso()),
          'verified_at':item.get('verified_at',now_iso() if item.get('verified') else None),
          'last_used_at':item.get('last_used_at'),'last_verified_at':item.get('last_verified_at'),
          'valid_from':item.get('valid_from'),'valid_until':item.get('valid_until'),'superseded_by':item.get('superseded_by'),
          'provenance':item.get('provenance',{}),'applicability':item.get('applicability',{}),
        }
        path=self.dir/f'{kid}.json'; row['source_path']=str(path)
        write_json(path,row)
        c=self.db.conn
        c.execute('''INSERT OR REPLACE INTO knowledge(id,type,title,summary,status,verified,confidence,project_id,domain,tags_json,evidence_json,created_at,verified_at,last_used_at,last_verified_at,valid_from,valid_until,superseded_by,source_path,provenance_json,applicability_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
          kid,row['type'],row['title'],row['summary'],row['status'],int(row['verified']),row['confidence'],row['project_id'],row['domain'],json.dumps(row['tags']),json.dumps(row['evidence']),row['created_at'],row['verified_at'],row['last_used_at'],row['last_verified_at'],row['valid_from'],row['valid_until'],row['superseded_by'],row['source_path'],json.dumps(row['provenance']),json.dumps(row['applicability'])))
        if self.db.fts5:
            c.execute('DELETE FROM knowledge_fts WHERE id=?',(kid,))
            c.execute('INSERT INTO knowledge_fts(id,title,summary,tags,project_id,domain) VALUES(?,?,?,?,?,?)',(kid,row['title'],row['summary'],' '.join(row['tags']),row['project_id'] or '',row['domain'] or ''))
        c.commit(); return row
    def get(self,kid):
        r=self.db.conn.execute('SELECT * FROM knowledge WHERE id=?',(kid,)).fetchone()
        if not r:return None
        d=dict(r); d['verified']=bool(d['verified']); d['tags']=json.loads(d.pop('tags_json')); d['evidence']=json.loads(d.pop('evidence_json')); d['provenance']=json.loads(d.pop('provenance_json','{}')); d['applicability']=json.loads(d.pop('applicability_json','{}')); return d
    def supersede(self,old_id,new_id):
        self.db.conn.execute("UPDATE knowledge SET status='superseded', superseded_by=? WHERE id=?",(new_id,old_id)); self.db.conn.commit()
        old=self.get(old_id)
        if old and old.get('source_path'):
            write_json(Path(old['source_path']),old)
    def search(self,query,project_id=None,domain=None,limit=10):
        c=self.db.conn; rows=[]
        if self.db.fts5:
            safe=' '.join(re.findall(r'[\w.-]+',query))
            sql='''SELECT k.*, bm25(knowledge_fts) AS rank FROM knowledge_fts JOIN knowledge k ON k.id=knowledge_fts.id WHERE knowledge_fts MATCH ? AND k.status IN ('active','candidate')'''
            args=[safe or query]
            if project_id: sql+=' AND (k.project_id=? OR k.project_id IS NULL)'; args.append(project_id)
            if domain: sql+=' AND (k.domain=? OR k.domain IS NULL)'; args.append(domain)
            sql+=' ORDER BY rank LIMIT ?'; args.append(limit)
            try: rows=c.execute(sql,args).fetchall()
            except Exception: rows=[]
        if not rows:
            like=f"%{query}%"; sql="SELECT * FROM knowledge WHERE status IN ('active','candidate') AND (title LIKE ? OR summary LIKE ?)"; args=[like,like]
            if project_id: sql+=' AND (project_id=? OR project_id IS NULL)'; args.append(project_id)
            if domain: sql+=' AND (domain=? OR domain IS NULL)'; args.append(domain)
            sql+=' ORDER BY verified DESC, confidence DESC LIMIT ?'; args.append(limit)
            rows=c.execute(sql,args).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d['verified']=bool(d['verified']); d['tags']=json.loads(d.pop('tags_json')); d['evidence']=json.loads(d.pop('evidence_json')); d['provenance']=json.loads(d.pop('provenance_json','{}')); d['applicability']=json.loads(d.pop('applicability_json','{}')); out.append(d)
        return out

    def conflicts(self,limit=50):
        rows=[self.get(r['id']) for r in self.db.conn.execute("SELECT id FROM knowledge WHERE status='active' ORDER BY created_at DESC LIMIT 500")]
        def toks(x):
            return {t.lower() for t in re.findall(r'[A-Za-z0-9_]+', (x.get('title','')+' '+x.get('summary',''))) if len(t)>3}
        out=[]
        for i,a in enumerate(rows):
            ta=toks(a)
            for b in rows[i+1:]:
                if a['id']==b['id'] or (a.get('project_id') and b.get('project_id') and a['project_id']!=b['project_id']): continue
                tb=toks(b); union=ta|tb
                score=len(ta&tb)/len(union) if union else 0
                if score>=0.45 and a['summary'].strip().lower()!=b['summary'].strip().lower():
                    out.append({'a':a['id'],'b':b['id'],'similarity':round(score,3),'reason':'high lexical overlap with differing active statements'})
                    if len(out)>=limit:return out
        return out

# V1 compatibility helpers
def add_knowledge(root: Path, item: dict):
    from .db import ContextDB
    from .ops import runtime_for
    runtime=runtime_for(root)
    db=ContextDB(runtime/'context.db').initialize(); row=KnowledgeStore(root,db).add(item); db.close(); return Path(row['source_path'])
def search_knowledge(root: Path, query: str, project_id=None, domain=None):
    from .db import ContextDB
    from .ops import runtime_for
    runtime=runtime_for(root)
    db=ContextDB(runtime/'context.db').initialize(); out=KnowledgeStore(root,db).search(query,project_id,domain); db.close(); return out

# compatibility re-exports
from .registry import register_project, find_projects
