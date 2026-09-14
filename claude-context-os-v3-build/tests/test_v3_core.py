import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from context_os.config import load_config, save_config, detect_storage_kind
from context_os.db import ContextDB
from context_os.knowledge import KnowledgeStore
from context_os.registry import ProjectRegistry
from context_os.tasks import TaskLedger
from context_os.events import EventLog
from context_os.integrity import build_manifest, verify_manifest
from context_os.policy import PolicyEngine
from context_os.compiler import ContextCompiler
from context_os.assistant import ExecutiveAssistant


class V3CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / 'claude'
        self.runtime = self.base / 'runtime'
        self.root.mkdir()
        self.runtime.mkdir()
        save_config(self.root / 'context-os' / 'config' / 'context-os.json', {
            'version': '3.0.1',
            'profile': 'test',
            'paths': {'claude_root': str(self.root), 'runtime_root': str(self.runtime)},
            'assistant': {'name': 'Avery', 'personality': {'directness': 8, 'humor': 5}},
        })
        self.db = ContextDB(self.runtime / 'context.db')
        self.db.initialize()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_network_storage_detection_is_configuration_not_architecture(self):
        self.assertEqual(detect_storage_kind(Path('/Volumes/BryzConfig/Claude')), 'network_or_removable')
        self.assertEqual(detect_storage_kind(Path('/Users/test/.claude')), 'local')

    def test_knowledge_is_temporal_searchable_and_supersedable(self):
        store = KnowledgeStore(self.root, self.db)
        a = store.add({'type':'FIX','title':'Store join casting','summary':'Cast store_number to STRING before joining legacy sales','status':'active','verified':True,'tags':['bigquery','join']})
        hits = store.search('legacy store join')
        self.assertTrue(any(x['id'] == a['id'] for x in hits))
        b = store.add({'type':'FIX','title':'Canonical store key','summary':'Use canonical_store_key after warehouse migration','status':'active','verified':True})
        store.supersede(a['id'], b['id'])
        old = store.get(a['id'])
        self.assertEqual(old['status'], 'superseded')
        self.assertEqual(old['superseded_by'], b['id'])

    def test_registry_tracks_resources_and_dependencies(self):
        reg = ProjectRegistry(self.root, self.db)
        reg.register({'project_id':'sales','name':'Sales Dashboard','path':'/p/sales','types':['GAS','BigQuery']})
        reg.add_resource('sales','bigquery_dataset','prod.sales','reads')
        reg.register({'project_id':'email','name':'Email Engine','path':'/p/email','types':['GAS']})
        reg.add_dependency('sales','email','depends_on')
        self.assertEqual(reg.find('prod.sales')[0]['project_id'], 'sales')
        impact = reg.impact('prod.sales')
        self.assertIn('sales', impact['direct_projects'])
        self.assertIn('email', reg.related('sales'))

    def test_task_ledger_survives_session_boundaries(self):
        ledger = TaskLedger(self.root, self.db)
        task = ledger.create('sales','Fix location hierarchy',constraints=['preserve sheet schema'])
        ledger.update(task['id'], status='in_progress', note='Mapped join types')
        loaded = ledger.get(task['id'])
        self.assertEqual(loaded['status'],'in_progress')
        self.assertIn('Mapped join types', loaded['journal'][-1]['note'])

    def test_integrity_detects_drift(self):
        f = self.root / 'context-os' / 'runtime' / 'managed.txt'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('good')
        manifest = build_manifest(self.root, [Path('context-os/runtime/managed.txt')])
        self.assertTrue(verify_manifest(self.root, manifest)['ok'])
        f.write_text('changed')
        self.assertFalse(verify_manifest(self.root, manifest)['ok'])

    def test_policy_denies_protected_operations(self):
        p = PolicyEngine(self.root)
        self.assertFalse(p.evaluate('delete_authoritative_knowledge', {'actor':'assistant'}).allowed)
        self.assertFalse(p.evaluate('read_secret', {'actor':'assistant'}).allowed)
        self.assertTrue(p.evaluate('search_knowledge', {'actor':'assistant'}).allowed)

    def test_context_compiler_respects_budget_and_scope(self):
        reg = ProjectRegistry(self.root, self.db)
        reg.register({'project_id':'sales','name':'Sales Dashboard','path':'/p/sales','types':['GAS']})
        store = KnowledgeStore(self.root, self.db)
        for i in range(20):
            store.add({'type':'FIX','title':f'Fix {i}','summary':'regional sales hierarchy ' + ('x '*80), 'status':'active','verified':True,'project_id':'sales'})
        ledger = TaskLedger(self.root, self.db)
        ledger.create('sales','Fix regional sales hierarchy')
        compiler = ContextCompiler(self.root, self.db)
        pack = compiler.compile('sales','regional hierarchy', max_chars=3000)
        self.assertLessEqual(len(pack['rendered']), 3000)
        self.assertIn('Sales Dashboard', pack['rendered'])

    def test_executive_assistant_reads_os_and_keeps_own_memory(self):
        reg = ProjectRegistry(self.root, self.db)
        reg.register({'project_id':'sales','name':'Sales Dashboard','path':'/p/sales','types':['GAS']})
        TaskLedger(self.root,self.db).create('sales','Validate hierarchy')
        ea = ExecutiveAssistant(self.root, self.db)
        response = ea.brief(project_id='sales')
        self.assertIn('Sales Dashboard', response)
        ea.remember_preference('Lead project briefs with blockers', confirmed=True)
        prefs = ea.preferences()
        self.assertTrue(any('blockers' in p['text'].lower() for p in prefs))

    def test_event_log_records_without_source_contents(self):
        log = EventLog(self.root, self.db)
        eid = log.emit('session.started', {'project_id':'sales','path':'/p/sales'})
        row = log.get(eid)
        self.assertEqual(row['event_type'],'session.started')
        self.assertNotIn('source_code', row['payload'])


if __name__ == '__main__':
    unittest.main()
