import json
import tempfile
import unittest
from pathlib import Path

from context_os.inventory import inventory_tree
from context_os.shared_migrate import (
    activate_shared,
    build_shared_stage,
    probe_shared_rollback,
    prepare_shared_migration,
    rollback_shared,
    verify_shared_stage,
)
from context_os.migrate import mark_semantic_review
from tests.shared_nas_fixture import ROOT, make_three_machine_fixture
from tests.shared_nas_fixture import fail_prepared_stage_rename


class SharedMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.fixture = make_three_machine_fixture(self.base)

    def tearDown(self):
        self.tempdir.cleanup()

    def prepare_and_build(self):
        migration = prepare_shared_migration(self.fixture.topology, self.base / 'work')
        build_shared_stage(migration, ROOT / 'template_root', ROOT)
        return migration

    def reviewed_and_probed(self):
        migration = self.prepare_and_build()
        mark_semantic_review(migration.paths, 'test-suite')
        probe_shared_rollback(migration)
        return migration

    def test_shared_migration_snapshots_shared_only(self):
        before = inventory_tree(self.fixture.machines_root)
        migration = self.prepare_and_build()
        self.assertEqual(migration.paths.source, self.fixture.shared_root.resolve())
        self.assertEqual(inventory_tree(self.fixture.machines_root), before)
        report = json.loads((
            migration.paths.stage / 'context-os/migration/migration-report.json'
        ).read_text())
        sources = {row['source'] for row in report['mappings']}
        self.assertNotIn('machines', sources)
        self.assertNotIn('shared', sources)

    def test_nonempty_shared_claude_requires_semantic_review(self):
        migration = self.prepare_and_build()
        status = json.loads((
            migration.paths.stage / 'context-os/migration/semantic-review.json'
        ).read_text())
        self.assertEqual(status['status'], 'pending')
        reviewed = migration.paths.stage / 'context-os/migration/review/legacy-CLAUDE.md'
        self.assertEqual(reviewed.read_text(), self.fixture.original_claude)

    def test_shared_stage_uses_portable_runtime_and_topology_config(self):
        migration = self.prepare_and_build()
        config = json.loads((
            migration.paths.stage / 'context-os/config/context-os.json'
        ).read_text())
        topology = json.loads((
            migration.paths.stage / 'context-os/config/topology.json'
        ).read_text())
        self.assertEqual(
            config['paths']['runtime_root'],
            '~/Library/Application Support/ClaudeContextOS/home',
        )
        self.assertEqual(config['paths']['claude_root'], str(self.fixture.shared_root.resolve()))
        self.assertEqual(topology['layout'], 'shared-nas-v1')

    def test_shared_stage_preserves_existing_settings_and_hooks(self):
        settings_path = self.fixture.shared_root / 'settings.json'
        settings_path.write_text(json.dumps({
            'theme': 'dark',
            'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'existing-stop'}]}]},
        }))
        migration = self.prepare_and_build()
        staged = json.loads((migration.paths.stage / 'settings.json').read_text())
        self.assertEqual(staged['theme'], 'dark')
        self.assertEqual(staged['hooks']['Stop'][0]['hooks'][0]['command'], 'existing-stop')
        managed = staged['hooks']['SessionStart'][-1]['hooks'][0]['command']
        self.assertIn('$HOME/.claude/context-os/runtime/hooks/session_start.py', managed)

    def test_shared_verifier_rejects_nas_runtime(self):
        migration = self.prepare_and_build()
        config_path = migration.paths.stage / 'context-os/config/context-os.json'
        config = json.loads(config_path.read_text())
        config['paths']['runtime_root'] = str(self.fixture.container_root.resolve() / 'runtime')
        config_path.write_text(json.dumps(config))
        result = verify_shared_stage(migration)
        self.assertFalse(result.ok)
        self.assertTrue(any('runtime path must be local' in e for e in result.errors))

    def test_shared_verifier_accepts_structurally_valid_pending_stage(self):
        migration = self.prepare_and_build()
        result = verify_shared_stage(migration)
        self.assertTrue(result.ok, result.errors)

    def test_shared_stage_writes_ready_primary_enrollment_plan(self):
        migration = self.prepare_and_build()
        plan = json.loads(migration.enrollment_plan.read_text())
        self.assertEqual(plan['machine_id'], 'mac-mini-m4')
        self.assertEqual(plan['status'], 'ready')
        self.assertEqual(
            {Path(row['path']).name for row in plan['actions']},
            {'context-os', 'commands', 'rules', 'context-os-machine.json'},
        )

    def test_activate_shared_swaps_only_shared_directory_and_rolls_back(self):
        machine_before = inventory_tree(self.fixture.machines_root)
        migration = self.reviewed_and_probed()
        result = activate_shared(migration)
        self.assertTrue((self.fixture.shared_root / 'context-os/VERSION').exists())
        self.assertEqual(inventory_tree(self.fixture.machines_root), machine_before)
        self.assertEqual(Path(result['rollback_root']).parent, self.fixture.container_root.resolve())
        restored = rollback_shared(migration)
        self.assertTrue(restored['ok'])
        self.assertEqual(
            (self.fixture.shared_root / 'CLAUDE.md').read_text(),
            self.fixture.original_claude,
        )

    def test_activate_shared_restores_old_shared_on_second_rename_failure(self):
        migration = self.reviewed_and_probed()
        with fail_prepared_stage_rename():
            with self.assertRaises(OSError):
                activate_shared(migration)
        self.assertEqual(
            (self.fixture.shared_root / 'CLAUDE.md').read_text(),
            self.fixture.original_claude,
        )

    def test_activation_requires_rollback_probe(self):
        migration = self.prepare_and_build()
        mark_semantic_review(migration.paths, 'test-suite')
        with self.assertRaisesRegex(RuntimeError, 'rollback probe evidence missing'):
            activate_shared(migration)

    def test_activation_rejects_shared_source_change_after_staging(self):
        migration = self.reviewed_and_probed()
        (self.fixture.shared_root / 'CLAUDE.md').write_text('changed after staging')
        with self.assertRaisesRegex(RuntimeError, 'shared source changed after staging'):
            activate_shared(migration)


if __name__ == '__main__':
    unittest.main()
