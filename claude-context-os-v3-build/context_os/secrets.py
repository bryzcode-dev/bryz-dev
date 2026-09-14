from __future__ import annotations
import re, shutil, subprocess, json
from pathlib import Path
PATTERNS=[
 ('private_key',re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
 ('generic_secret',re.compile(r'(?i)(api[_-]?key|client[_-]?secret|password|token)\s*[:=]\s*["\']?[^\s"\']{8,}')),
 ('aws_key',re.compile(r'AKIA[0-9A-Z]{16}')),
]
SENSITIVE_NAMES={'.env','credentials.json','service-account.json','id_rsa','id_ed25519'}
def scan_tree(root:Path,max_bytes=2_000_000,exclude_prefixes=None):
    root=Path(root); findings=[]; exclude_prefixes=tuple(str(x).strip("/") for x in (exclude_prefixes or []))
    if not root.exists(): return findings
    for p in root.rglob('*'):
        if not p.is_file() or p.is_symlink(): continue
        rel=str(p.relative_to(root)); low=p.name.lower()
        if any(rel == pref or rel.startswith(pref + '/') for pref in exclude_prefixes): continue
        if p.name in SENSITIVE_NAMES or any(x in low for x in ('credential','private_key','secret')):
            findings.append({'path':rel,'kind':'sensitive_name'})
        try:
            if p.stat().st_size>max_bytes: continue
            text=p.read_text(encoding='utf-8',errors='ignore')
        except Exception: continue
        for kind,pat in PATTERNS:
            if pat.search(text): findings.append({'path':rel,'kind':kind}); break
    # de-dupe
    seen=set(); out=[]
    for f in findings:
        k=(f['path'],f['kind'])
        if k not in seen: seen.add(k); out.append(f)
    return out

def gitleaks_available(): return shutil.which('gitleaks') is not None

def scan_with_gitleaks(root:Path):
    if not gitleaks_available(): return {'available':False,'findings':[]}
    cp=subprocess.run(['gitleaks','dir',str(root),'--report-format','json','--report-path','-','--no-banner'],capture_output=True,text=True)
    try: data=json.loads(cp.stdout or '[]')
    except Exception: data=[]
    return {'available':True,'findings':data,'returncode':cp.returncode}
