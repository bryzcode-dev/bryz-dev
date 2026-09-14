#!/usr/bin/env python3
from _common import payload,append_event
p=payload(); ti=p.get('tool_input') or {}; summary=''
if p.get('tool_name')=='Bash': summary=str(ti.get('command',''))[:160]
elif p.get('tool_name') in {'Read','Write','Edit'}: summary=str(ti.get('file_path',''))[:240]
append_event('tool.post',{'tool':p.get('tool_name'),'summary':summary,'session_id':p.get('session_id')})
