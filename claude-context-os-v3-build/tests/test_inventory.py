import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from context_os.inventory import inventory_tree


class InventoryTests(unittest.TestCase):
    def test_inventory_hashes_regular_files_and_records_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'CLAUDE.md').write_text('hello', encoding='utf-8')
            (root / 'dir').mkdir()
            (root / 'dir' / 'a.txt').write_text('abc', encoding='utf-8')
            os.symlink(root / 'dir' / 'a.txt', root / 'link.txt')
            rows = inventory_tree(root)
            by_path = {r['path']: r for r in rows}
            self.assertEqual(by_path['CLAUDE.md']['sha256'], hashlib.sha256(b'hello').hexdigest())
            self.assertEqual(by_path['link.txt']['type'], 'symlink')
            self.assertIn('target', by_path['link.txt'])
