from __future__ import annotations
from pathlib import Path
from .knowledge import KnowledgeStore
from .registry import ProjectRegistry
from .tasks import TaskLedger

class ContextCompiler:
    def __init__(self,root:Path,db): self.root=Path(root); self.db=db
    def compile(self,project_id,query,max_chars=9000):
        reg=ProjectRegistry(self.root,self.db); ks=KnowledgeStore(self.root,self.db); tasks=TaskLedger(self.root,self.db)
        p=reg.get(project_id) if project_id else None
        hits=ks.search(query,project_id=project_id,limit=8)
        active=tasks.list(project_id=project_id,limit=8)
        parts=['CONTEXT OS COMPILED PACK']
        if p: parts += [f"Project: {p['name']} ({p['project_id']})",f"Types: {', '.join(p['types'])}",f"Status: {p['status']}"]
        if active:
            parts.append('Tasks:')
            for t in active: parts.append(f"- {t['id']} [{t['status']}] {t['title']}")
        if hits:
            parts.append('Relevant knowledge:')
            for h in hits: parts.append(f"- {h['id']} {h['title']}: {h['summary']}")
        rendered='\n'.join(parts)
        if len(rendered)>max_chars: rendered=rendered[:max_chars-80]+'\n[Context truncated to configured budget]'
        return {'project':p,'tasks':active,'knowledge':hits,'rendered':rendered,'budget_chars':max_chars}
