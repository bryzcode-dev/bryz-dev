#!/usr/bin/env python3
from _common import payload,append_event
p=payload(); append_event('session.postcompact',{'session_id':p.get('session_id'),'cwd':p.get('cwd')})
print('<context-os-checkpoint>Context was compacted. Re-read current project task/state from Context OS before making architectural assumptions.</context-os-checkpoint>')
