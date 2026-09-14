from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .util import write_json


SHARED_LINK_NAMES = frozenset({'CLAUDE.md', 'settings.json', 'agents', 'plugins', 'skills'})
MACHINE_LINK_NAMES = frozenset({
    '.last-cleanup', 'backups', 'cache', 'history.jsonl',
    'mcp-needs-auth-cache.json', 'projects', 'session-env', 'sessions',
    'shell-snapshots', 'tasks',
})


@dataclass(frozen=True)
class SharedNasTopology:
    layout: str
    container_root: Path
    logical_root: Path
    machines_root: Path
    primary_machine_id: str
    secondary_machine_ids: tuple[str, ...]
    facade_root: Path
    runtime_template: str = '~/Library/Application Support/ClaudeContextOS/home'

    @property
    def primary_machine_root(self) -> Path:
        return self.machines_root / self.primary_machine_id

    @property
    def machine_ids(self) -> tuple[str, ...]:
        return (self.primary_machine_id, *self.secondary_machine_ids)

    def as_json(self) -> dict:
        return {
            'layout': self.layout,
            'container_root': str(self.container_root),
            'logical_root': str(self.logical_root),
            'machines_root': str(self.machines_root),
            'primary_machine_id': self.primary_machine_id,
            'secondary_machine_ids': list(self.secondary_machine_ids),
            'facade_root': str(self.facade_root),
            'runtime_template': self.runtime_template,
            'shared_link_names': sorted(SHARED_LINK_NAMES),
            'machine_link_names': sorted(MACHINE_LINK_NAMES),
        }


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def detect_shared_nas(
    container_root: Path,
    primary_machine_id: str,
    secondary_machine_ids: tuple[str, ...] | list[str],
    facade_root: Path,
    runtime_template: str = '~/Library/Application Support/ClaudeContextOS/home',
) -> SharedNasTopology:
    container = Path(container_root).expanduser().resolve()
    shared = container / 'shared'
    machines = container / 'machines'
    facade = Path(facade_root).expanduser().resolve()
    if not shared.is_dir():
        raise RuntimeError(f'missing shared root: {shared}')
    if not machines.is_dir():
        raise RuntimeError(f'missing machines root: {machines}')
    if not (shared / 'CLAUDE.md').is_file():
        raise RuntimeError(f'missing shared CLAUDE.md: {shared / "CLAUDE.md"}')
    if not (shared / 'settings.json').is_file():
        raise RuntimeError(f'missing shared settings.json: {shared / "settings.json"}')
    machine_ids = (primary_machine_id, *tuple(secondary_machine_ids))
    if len(set(machine_ids)) != len(machine_ids):
        raise RuntimeError('machine IDs must be unique')
    for machine_id in machine_ids:
        if not (machines / machine_id).is_dir():
            raise RuntimeError(f'missing machine root: {machine_id}')
    if not facade.is_dir():
        raise RuntimeError(f'missing facade root: {facade}')
    return SharedNasTopology(
        'shared-nas-v1', container, shared, machines, primary_machine_id,
        tuple(secondary_machine_ids), facade, runtime_template,
    )


def inventory_facade(facade_root: Path, topology: SharedNasTopology) -> list[dict]:
    facade = Path(facade_root).expanduser().resolve()
    rows = []
    for path in sorted(facade.iterdir(), key=lambda p: p.name):
        row = {'name': path.name, 'path': str(path)}
        if path.is_symlink():
            target_text = os.readlink(path)
            target = path.resolve(strict=False)
            if _is_within(target, topology.logical_root):
                link_class = 'shared'
            elif _is_within(target, topology.machines_root):
                link_class = 'machine'
            else:
                link_class = 'unexpected'
            row.update({
                'type': 'symlink',
                'target': target_text,
                'resolved_target': str(target),
                'link_class': link_class,
            })
        elif path.is_dir():
            row.update({'type': 'dir', 'link_class': 'local'})
        elif path.is_file():
            row.update({'type': 'file', 'link_class': 'local'})
        else:
            row.update({'type': 'other', 'link_class': 'local'})
        rows.append(row)
    return rows


def validate_facade(facade_root: Path, topology: SharedNasTopology) -> list[dict]:
    rows = inventory_facade(facade_root, topology)
    for row in rows:
        if row['link_class'] == 'unexpected':
            raise RuntimeError(f'facade link escapes topology: {row["name"]}')
        if row['link_class'] == 'shared' and row['name'] in SHARED_LINK_NAMES:
            expected = (topology.logical_root / row['name']).resolve(strict=False)
            if Path(row['resolved_target']) != expected:
                raise RuntimeError(f'unexpected shared facade target: {row["name"]}')
        if row['link_class'] == 'machine' and row['name'] in MACHINE_LINK_NAMES:
            expected = (topology.primary_machine_root / row['name']).resolve(strict=False)
            if Path(row['resolved_target']) != expected:
                raise RuntimeError(f'unexpected machine facade target: {row["name"]}')
    return rows


def write_topology_manifest(path: Path, topology: SharedNasTopology) -> dict:
    data = topology.as_json()
    data['facade_inventory'] = validate_facade(topology.facade_root, topology)
    write_json(path, data)
    return data
