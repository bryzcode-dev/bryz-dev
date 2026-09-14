from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import expand_path_template
from .inventory import inventory_tree
from .topology import SharedNasTopology, validate_facade
from .util import read_json, write_json


PRIMARY_LINKS = ('context-os', 'commands', 'rules')
PROFILE_NAME = 'context-os-machine.json'


def _is_within(path: Path, root: Path) -> bool:
    path = path.resolve(strict=False); root = root.resolve(strict=False)
    return path == root or root in path.parents

def _is_path_within(path: Path, root: Path) -> bool:
    path = path.absolute(); root = root.absolute()
    return path == root or root in path.parents


def _profile(topology: SharedNasTopology, machine_id: str, facade: Path, runtime: Path) -> dict:
    return {
        'version': '3.0.1',
        'layout': topology.layout,
        'machine_id': machine_id,
        'container_root': str(topology.container_root),
        'shared_root': str(topology.logical_root),
        'machine_root': str(topology.machines_root / machine_id),
        'facade_root': str(facade),
        'runtime_root': str(runtime),
    }


def plan_machine_enrollment(
    topology: SharedNasTopology,
    machine_id: str,
    facade_root: Path,
    workspace: Path,
    runtime_root: Path | None = None,
) -> dict:
    if machine_id not in topology.machine_ids:
        raise RuntimeError(f'unknown machine ID: {machine_id}')
    facade = Path(facade_root).expanduser().resolve()
    validate_facade(facade, topology)
    runtime = (
        Path(runtime_root).expanduser().resolve()
        if runtime_root is not None
        else expand_path_template(topology.runtime_template)
    )
    if _is_within(runtime, topology.container_root):
        raise RuntimeError(f'runtime path must be local: {runtime}')
    work = Path(workspace).expanduser().resolve(); work.mkdir(parents=True, exist_ok=True)
    actions = []; errors = []
    for name in PRIMARY_LINKS:
        path = facade / name; target = topology.logical_root / name
        if path.is_symlink():
            if path.resolve(strict=False) != target.resolve(strict=False):
                errors.append(f'unexpected existing path: {path}')
        elif path.exists():
            errors.append(f'unexpected existing path: {path}')
        else:
            actions.append({
                'operation': 'symlink', 'path': str(path), 'target': str(target),
                'precondition': 'absent',
            })
    profile_path = facade / PROFILE_NAME
    profile = _profile(topology, machine_id, facade, runtime)
    if profile_path.exists() or profile_path.is_symlink():
        try:
            if profile_path.is_symlink() or json.loads(profile_path.read_text()) != profile:
                errors.append(f'unexpected existing path: {profile_path}')
        except Exception:
            errors.append(f'unexpected existing path: {profile_path}')
    else:
        actions.append({
            'operation': 'write-json', 'path': str(profile_path),
            'content': profile, 'precondition': 'absent',
        })
    plan = {
        'plan_id': 'ENROLL-' + uuid.uuid4().hex[:10].upper(),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'machine_id': machine_id,
        'facade_root': str(facade),
        'shared_root': str(topology.logical_root),
        'machine_root': str(topology.machines_root / machine_id),
        'container_root': str(topology.container_root),
        'runtime_root': str(runtime),
        'status': 'blocked' if errors else 'ready',
        'errors': errors,
        'actions': actions,
        'facade_before': inventory_tree(facade),
        'workspace': str(work),
    }
    plan_path = work / f'machine-enrollment-{machine_id}.json'
    plan['plan_path'] = str(plan_path)
    write_json(plan_path, plan)
    return plan


def _check_preconditions(plan: dict) -> None:
    for action in plan['actions']:
        path = Path(action['path'])
        if action['precondition'] == 'absent' and (path.exists() or path.is_symlink()):
            raise RuntimeError(f'precondition changed: {path}')
        if action['operation'] == 'symlink' and not Path(action['target']).exists():
            raise RuntimeError(f'enrollment target missing: {action["target"]}')


