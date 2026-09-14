from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import shutil, subprocess, json

@dataclass
class Decision:
    allowed: bool
    reason: str
    requires_confirmation: bool=False

class PolicyEngine:
    HARD_DENY={'read_secret','delete_backup','disable_audit','disable_policy','delete_authoritative_knowledge'}
    SAFE={'search_knowledge','read_project','read_health','create_task','create_snapshot','reindex','read_resource','impact_analysis'}
    def __init__(self,root:Path): self.root=Path(root)
    def evaluate(self,action,context=None):
        context=context or {}
        if action in self.HARD_DENY: return Decision(False,f'{action} is protected by Context OS policy')
        if action in self.SAFE: return Decision(True,'allowed')
        if action in {'modify_global_rule','supersede_knowledge','change_security_config'}: return Decision(False,'requires explicit user confirmation',True)
        return Decision(True,'default local policy allow')
    def opa_available(self): return shutil.which('opa') is not None
