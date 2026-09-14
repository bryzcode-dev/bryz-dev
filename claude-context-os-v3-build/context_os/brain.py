from __future__ import annotations
from pathlib import Path
from .registry import ProjectRegistry
from .tasks import TaskLedger
from .knowledge import KnowledgeStore

class ProjectBrain:
    def __init__(self,root:Path,db):self.root=Path(root);self.db=db
    def compile(self,project_id):
        reg=ProjectRegistry(self.root,self.db); p=reg.get(project_id)
        if not p:return None
        tasks=TaskLedger(self.root,self.db).list(project_id=project_id,limit=25)
        knowledge=KnowledgeStore(self.root,self.db).search(project_id,project_id=project_id,limit=25)
        return {'project':p,'tasks':tasks,'knowledge':knowledge,'related_projects':reg.related(project_id)}
