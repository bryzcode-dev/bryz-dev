import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EndToEndTests(unittest.TestCase):
    def test_adopt_then_health_then_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            r = base / '.claude'; r.mkdir()
            (r / 'CLAUDE.md').write_text('# Workflow\nInspect before modifying\n# SQL\nVerify source schema\n')
            (r / 'settings.json').write_text(json.dumps({'theme': 'dark'}))
            (r / 'notes.md').write_text('preserve this')
            p = subprocess.run(['python3', str(ROOT/'contextctl.py'), 'adopt', '--root', str(r), '--workspace', str(base/'work'), '--activate', '--skip-semantic-review'], text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue((r / 'context-os' / 'migration' / 'ACTIVE_MIGRATION.json').exists())
            self.assertTrue((r / 'context-os' / 'legacy-preserved' / 'notes.md').exists())
            health = subprocess.run(['python3', str(ROOT/'contextctl.py'), 'health', '--root', str(r)], text=True, capture_output=True)
            self.assertEqual(health.returncode, 0, health.stdout + health.stderr)
            active_meta = json.loads((r / 'context-os' / 'migration' / 'ACTIVE_MIGRATION.json').read_text())
            rb = subprocess.run(['python3', str(ROOT/'contextctl.py'), 'rollback', '--root', str(r), '--rollback-root', active_meta['rollback_root']], text=True, capture_output=True)
            self.assertEqual(rb.returncode, 0, rb.stderr)
            self.assertTrue((r / 'notes.md').exists())
