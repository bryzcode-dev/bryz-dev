import json
import tempfile
import unittest
from pathlib import Path

from context_os.knowledge import add_knowledge, search_knowledge, register_project, find_projects


class KnowledgeTests(unittest.TestCase):
    def test_add_and_search_cross_project_knowledge(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            item = add_knowledge(root, {
                'type': 'FIX', 'title': 'Store key type mismatch', 'project_id': 'sales-dashboard',
                'domains': ['sql', 'bigquery'], 'tags': ['join', 'store_number'],
                'summary': 'Cast operations.store_number to STRING before joining legacy sales.',
                'verified': True,
            })
            self.assertTrue(item.exists())
            results = search_knowledge(root, 'store_number join')
            self.assertEqual(results[0]['title'], 'Store key type mismatch')
            self.assertEqual(results[0]['project_id'], 'sales-dashboard')

    def test_register_and_find_project_by_resource(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = {
                'project_id': 'inventory', 'name': 'Inventory Dashboard', 'type': ['GAS', 'BigQuery'],
                'resources': {'production_url': 'https://example.test/app', 'sheet_id': 'sheet-123'},
                'related_projects': ['email-engine']
            }
            register_project(root, manifest, '/work/inventory')
            hits = find_projects(root, 'sheet-123')
            self.assertEqual(hits[0]['project_id'], 'inventory')
