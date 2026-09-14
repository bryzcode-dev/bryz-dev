from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config, save_config
from .enrollment import plan_machine_enrollment
from .migrate import (
    MigrationPaths,
    activate_verified_stage,
    build_stage,
    prepare_migration,
    regenerate_managed_manifest,
    semantic_review_complete,
)
from .rollback import rollback
from .settings import (
    apply_security_permissions,
    merge_context_os_settings,
    portable_hook_paths,
)
from .topology import SharedNasTopology, validate_facade, write_topology_manifest
from .util import read_json, write_json
from .verify import VerificationReport, verify_stage


@dataclass
class SharedMigration:
    topology: SharedNasTopology
    paths: MigrationPaths
    topology_manifest: Path
    enrollment_plan: Path


def prepare_shared_migration(
    topology: SharedNasTopology,
    workspace: Path,
) -> SharedMigration:
    validate_facade(topology.facade_root, topology)
    paths = prepare_migration(topology.logical_root, workspace)
    manifest_path = paths.workspace / 'topology-guard.json'
    guard = write_topology_manifest(manifest_path, topology)
    guard['machine_roots'] = {
        machine_id: str((topology.machines_root / machine_id).resolve())
        for machine_id in topology.machine_ids
    }
    write_json(manifest_path, guard)
    return SharedMigration(
        topology,
        paths,
        manifest_path,
        paths.workspace / 'primary-enrollment-plan.json',
    )


def build_shared_stage(
    migration: SharedMigration,
    template_root: Path,
    package_root: Path,
) -> dict:
    report = build_stage(
        migration.paths,
        template_root,
        package_root=package_root,
        profile='home',
    )
    stage = migration.paths.stage
    topology = migration.topology
    config_path = stage / 'context-os/config/context-os.json'
    config = load_config(config_path)
    config['profile'] = 'home'
    config['paths'] = {
        'claude_root': str(topology.logical_root),
        'container_root': str(topology.container_root),
        'runtime_root': topology.runtime_template,
        'storage_kind': 'network_or_removable',
    }
    config['topology'] = {
        'layout': topology.layout,
        'machine_profile': '~/.claude/context-os-machine.json',
    }
    save_config(config_path, config)
    write_topology_manifest(stage / 'context-os/config/topology.json', topology)

    existing = json.loads((topology.logical_root / 'settings.json').read_text(encoding='utf-8'))
    settings = merge_context_os_settings(existing, portable_hook_paths())
    settings = apply_security_permissions(settings, '$HOME/.claude/context-os')
    write_json(stage / 'settings.json', settings)
    regenerate_managed_manifest(stage, template_root)
    plan = plan_machine_enrollment(
        topology,
        topology.primary_machine_id,
        topology.facade_root,
        migration.paths.workspace,
    )
    Path(plan['plan_path']).unlink()
    plan['plan_path'] = str(migration.enrollment_plan)
    write_json(migration.enrollment_plan, plan)
    return report


