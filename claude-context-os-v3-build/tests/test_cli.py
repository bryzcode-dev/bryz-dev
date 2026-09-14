import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_inventory_command(self):
        with tempfile.TemporaryDirectory() as td:
            r = Path(td) / '.claude'; r.mkdir(); (r / 'CLAUDE.md').write_text('# X\nY')
            p = subprocess.run(['python3', str(ROOT / 'contextctl.py'), 'inventory', '--root', str(r)], text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            out = json.loads(p.stdout)
            self.assertEqual(Path(out['root']), r.resolve())
            self.assertEqual(out['files'], 1)
