from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MACHINE_IDS = ('mac-mini-m4', 'bryans-macbook-pro', 'bryan-mac-neo')


@dataclass
class ThreeMachineFixture:
    base: Path
    container_root: Path
    shared_root: Path
    machines_root: Path
    facade_root: Path
    original_claude: str

    @property
    def primary_machine_root(self) -> Path:
        return self.machines_root / 'mac-mini-m4'

    @property
    def topology(self):
        from context_os.topology import detect_shared_nas
        return detect_shared_nas(
            self.container_root,
            'mac-mini-m4',
            MACHINE_IDS[1:],
            self.facade_root,
        )


def make_three_machine_fixture(base: Path) -> ThreeMachineFixture:
    container = base / 'BryzConfig' / 'Claude'
    shared = container / 'shared'
    machines = container / 'machines'
    facade = base / 'home' / '.claude'
    shared.mkdir(parents=True)
    facade.mkdir(parents=True)
    original = '# Existing shared instructions\n\nPreserve current behavior.\n'
    (shared / 'CLAUDE.md').write_text(original, encoding='utf-8')
    (shared / 'settings.json').write_text(
        json.dumps({'theme': 'dark', 'hooks': {}}), encoding='utf-8'
    )
    for name in ('agents', 'plugins', 'reference', 'skills'):
        (shared / name).mkdir()
    for machine_id in MACHINE_IDS:
        machine = machines / machine_id
        for name in ('projects', 'tasks', 'sessions', 'cache'):
            (machine / name).mkdir(parents=True, exist_ok=True)
        (machine / 'history.jsonl').write_text(
            json.dumps({'machine': machine_id}) + '\n', encoding='utf-8'
        )
    for name in ('CLAUDE.md', 'settings.json', 'agents', 'plugins', 'skills'):
        (facade / name).symlink_to(shared / name)
    for name in ('projects', 'tasks'):
        (facade / name).symlink_to(machines / 'mac-mini-m4' / name)
    (facade / 'settings.local.json').write_text(
        json.dumps({'permissions': {'allow': []}}), encoding='utf-8'
    )
    return ThreeMachineFixture(base, container, shared, machines, facade, original)


def make_secondary_facade(fixture: ThreeMachineFixture, machine_id: str) -> Path:
    facade = fixture.base / f'{machine_id}-home' / '.claude'
    facade.mkdir(parents=True, exist_ok=True)
    for name in ('CLAUDE.md', 'settings.json', 'agents', 'plugins', 'skills'):
        (facade / name).symlink_to(fixture.shared_root / name)
    for name in ('projects', 'tasks'):
        (facade / name).symlink_to(fixture.machines_root / machine_id / name)
    return facade


class SharedNasTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.fixture = make_three_machine_fixture(self.base)
        self.container = self.fixture.container_root
        self.facade = self.fixture.facade_root
        self.workspace = self.base / 'workspace'
        self.topology = self.fixture.topology
        self.machine_root = self.fixture.primary_machine_root
        self.original_claude = self.fixture.original_claude
        self.other_machine_facade = self.base / 'other-home' / '.claude'

    def tearDown(self):
        self.tempdir.cleanup()


def run_cli(*args: str, env: dict | None = None):
    child_env = os.environ.copy()
    child_env.update(env or {})
    return subprocess.run(
        ['python3', str(ROOT / 'contextctl.py'), *args],
        text=True,
        capture_output=True,
        cwd=ROOT,
        env=child_env,
    )


@contextmanager
def fail_prepared_stage_rename():
    real = Path.rename
    calls = {'count': 0}

    def fail_second(path, target):
        calls['count'] += 1
        if calls['count'] == 2:
            raise OSError('simulated prepared-stage rename failure')
        return real(path, target)

    with mock.patch('pathlib.Path.rename', new=fail_second):
        yield


@contextmanager
def fail_symlink_creation(name: str):
    real = Path.symlink_to

    def fail_named(path, target, *args, **kwargs):
        if path.name == name:
            raise OSError('simulated symlink failure: ' + name)
        return real(path, target, *args, **kwargs)

    with mock.patch('pathlib.Path.symlink_to', new=fail_named):
        yield
