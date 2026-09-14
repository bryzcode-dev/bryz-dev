#!/usr/bin/env python3
import json,re
from _common import payload,append_event
p=payload();tool=p.get('tool_name','');ti=p.get('tool_input') or {};deny=None
if tool=='Bash':
    cmd=str(ti.get('command',''));patterns=[r'\bgit\s+reset\s+--hard\b',r'\bgit\s+push\s+.*--force\b',r'\brm\s+-rf\s+/(?:\s|$)',r'\bDROP\s+(?:DATABASE|SCHEMA|TABLE)\b',r'\bTRUNCATE\s+TABLE\b']
    if any(re.search(x,cmd,re.I) for x in patterns):deny='Protected/destructive command blocked by Context OS policy.'
for key in ('file_path','path'):
    val=str(ti.get(key,'') or '')
    if val and '/context-os/runtime/' in val and tool in {'Write','Edit'}:deny='Context OS managed runtime is protected. Use the upgrade/repair workflow.'
if deny:
    append_event('policy.denied',{'tool':tool,'reason':deny})
    print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':deny}}))
else:append_event('tool.pre',{'tool':tool})
