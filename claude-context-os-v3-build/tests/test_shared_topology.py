import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.shared_nas_fixture import MACHINE_IDS, make_three_machine_fixture
from context_os.topology import (
    detect_shared_nas,
    inventory_facade,
    validate_facade,
    write_topology_manifest,
)


class SharedNasTopologyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.fixture = make_three_machine_fixture(self.base)

    def tearDown(self):
        self.tempdir.cleanup()

    def detect(self):
        return detect_shared_nas(
            self.fixture.container_root,
            'mac-mini-m4',
            MACHINE_IDS[1:],
            self.fixture.facade_root,
        )

    def test_detects_container_shared_and_three_machine_roots(self):
        found = self.detect()
        self.assertEqual(found.layout, 'shared-nas-v1')
        self.assertEqual(found.logical_root, (self.fixture.container_root / 'shared').resolve())
        self.assertEqual(found.primary_machine_root, self.fixture.primary_machine_root.resolve())

    def test_rejects_missing_machine_root(self):
        shutil.rmtree(self.fixture.machines_root / 'bryan-mac-neo')
        with self.assertRaisesRegex(RuntimeError, 'missing machine root: bryan-mac-neo'):
            self.detect()

    def test_classifies_shared_machine_and_local_facade_entries(self):
        rows = inventory_facade(self.fixture.facade_root, self.detect())
        by_name = {row['name']: row for row in rows}
        self.assertEqual(by_name['CLAUDE.md']['link_class'], 'shared')
        self.assertEqual(by_name['projects']['link_class'], 'machine')
        self.assertEqual(by_name['settings.local.json']['link_class'], 'local')

    def test_rejects_facade_link_outside_topology(self):
        (self.fixture.facade_root / 'projects').unlink()
        (self.fixture.facade_root / 'projects').symlink_to(self.base / 'outside')
        with self.assertRaisesRegex(RuntimeError, 'facade link escapes topology: projects'):
            validate_facade(self.fixture.facade_root, self.detect())

    def test_writes_round_trippable_manifest(self):
        output = self.base / 'topology.json'
        write_topology_manifest(output, self.detect())
        data = json.loads(output.read_text())
        self.assertEqual(data['layout'], 'shared-nas-v1')
        self.assertEqual(data['primary_machine_id'], 'mac-mini-m4')


if __name__ == '__main__':
    unittest.main()
