import json
import tempfile
import unittest
from pathlib import Path

from context_os.migrate import mark_semantic_review
from context_os.shared_migrate import (
    activate_shared, build_shared_stage, prepare_shared_migration,
    probe_shared_rollback,
)
from tests.shared_nas_fixture import ROOT
from tests.shared_nas_fixture import make_three_machine_fixture, run_cli


class SharedCliTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.fixture = make_three_machine_fixture(self.base)
        self.workspace = self.base / 'work'

    def tearDown(self):
        self.tempdir.cleanup()

    def topology_args(self):
        return (
            '--root', str(self.fixture.container_root),
            '--primary-machine', 'mac-mini-m4',
            '--secondary-machine', 'bryans-macbook-pro',
            '--secondary-machine', 'bryan-mac-neo',
            '--facade', str(self.fixture.facade_root),
        )

    def test_adopt_shared_defaults_to_stage_only(self):
        result = run_cli(
            'adopt-shared', *self.topology_args(),
            '--workspace', str(self.workspace),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload['verification']['ok'])
        self.assertNotIn('activation', payload)
        self.assertEqual(
            (self.fixture.shared_root / 'CLAUDE.md').read_text(),
            self.fixture.original_claude,
        )
        self.assertTrue(Path(payload['workspace']).joinpath('topology-guard.json').exists())

    def test_enroll_machine_is_dry_run_without_apply(self):
        result = run_cli(
            'enroll-machine', *self.topology_args(),
            '--machine-id', 'mac-mini-m4',
            '--workspace', str(self.workspace),
            '--runtime', str(self.base / 'runtime'),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['status'], 'ready')
        self.assertFalse((self.fixture.facade_root / 'context-os').exists())

    def test_shared_followup_commands_require_exact_migration_workspace(self):
        adopted = run_cli(
            'adopt-shared', *self.topology_args(), '--workspace', str(self.workspace)
        )
        self.assertEqual(adopted.returncode, 0, adopted.stderr)
        exact = Path(json.loads(adopted.stdout)['workspace'])
        rejected = run_cli(
            'verify-shared', *self.topology_args(), '--workspace', str(self.workspace)
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('exact migration workspace', rejected.stderr)
        verified = run_cli(
            'verify-shared', *self.topology_args(), '--workspace', str(exact)
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)

    def test_ea_context_reports_local_machine_profile(self):
        adopted = run_cli(
            'adopt-shared', *self.topology_args(), '--workspace', str(self.workspace)
        )
        self.assertEqual(adopted.returncode, 0, adopted.stderr)
        stage = Path(json.loads(adopted.stdout)['stage'])
        profile = self.base / 'context-os-machine.json'
        profile.write_text(json.dumps({
            'machine_id': 'mac-mini-m4',
            'shared_root': str(self.fixture.shared_root),
            'machine_root': str(self.fixture.primary_machine_root),
        }))
        result = run_cli(
            'assistant-context', '--root', str(stage), '--cwd', str(self.base),
            '--query', 'status', env={
                'HOME': str(self.base / 'home'),
                'CONTEXT_OS_MACHINE_PROFILE': str(profile),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['machine']['machine_id'], 'mac-mini-m4')

    def test_rollback_shared_recovers_incomplete_active_root(self):
        migration = prepare_shared_migration(self.fixture.topology, self.workspace)
        build_shared_stage(migration, ROOT / 'template_root', ROOT)
        mark_semantic_review(migration.paths, 'test-suite')
        probe_shared_rollback(migration)
        activate_shared(migration)
        (self.fixture.shared_root / 'settings.json').unlink()
        result = run_cli(
            'rollback-shared', *self.topology_args(),
            '--workspace', str(migration.paths.workspace),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.fixture.shared_root / 'CLAUDE.md').read_text(),
            self.fixture.original_claude,
        )


if __name__ == '__main__':
    unittest.main()
