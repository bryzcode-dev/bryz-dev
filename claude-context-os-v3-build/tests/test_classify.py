import tempfile
import unittest
from pathlib import Path

from context_os.classify import classify_section, looks_secret, split_markdown_sections


class ClassifyTests(unittest.TestCase):
    def test_split_markdown_sections_uses_headings(self):
        parts = split_markdown_sections('# Global Rules\nNever force push\n## GAS\nUse PropertiesService\n')
        self.assertEqual([p['title'] for p in parts], ['Global Rules', 'GAS'])
        self.assertIn('PropertiesService', parts[1]['body'])

    def test_classifies_sql_and_gas(self):
        self.assertEqual(classify_section('SQL', 'BigQuery joins and dataset grain')['domain'], 'sql')
        self.assertEqual(classify_section('Apps Script', 'GAS trigger deployment')['domain'], 'gas')

    def test_secret_detection_by_name_and_content(self):
        self.assertTrue(looks_secret(Path('.env'), None))
        self.assertTrue(looks_secret(Path('notes.txt'), 'api_key = "abc123456789"'))
        self.assertFalse(looks_secret(Path('notes.txt'), 'BigQuery dataset notes'))
