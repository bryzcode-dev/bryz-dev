#!/usr/bin/env python3
import runpy,sys
from pathlib import Path
target=Path(__file__).resolve().parents[1]/'context-os'/'runtime'/'hooks'/'session_start.py'
sys.path.insert(0,str(target.parent))
runpy.run_path(str(target),run_name='__main__')