def apply_machine_enrollment(plan: dict) -> dict:
    if plan.get('status') != 'ready':
        raise RuntimeError('machine enrollment plan is not ready')
    _check_preconditions(plan)
    facade = Path(plan['facade_root']).resolve()
    runtime = Path(plan['runtime_root']).resolve()
    container = Path(plan['container_root']).resolve()
    if _is_within(runtime, container):
        raise RuntimeError(f'runtime path must be local: {runtime}')
    manifest_path = Path(plan['workspace']) / f'enrollment-transaction-{plan["plan_id"]}.json'
    runtime_existed = runtime.exists()
    manifest = {
        **plan,
        'status': 'applying',
        'manifest': str(manifest_path),
        'created_paths': [],
        'runtime_created': not runtime_existed,
    }
    write_json(manifest_path, manifest)
    try:
        for action in plan['actions']:
            path = Path(action['path'])
            if not _is_path_within(path, facade):
                raise RuntimeError(f'enrollment path escapes facade: {path}')
            if action['operation'] == 'symlink':
                path.symlink_to(Path(action['target']))
            elif action['operation'] == 'write-json':
                write_json(path, action['content'])
            else:
                raise RuntimeError(f'unknown enrollment operation: {action["operation"]}')
            manifest['created_paths'].append(str(path))
            write_json(manifest_path, manifest)
        runtime.mkdir(parents=True, exist_ok=True)
        manifest['status'] = 'complete'
        manifest['completed_at'] = datetime.now(timezone.utc).isoformat()
        write_json(manifest_path, manifest)
    except Exception:
        for value in reversed(manifest['created_paths']):
            path = Path(value)
            if path.is_symlink() or path.is_file(): path.unlink()
        if not runtime_existed and runtime.exists() and not any(runtime.iterdir()):
            runtime.rmdir()
        manifest['status'] = 'rolled_back_on_failure'
        write_json(manifest_path, manifest)
        raise
    return {
        'ok': True,
        'manifest': str(manifest_path),
        'runtime_root': str(runtime),
        'machine_id': plan['machine_id'],
    }


def verify_machine_enrollment(manifest_path: Path) -> dict:
    manifest = read_json(manifest_path, {})
    errors = []
    if manifest.get('status') != 'complete': errors.append('enrollment transaction incomplete')
    for action in manifest.get('actions', []):
        path = Path(action['path'])
        if action['operation'] == 'symlink':
            if not path.is_symlink(): errors.append(f'missing enrollment symlink: {path}')
            elif path.resolve(strict=False) != Path(action['target']).resolve(strict=False):
                errors.append(f'enrollment symlink target mismatch: {path}')
        elif action['operation'] == 'write-json':
            if read_json(path, None) != action['content']:
                errors.append(f'machine profile mismatch: {path}')
    runtime = Path(manifest.get('runtime_root', '/'))
    if not runtime.is_dir(): errors.append(f'local runtime missing: {runtime}')
    if _is_within(runtime, Path(manifest.get('container_root', '/'))):
        errors.append(f'runtime path must be local: {runtime}')
    return {'ok': not errors, 'errors': errors, 'machine_id': manifest.get('machine_id')}


def rollback_machine_enrollment(manifest_path: Path) -> dict:
    manifest_path = Path(manifest_path).resolve()
    manifest = read_json(manifest_path, {})
    facade = Path(manifest['facade_root']).resolve()
    for value in reversed(manifest.get('created_paths', [])):
        path = Path(value)
        if not _is_path_within(path, facade):
            raise RuntimeError(f'rollback path escapes facade: {path}')
        if path.is_symlink() or path.is_file(): path.unlink()
    runtime = Path(manifest['runtime_root']).resolve()
    runtime_archive = None
    if manifest.get('runtime_created') and runtime.exists():
        if any(runtime.iterdir()):
            runtime_archive = manifest_path.parent / f'rolled-back-runtime-{manifest["plan_id"]}'
            runtime.rename(runtime_archive)
        else:
            runtime.rmdir()
    current = inventory_tree(facade)
    if current != manifest.get('facade_before', []):
        raise RuntimeError('facade rollback verification failed')
    manifest['status'] = 'rolled_back'
    manifest['rolled_back_at'] = datetime.now(timezone.utc).isoformat()
    manifest['runtime_archive'] = str(runtime_archive) if runtime_archive else None
    write_json(manifest_path, manifest)
    return {'ok': True, 'manifest': str(manifest_path), 'runtime_archive': manifest['runtime_archive']}
