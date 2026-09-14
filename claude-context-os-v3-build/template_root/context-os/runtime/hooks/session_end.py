#!/usr/bin/env python3
from _common import payload,append_event
p=payload(); append_event('session.ended',{'session_id':p.get('session_id'),'cwd':p.get('cwd'),'reason':p.get('reason')})
