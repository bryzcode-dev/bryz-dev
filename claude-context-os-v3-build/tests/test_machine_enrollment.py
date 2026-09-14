import tempfile
import unittest
from pathlib import Path

from context_os.enrollment import (
    apply_machine_enrollment,
    plan_machine_enrollment,
    rollback_machine_enrollment,
    verify_machine_enrollment,
)
from context_os.inventory import inventory_tree
from tests.shared_nas_fixture import make_three_machine_fixture


class MachineEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.fixture = make_three_machine_fixture(self.base)
        self.runtime = self.base / 'runtime'
        for name in ('context-os', 'commands', 'rules'):
            (self.fixture.shared_root / name).mkdir()

    def tearDown(self):
        self.tempdir.cleanup()

    def plan(self):
        return plan_machine_enrollment(
            self.fixture.topology,
            'mac-mini-m4',
            self.fixture.facade_root,
            self.base / 'workspace',
            runtime_root=self.runtime,
        )

    def test_primary_plan_preserves_existing_facade_and_adds_only_v3_entries(self):
        plan = self.plan()
        self.assertEqual(plan['status'], 'ready')
        self.assertEqual(
            {Path(a['path']).name for a in plan['actions']},
            {'context-os', 'commands', 'rules', 'context-os-machine.json'},
        )
        self.assertTrue((self.fixture.facade_root / 'settings.local.json').exists())

    def test_primary_plan_blocks_unexpected_context_os_file(self):
        (self.fixture.facade_root / 'context-os').write_text('collision')
        plan = self.plan()
        self.assertEqual(plan['status'], 'blocked')
        self.assertTrue(any('unexpected existing path' in e for e in plan['errors']))

    def test_apply_then_rollback_changes_only_manifest_paths(self):
        before = inventory_tree(self.fixture.facade_root)
        result = apply_machine_enrollment(self.plan())
        self.assertTrue((self.fixture.facade_root / 'context-os').is_symlink())
        self.assertTrue(verify_machine_enrollment(Path(result['manifest']))['ok'])
        self.assertFalse(str(Path(result['runtime_root'])).startswith(
            str(self.fixture.container_root.resolve())
        ))
        rollback_machine_enrollment(Path(result['manifest']))
        self.assertEqual(inventory_tree(self.fixture.facade_root), before)

    def test_apply_refuses_changed_precondition(self):
        plan = self.plan()
        (self.fixture.facade_root / 'rules').write_text('appeared after planning')
        with self.assertRaisesRegex(RuntimeError, 'precondition changed: .*rules'):
            apply_machine_enrollment(plan)


if __name__ == '__main__':
    unittest.main()
