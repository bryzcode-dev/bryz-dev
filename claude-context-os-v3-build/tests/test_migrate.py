import json
import tempfile
import unittest
from pathlib import Path

from context_os.migrate import prepare_migration, build_stage
from context_os.verify import verify_stage

ROOT = Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def make_legacy(self, root: Path):
        root.mkdir(parents=True)
        (root / 'CLAUDE.md').write_text('# SQL Rules\nVerify grain before joins\n# GAS\nPreserve triggers\n')
        (root / 'settings.json').write_text(json.dumps({'theme': 'dark', 'custom': 7}))
        (root / 'projects').mkdir()
        (root / 'projects' / 'p1').mkdir()
        (root / 'projects' / 'p1' / 'MEMORY.md').write_text('remember me')
        (root / 'mystery.txt').write_text('legacy useful content')
        (root / '.env').write_text('API_KEY=abc123456789')

    def test_stage_preserves_source_and_accounts_for_files(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            src = base / '.claude'
            self.make_legacy(src)
            original = (src / 'CLAUDE.md').read_text()
            paths = prepare_migration(src, base / 'work')
            report = build_stage(paths, ROOT / 'template_root')
            self.assertEqual((src / 'CLAUDE.md').read_text(), original)
            self.assertTrue((paths.stage / 'projects' / 'p1' / 'MEMORY.md').exists())
            self.assertTrue((paths.stage / 'context-os' / 'legacy-preserved' / 'mystery.txt').exists())
            self.assertTrue((paths.stage / 'context-os' / 'migration' / 'review' / '.env.secret-ref.json').exists())
            result = verify_stage(paths)
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(json.loads((paths.stage / 'settings.json').read_text())['theme'], 'dark')
            self.assertGreater(len(report['claude_sections']), 0)