def verify_shared_stage(
    migration: SharedMigration,
    require_source_unchanged: bool = False,
) -> VerificationReport:
    base = verify_stage(migration.paths)
    errors = list(base.errors)
    warnings = list(base.warnings)
    topology = migration.topology
    if not migration.topology_manifest.exists():
        errors.append('topology guard manifest missing')
    enrollment = read_json(migration.enrollment_plan, {})
    if enrollment.get('status') != 'ready':
        errors.append('primary enrollment plan is not ready')
    for machine_id in topology.machine_ids:
        path = topology.machines_root / machine_id
        if not path.is_dir():
            errors.append(f'missing machine root: {path}')
    try:
        validate_facade(topology.facade_root, topology)
    except Exception as ex:
        errors.append(str(ex))
    config = read_json(
        migration.paths.stage / 'context-os/config/context-os.json', {}
    )
    runtime_value = str(config.get('paths', {}).get('runtime_root', ''))
    if runtime_value.startswith('/Volumes/') or str(topology.container_root) in runtime_value:
        errors.append(f'runtime path must be local: {runtime_value}')
    if runtime_value != topology.runtime_template:
        errors.append(f'unexpected runtime template: {runtime_value}')
    staged_topology = read_json(
        migration.paths.stage / 'context-os/config/topology.json', {}
    )
    if staged_topology.get('layout') != topology.layout:
        errors.append('staged topology layout mismatch')
    report = read_json(
        migration.paths.stage / 'context-os/migration/migration-report.json',
        {'mappings': []},
    )
    source_names = {row.get('source') for row in report.get('mappings', [])}
    for forbidden in ('machines', 'shared'):
        if forbidden in source_names:
            errors.append(f'container topology incorrectly migrated as native item: {forbidden}')
    if require_source_unchanged:
        from .inventory import inventory_tree
        frozen = read_json(migration.paths.workspace / 'source-manifest.json', [])
        if inventory_tree(topology.logical_root) != frozen:
            errors.append('shared source changed after staging')
    return VerificationReport(not errors, errors, warnings)


def probe_shared_rollback(migration: SharedMigration) -> dict:
    container = migration.topology.container_root
    base = Path(tempfile.mkdtemp(prefix='.context-os-rollback-probe-', dir=str(container)))
    evidence_path = migration.paths.workspace / 'rollback-probe.json'
    try:
        active = base / 'active'; previous = base / 'rollback'
        active.mkdir(); previous.mkdir()
        (active / 'v3.txt').write_text('v3', encoding='utf-8')
        (previous / 'legacy.txt').write_text('legacy', encoding='utf-8')
        result = rollback(active, previous)
        displaced = Path(result['displaced_context_os'])
        if (active / 'legacy.txt').read_text(encoding='utf-8') != 'legacy':
            raise RuntimeError('rollback probe did not restore legacy content')
        if (displaced / 'v3.txt').read_text(encoding='utf-8') != 'v3':
            raise RuntimeError('rollback probe did not preserve displaced content')
        evidence = {
            'ok': True,
            'tested_at': datetime.now(timezone.utc).isoformat(),
            'container_root': str(container),
            'probe_removed': True,
        }
        shutil.rmtree(base)
        write_json(evidence_path, evidence)
        return evidence
    except Exception as ex:
        write_json(evidence_path, {
            'ok': False,
            'tested_at': datetime.now(timezone.utc).isoformat(),
            'container_root': str(container),
            'probe_path': str(base),
            'error': str(ex),
        })
        raise


def activate_shared(migration: SharedMigration) -> dict:
    verification = verify_shared_stage(migration, require_source_unchanged=True)
    if not verification.ok:
        raise RuntimeError('; '.join(verification.errors))
    if not semantic_review_complete(migration.paths):
        raise RuntimeError('Semantic adoption review is still pending')
    probe = read_json(migration.paths.workspace / 'rollback-probe.json', {})
    if not probe.get('ok') or probe.get('container_root') != str(migration.topology.container_root):
        raise RuntimeError('rollback probe evidence missing or invalid')
    enrollment = read_json(migration.enrollment_plan, {})
    if enrollment.get('status') != 'ready':
        raise RuntimeError('primary enrollment plan is not ready')
    if migration.paths.source != migration.topology.logical_root:
        raise RuntimeError('shared activation source is not the logical shared root')
    return activate_verified_stage(migration.paths)


def rollback_shared(migration: SharedMigration) -> dict:
    result = rollback(migration.topology.logical_root, migration.paths.rollback_root)
    from .inventory import inventory_tree
    restored = inventory_tree(migration.topology.logical_root)
    frozen = read_json(migration.paths.workspace / 'source-manifest.json', [])
    if restored != frozen:
        raise RuntimeError('restored shared root does not match frozen source manifest')
    return {'ok': True, **result}
