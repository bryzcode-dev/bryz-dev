import tempfile
import unittest
from pathlib import Path
from unittest import mock

from context_os.migrate import MigrationPaths, activate_verified_stage
from context_os.rollback import rollback


class ActivationTests(unittest.TestCase):
    def test_activate_and_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            active = base / '.claude'
            active.mkdir(); (active / 'old.txt').write_text('old')
            stage = base / 'stage'; stage.mkdir(); (stage / 'new.txt').write_text('new')
            backup = base / 'backup'; backup.mkdir(); (backup / 'old.txt').write_text('old')
            rollback_dir = base / 'rollback'
            (stage / 'context-os' / 'migration').mkdir(parents=True)
            (stage / 'context-os' / 'migration' / 'semantic-review.json').write_text('{"status":"complete"}')
            paths = MigrationPaths('m1', active, base, backup, stage, rollback_dir)
            result = activate_verified_stage(paths)
            self.assertTrue((active / 'new.txt').exists())
            self.assertTrue(rollback_dir.exists())
            rollback(active, rollback_dir)
            self.assertTrue((active / 'old.txt').exists())

    def test_activate_restores_old_root_when_stage_rename_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            active = base / '.claude'; active.mkdir(); (active / 'old.txt').write_text('old')
            stage = base / 'stage'; stage.mkdir(); (stage / 'new.txt').write_text('new')
            backup = base / 'backup'; backup.mkdir()
            rollback_dir = base / 'rollback'
            (stage / 'context-os' / 'migration').mkdir(parents=True)
            (stage / 'context-os' / 'migration' / 'semantic-review.json').write_text('{"status":"complete"}')
            paths = MigrationPaths('m1', active, base, backup, stage, rollback_dir)
            real_rename = Path.rename
            calls = {'n': 0}
            def fail_second(self, target):
                calls['n'] += 1
                if calls['n'] == 2:
                    raise OSError('simulated')
                return real_rename(self, target)
            with mock.patch('pathlib.Path.rename', new=fail_second):
                with self.assertRaises(OSError):
                    activate_verified_stage(paths)
            self.assertTrue((active / 'old.txt').exists())

    def test_activate_rejects_concurrent_activation_lock(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            active = base / '.claude'; active.mkdir(); (active / 'old.txt').write_text('old')
            stage = base / 'stage'; stage.mkdir(); (stage / 'new.txt').write_text('new')
            backup = base / 'backup'; backup.mkdir()
            rollback_dir = base / 'rollback'
            (stage / 'context-os/migration').mkdir(parents=True)
            (stage / 'context-os/migration/semantic-review.json').write_text('{"status":"complete"}')
            (base / 'activation.lock').write_text('{"pid":123}')
            paths = MigrationPaths('m1', active, base, backup, stage, rollback_dir)
            with self.assertRaisesRegex(RuntimeError, 'activation already in progress'):
                activate_verified_stage(paths)
            self.assertTrue((active / 'old.txt').exists())
            self.assertFalse(rollback_dir.exists())

    def test_activate_verifies_prepared_copy_before_swap(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            active = base / '.claude'; active.mkdir(); (active / 'old.txt').write_text('old')
            stage = base / 'stage'; stage.mkdir(); (stage / 'new.txt').write_text('new')
            backup = base / 'backup'; backup.mkdir()
            rollback_dir = base / 'rollback'
            (stage / 'context-os/migration').mkdir(parents=True)
            (stage / 'context-os/migration/semantic-review.json').write_text('{"status":"complete"}')
            paths = MigrationPaths('m1', active, base, backup, stage, rollback_dir)
            from context_os.inventory import inventory_tree
            def incomplete_inventory(path):
                rows = inventory_tree(path)
                if Path(path).name == '.context-os-stage-m1':
                    return [row for row in rows if row['path'] != 'new.txt']
                return rows
            with mock.patch('context_os.migrate.inventory_tree', side_effect=incomplete_inventory):
                with self.assertRaisesRegex(RuntimeError, 'prepared stage verification failed'):
                    activate_verified_stage(paths)
            self.assertTrue((active / 'old.txt').exists())
            self.assertFalse(rollback_dir.exists())
            self.assertFalse((base / 'activation.lock').exists())
