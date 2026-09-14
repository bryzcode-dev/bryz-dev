from __future__ import annotations

import re
from pathlib import Path

SECRET_NAME_PATTERNS = [
    re.compile(r'(^|/)\.env($|\.)', re.I),
    re.compile(r'(credential|secret|token|auth|private[_-]?key)', re.I),
]
SECRET_CONTENT_PATTERNS = [
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)\b\s*[:=]\s*["\']?[^\s"\']{8,}'),
]


def split_markdown_sections(text: str) -> list[dict]:
    sections: list[dict] = []
    current_title = 'Preamble'
    body: list[str] = []
    level = 0
    for line in text.splitlines():
        m = re.match(r'^(#{1,6})\s+(.+?)\s*$', line)
        if m:
            if body or current_title != 'Preamble':
                sections.append({'title': current_title, 'level': level, 'body': '\n'.join(body).strip()})
            current_title = m.group(2).strip()
            level = len(m.group(1))
            body = []
        else:
            body.append(line)
    if body or current_title != 'Preamble':
        sections.append({'title': current_title, 'level': level, 'body': '\n'.join(body).strip()})
    return [s for s in sections if s['title'] != 'Preamble' or s['body']]


def classify_section(title: str, body: str) -> dict:
    blob = f'{title}\n{body}'.lower()
    domain = 'general'
    if any(k in blob for k in ('apps script', 'google apps script', ' gas ', 'gas ', 'clasp', 'scriptapp', 'propertiesservice')):
        domain = 'gas'
    elif any(k in blob for k in ('sql', 'bigquery', 'teradata', 'dataset', 'warehouse', 'join', 'query')):
        domain = 'sql'
    elif any(k in blob for k in ('debug', 'root cause', 'bug', 'error', 'fix')):
        domain = 'debugging'
    elif any(k in blob for k in ('datacube', 'data cube', 'cube')):
        domain = 'datacube'

    kind = 'rule'
    if any(k in blob for k in ('url', 'http://', 'https://', 'script id', 'sheet id', 'deployment')):
        kind = 'resource'
    elif any(k in blob for k in ('step 1', 'workflow', 'procedure', 'process', 'runbook')):
        kind = 'procedure'
    elif any(k in blob for k in ('preference', 'i prefer', 'always ask', 'do not ask')):
        kind = 'preference'

    destination = {
        'procedure': 'skill-reference',
        'resource': 'project-or-resource-registry',
        'preference': 'global-rule',
        'rule': 'global-or-project-rule',
    }[kind]
    return {'domain': domain, 'kind': kind, 'suggested_destination': destination, 'confidence': 0.75 if domain != 'general' else 0.55}


def looks_secret(path: Path, text: str | None) -> bool:
    s = path.as_posix()
    if any(p.search(s) for p in SECRET_NAME_PATTERNS):
        return True
    return bool(text and any(p.search(text) for p in SECRET_CONTENT_PATTERNS))
