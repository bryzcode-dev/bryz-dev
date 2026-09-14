# Shared NAS Primary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt `/Volumes/BryzConfig/Claude/shared` as the authoritative Context OS root and enroll the Mac Mini without modifying any `machines/*` directory during shared migration.

**Architecture:** Add an explicit `shared-nas-v1` topology model, reuse the verified V3 snapshot engine against `shared/` only, and wrap staging/verification/activation with topology guards. Shared configuration uses portable `$HOME`/`~` paths, while a path-scoped Mac Mini enrollment transaction adds only new V3 facade entries and local runtime state.

**Tech Stack:** Python 3 standard library, `unittest`, JSON/Markdown, SQLite FTS5, Claude Code settings/hooks, APFS/SMB filesystem operations.

**Spec:** `docs/superpowers/specs/2026-09-12-shared-nas-topology-design.md`

## Global Constraints

- Do not modify `/Volumes/BryzConfig/Claude` until a new staged migration, semantic review, topology verification, and rollback probes pass.
- Never move, copy into a replacement, rename, or delete any `/Volumes/BryzConfig/Claude/machines/*` directory during shared adoption.
- Preserve all existing shared settings, unrelated hooks, skills, agents, plugins, reference material, and Mac Mini local-only facade entries.
- Keep SQLite, WAL files, hook events, offsets, locks, and transient logs under `~/Library/Application Support/ClaudeContextOS/home` on each Mac.
- Keep runtime code local-only with Python standard-library dependencies.
- Keep existing single-system `adopt`, `verify`, `activate`, and `rollback` behavior compatible.
- Never activate the real shared root in the implementation phase; stop after read-only real-topology comparison and staged verification.
- The package is not a Git repository. Replace commit steps with explicit changed-file and focused-test checkpoints; do not initialize or publish a repository without user authorization.

## File Structure

- Create `context_os/topology.py`: shared-NAS topology model, validation, facade inventory, and JSON serialization.
- Create `context_os/shared_migrate.py`: shared-only preparation, stage configuration, verification, activation, and rollback wrappers.
- Create `context_os/enrollment.py`: path-scoped primary-machine planning, apply, verification, and rollback.
- Modify `context_os/migrate.py`: expose managed-manifest regeneration without changing single-root migration behavior.
- Modify `context_os/config.py`: expand portable runtime templates deterministically.
- Modify `context_os/ops.py`: use the portable runtime resolver.
- Modify `context_os/settings.py`: generate portable hook and CLI commands without setting an invalid literal environment path.
- Modify `template_root/context-os/runtime/hooks/_common.py`: resolve shared topology and local runtime safely; no-op when unenrolled.
- Modify `contextctl.py`: add shared migration and machine-enrollment commands.
- Create `tests/test_shared_topology.py`: topology and facade validation.
- Create `tests/shared_nas_fixture.py`: complete synthetic topology, CLI, ready-state, and failure-injection helpers used by both plans.
- Create `tests/test_shared_migration.py`: shared staging, guards, activation, and rollback.
- Create `tests/test_machine_enrollment.py`: Mac Mini path-scoped enrollment and rollback.
- Create `tests/test_shared_nas_end_to_end.py`: synthetic three-machine topology release gate.
- Modify `README.md`, `ADOPTION_PROTOCOL.md`, `VERIFICATION_REPORT.md`, and `RELEASE_MANIFEST.json`: document only verified behavior and evidence.

---

### Task 0: Create the Shared Test Fixture Contract

**Files:**
- Create: `tests/shared_nas_fixture.py`

**Interfaces:**
- Consumes: a temporary base path and, after their respective tasks, the production topology/migration/enrollment APIs.
- Produces: `ThreeMachineFixture`, `SharedNasTestCase`, `make_three_machine_fixture()`, `prepare_and_build()`, `verified_reviewed_shared_migration()`, `ready_plan()`, `ready_secondary_plan()`, `run_cli()`, `fail_prepared_stage_rename()`, and `fail_symlink_creation()`.

- [ ] **Step 1: Create the deterministic three-machine fixture**

```python
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest import mock
import json, os, subprocess, tempfile, unittest

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
    def container(self): return self.container_root
    @property
    def facade(self): return self.facade_root
    @property
    def primary_machine_root(self): return self.machines_root / 'mac-mini-m4'
    @property
    def machine_root(self): return self.primary_machine_root
    @property
    def topology(self):
        from context_os.topology import detect_shared_nas
        return detect_shared_nas(self.container_root, 'mac-mini-m4',
                                 MACHINE_IDS[1:], self.facade_root)

def make_three_machine_fixture(base: Path) -> ThreeMachineFixture:
    container = base / 'BryzConfig' / 'Claude'
    shared = container / 'shared'
    machines = container / 'machines'
    facade = base / 'home' / '.claude'
    shared.mkdir(parents=True)
    facade.mkdir(parents=True)
    original = '# Existing shared instructions\n\nPreserve current behavior.\n'
    (shared / 'CLAUDE.md').write_text(original, encoding='utf-8')
    (shared / 'settings.json').write_text(json.dumps({'theme':'dark','hooks':{}}))
    for name in ('agents', 'plugins', 'reference', 'skills'):
        (shared / name).mkdir()
    for machine_id in MACHINE_IDS:
        machine = machines / machine_id
        for name in ('projects', 'tasks', 'sessions', 'cache'):
            (machine / name).mkdir(parents=True, exist_ok=True)
        (machine / 'history.jsonl').write_text('{"machine":"%s"}\n' % machine_id)
    for name in ('CLAUDE.md', 'settings.json', 'agents', 'plugins', 'skills'):
        (facade / name).symlink_to(shared / name)
    for name in ('projects', 'tasks'):
        (facade / name).symlink_to(machines / 'mac-mini-m4' / name)
    (facade / 'settings.local.json').write_text('{"permissions":{"allow":[]}}')
    return ThreeMachineFixture(base, container, shared, machines, facade, original)

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
    def tearDown(self): self.tempdir.cleanup()
```

- [ ] **Step 2: Add lazy helpers as their production APIs become available**

```python
def prepare_and_build(fixture, workspace=None):
    from context_os.shared_migrate import prepare_shared_migration, build_shared_stage
    migration = prepare_shared_migration(fixture.topology, workspace or fixture.base/'work')
    build_shared_stage(migration, ROOT/'template_root', ROOT)
    return migration

def verified_reviewed_shared_migration(fixture):
    from context_os.migrate import mark_semantic_review
    from context_os.shared_migrate import probe_shared_rollback
    migration = prepare_and_build(fixture)
    mark_semantic_review(migration.paths, 'test-suite')
    probe_shared_rollback(migration)
    return migration

def ready_plan(fixture):
    from context_os.enrollment import plan_machine_enrollment
    return plan_machine_enrollment(fixture.topology, 'mac-mini-m4',
                                   fixture.facade_root, fixture.base/'enrollment')

def ready_secondary_plan(fixture, machine_id):
    from context_os.enrollment import plan_secondary_reset
    facade = make_secondary_facade(fixture, machine_id)
    return plan_secondary_reset(fixture.topology, machine_id,
                                facade, fixture.base/'secondary')

def make_secondary_facade(fixture, machine_id):
    facade = fixture.base / (machine_id + '-home') / '.claude'
    facade.mkdir(parents=True, exist_ok=True)
    for name in ('CLAUDE.md', 'settings.json', 'agents', 'plugins', 'skills'):
        (facade / name).symlink_to(fixture.shared_root / name)
    for name in ('projects', 'tasks'):
        (facade / name).symlink_to(fixture.machines_root / machine_id / name)
    return facade

def run_cli(*args, env=None):
    child_env = os.environ.copy()
    child_env.update(env or {})
    return subprocess.run(['python3', str(ROOT/'contextctl.py'), *args],
                          text=True, capture_output=True, cwd=ROOT, env=child_env)

@contextmanager
def fail_prepared_stage_rename():
    real = Path.rename; calls = {'count': 0}
    def fail_second(path, target):
        calls['count'] += 1
        if calls['count'] == 2: raise OSError('simulated prepared-stage rename failure')
        return real(path, target)
    with mock.patch('pathlib.Path.rename', new=fail_second): yield

@contextmanager
def fail_symlink_creation(name):
    real = Path.symlink_to
    def fail_named(path, target, *args, **kwargs):
        if path.name == name: raise OSError('simulated symlink failure: ' + name)
        return real(path, target, *args, **kwargs)
    with mock.patch('pathlib.Path.symlink_to', new=fail_named): yield
```

- [ ] **Step 3: Verify the fixture module imports**

Run: `rtk python3 -m unittest tests.shared_nas_fixture -v`

Expected: exit 0 with zero collected tests and no import error.

- [ ] **Step 4: Record the checkpoint**

Record `tests/shared_nas_fixture.py` and its import-gate exit code.

---

### Task 1: Model and Validate the Shared NAS Topology

**Files:**
- Create: `context_os/topology.py`
- Create: `tests/test_shared_topology.py`

**Interfaces:**
- Consumes: filesystem paths and symlink targets.
- Produces: `SharedNasTopology`, `detect_shared_nas()`, `inventory_facade()`, `validate_facade()`, and `write_topology_manifest()`.

- [ ] **Step 1: Write failing topology tests**

```python
class SharedNasTopologyTests(unittest.TestCase):
    def test_detects_container_shared_and_three_machine_roots(self):
        topology = make_three_machine_fixture(Path(self.tempdir.name))
        found = detect_shared_nas(
            topology.container_root,
            primary_machine_id='mac-mini-m4',
            secondary_machine_ids=('bryans-macbook-pro', 'bryan-mac-neo'),
            facade_root=topology.facade_root,
        )
        self.assertEqual(found.layout, 'shared-nas-v1')
        self.assertEqual(found.logical_root, topology.container_root / 'shared')

    def test_rejects_missing_machine_root(self):
        fixture = make_three_machine_fixture(Path(self.tempdir.name))
        shutil.rmtree(fixture.container_root / 'machines' / 'bryan-mac-neo')
        with self.assertRaisesRegex(RuntimeError, 'missing machine root: bryan-mac-neo'):
            detect_shared_nas(fixture.container_root, 'mac-mini-m4',
                              ('bryans-macbook-pro', 'bryan-mac-neo'), fixture.facade_root)

    def test_classifies_shared_machine_and_local_facade_entries(self):
        fixture = make_three_machine_fixture(Path(self.tempdir.name))
        rows = inventory_facade(fixture.facade_root, fixture.topology)
        by_name = {row['name']: row for row in rows}
        self.assertEqual(by_name['CLAUDE.md']['link_class'], 'shared')
        self.assertEqual(by_name['projects']['link_class'], 'machine')
        self.assertEqual(by_name['settings.local.json']['link_class'], 'local')
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run: `rtk python3 -m unittest tests.test_shared_topology -v`

Expected: FAIL because `context_os.topology` does not exist.

- [ ] **Step 3: Implement the topology model and validators**

```python
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
        }
```

`detect_shared_nas()` resolves paths, requires `shared/`, `machines/`, every named machine directory, `shared/CLAUDE.md`, and `shared/settings.json`, and rejects a facade outside the executing user's home. `inventory_facade()` uses `lstat()`/`readlink()` and never follows links while classifying them. `validate_facade()` rejects shared or machine links that escape their approved roots.

- [ ] **Step 4: Run focused topology tests**

Run: `rtk python3 -m unittest tests.test_shared_topology -v`

Expected: all topology tests pass.

- [ ] **Step 5: Record the checkpoint**

Record changed files `context_os/topology.py` and `tests/test_shared_topology.py`, plus the focused test count and exit code. Do not initialize Git.

---

### Task 2: Resolve Portable Per-Machine Runtime and Hook Paths

**Files:**
- Modify: `context_os/config.py`
- Modify: `context_os/ops.py`
- Modify: `context_os/settings.py`
- Modify: `template_root/context-os/runtime/hooks/_common.py`
- Modify: `tests/test_settings.py`
- Modify: `tests/test_hooks.py`

**Interfaces:**
- Consumes: runtime template string, optional home path, topology-aware hook root.
- Produces: `expand_path_template(value, home=None) -> Path`, portable settings commands, and safe hook runtime resolution.

- [ ] **Step 1: Write failing portable-path tests**

```python
def test_expands_runtime_template_for_each_machine_home(self):
    self.assertEqual(
        expand_path_template('~/Library/Application Support/ClaudeContextOS/home', Path('/Users/tester')),
        Path('/Users/tester/Library/Application Support/ClaudeContextOS/home'),
    )

def test_shared_settings_use_portable_facade_hook_commands(self):
    hooks = portable_hook_paths('$HOME/.claude/context-os')
    merged = merge_context_os_settings({'theme': 'dark'}, hooks)
    command = merged['hooks']['SessionStart'][-1]['hooks'][0]['command']
    self.assertEqual(command, 'python3 "$HOME/.claude/context-os/runtime/hooks/session_start.py"')
    self.assertNotIn('CONTEXT_OS_HOME', merged.get('env', {}))

def test_unenrolled_shared_hook_exits_without_writing_to_nas(self):
    result = run_hook('session_start.py', {}, env={
        'HOME': self.tempdir.name,
        'CONTEXT_OS_HOME': '',
    })
    self.assertEqual(result.returncode, 0)
    self.assertFalse(any(Path(self.tempdir.name).rglob('context.db')))
```

- [ ] **Step 2: Run tests and verify failures name the missing resolver/portable behavior**

Run: `rtk python3 -m unittest tests.test_settings tests.test_hooks -v`

Expected: FAIL because `expand_path_template()` and portable hook handling are absent.

- [ ] **Step 3: Implement deterministic template expansion**

```python
def expand_path_template(value: str | Path, home: Path | None = None) -> Path:
    text = str(value)
    base = Path(home) if home is not None else Path.home()
    if text == '~':
        return base.resolve()
    if text.startswith('~/'):
        return (base / text[2:]).resolve()
    return Path(text).expanduser().resolve()
```

Change `runtime_for()` and hook `runtime_root()` to use the resolver. A resolved runtime under `/Volumes/BryzConfig/Claude` raises `RuntimeError('runtime path must be local')` instead of falling back to shared storage.

- [ ] **Step 4: Add portable hook-path construction**

```python
def portable_hook_paths(context_home='$HOME/.claude/context-os'):
    base = context_home.rstrip('/') + '/runtime/hooks'
    return {key: f'{base}/{name}.py' for key, name in HOOK_FILES.items()}
```

Keep `$HOME` inside double quotes so the shell expands it. Do not write the literal `$HOME` value into `CONTEXT_OS_HOME`; hook code resolves its installed file location and local machine profile.

- [ ] **Step 5: Run focused settings and hook tests**

Run: `rtk python3 -m unittest tests.test_settings tests.test_hooks -v`

Expected: all focused tests pass, including the existing idempotency and privacy tests.

- [ ] **Step 6: Record the checkpoint**

Record the four runtime/settings files, two test files, test count, and exit code.

---

### Task 3: Build and Verify a Shared-Only Migration Stage

**Files:**
- Create: `context_os/shared_migrate.py`
- Modify: `context_os/migrate.py`
- Modify: `context_os/verify.py`
- Create: `tests/test_shared_migration.py`

**Interfaces:**
- Consumes: `SharedNasTopology`, existing `prepare_migration()`, `build_stage()`, and `verify_stage()`.
- Produces: `SharedMigration`, `prepare_shared_migration()`, `build_shared_stage()`, `verify_shared_stage()`, and `regenerate_managed_manifest()`.

- [ ] **Step 1: Write failing shared-stage tests**

```python
def test_shared_migration_snapshots_shared_only(self):
    fixture = make_three_machine_fixture(self.base)
    before = inventory_tree(fixture.container / 'machines')
    migration = prepare_shared_migration(fixture.topology, self.base / 'work')
    build_shared_stage(migration, ROOT / 'template_root', ROOT)
    self.assertEqual(migration.paths.source, fixture.container / 'shared')
    self.assertEqual(inventory_tree(fixture.container / 'machines'), before)
    report = json.loads((migration.paths.stage / 'context-os/migration/migration-report.json').read_text())
    sources = {row['source'] for row in report['mappings']}
    self.assertNotIn('machines', sources)
    self.assertNotIn('shared', sources)

def test_nonempty_shared_claude_requires_semantic_review(self):
    fixture = make_three_machine_fixture(self.base)
    migration = prepare_shared_migration(fixture.topology, self.base / 'work')
    build_shared_stage(migration, ROOT / 'template_root', ROOT)
    status = json.loads((migration.paths.stage / 'context-os/migration/semantic-review.json').read_text())
    self.assertEqual(status['status'], 'pending')

def test_shared_verifier_rejects_nas_runtime(self):
    fixture = make_three_machine_fixture(self.base)
    migration = prepare_and_build(fixture)
    config_path = migration.paths.stage / 'context-os/config/context-os.json'
    config = json.loads(config_path.read_text())
    config['paths']['runtime_root'] = str(fixture.container / 'runtime')
    config_path.write_text(json.dumps(config))
    result = verify_shared_stage(migration)
    self.assertIn('runtime path must be local', result.errors)

def test_shared_stage_preserves_existing_settings_and_hooks(self):
    fixture = make_three_machine_fixture(self.base)
    settings_path = fixture.shared_root / 'settings.json'
    settings_path.write_text(json.dumps({'theme':'dark','hooks':{
        'Stop':[{'hooks':[{'type':'command','command':'existing-stop'}]}]
    }}))
    migration = prepare_and_build(fixture)
    staged = json.loads((migration.paths.stage/'settings.json').read_text())
    self.assertEqual(staged['theme'], 'dark')
    self.assertEqual(staged['hooks']['Stop'][0]['hooks'][0]['command'], 'existing-stop')
```

- [ ] **Step 2: Run the focused tests and verify missing shared-migration interfaces**

Run: `rtk python3 -m unittest tests.test_shared_migration -v`

Expected: FAIL because `context_os.shared_migrate` is absent.

- [ ] **Step 3: Expose managed-manifest regeneration**

Extract the existing manifest construction from `build_stage()` into:

```python
def regenerate_managed_manifest(stage: Path, template_root: Path) -> dict:
    managed = managed_paths(stage, template_root)
    manifest = build_manifest(stage, managed)
    write_json(stage / 'context-os/integrity/managed-manifest.json', manifest)
    return manifest
```

Call this function from the existing single-root path so behavior remains identical.

- [ ] **Step 4: Implement shared preparation and stage configuration**

```python
@dataclass
class SharedMigration:
    topology: SharedNasTopology
    paths: MigrationPaths
    topology_manifest: Path
    enrollment_plan: Path

def prepare_shared_migration(topology, workspace):
    paths = prepare_migration(topology.logical_root, workspace)
    manifest = paths.workspace / 'topology-guard.json'
    write_json(manifest, topology_guard(topology))
    return SharedMigration(topology, paths, manifest,
                           paths.workspace / 'primary-enrollment-plan.json')
```

`build_shared_stage()` calls the existing stage builder against `shared/`, rewrites only V3-managed configuration/settings to portable paths, writes `topology.json`, writes the primary dry-run enrollment plan, and regenerates the managed manifest after all managed changes.

- [ ] **Step 5: Implement shared verification**

`verify_shared_stage()` composes `verify_stage()` with exact checks for topology guard presence, all three machine roots, portable local runtime, non-empty shared semantic-review status, no container-level `machines`/`shared` preservation mappings, valid facade inventory, and enrollment-plan readiness. Errors include the failing path.

- [ ] **Step 6: Run focused shared-migration tests**

Run: `rtk python3 -m unittest tests.test_shared_migration tests.test_migrate tests.test_v3_migration_and_ops.LiveRootSnapshotTests -v`

Expected: all new tests and existing V3.0.1 snapshot tests pass.

- [ ] **Step 7: Record the checkpoint**

Record the shared migration files, exact test count, and exit code.

---

### Task 4: Plan, Apply, Verify, and Roll Back Mac Mini Enrollment

**Files:**
- Create: `context_os/enrollment.py`
- Create: `tests/test_machine_enrollment.py`

**Interfaces:**
- Consumes: `SharedNasTopology`, staged or active shared root, local facade, resolved runtime.
- Produces: `plan_machine_enrollment()`, `apply_machine_enrollment()`, `verify_machine_enrollment()`, and `rollback_machine_enrollment()`.

- [ ] **Step 1: Write failing dry-run and collision tests**

```python
def test_primary_plan_preserves_existing_facade_and_adds_only_v3_entries(self):
    fixture = make_three_machine_fixture(self.base)
    plan = plan_machine_enrollment(fixture.topology, 'mac-mini-m4',
                                   fixture.facade, self.base / 'workspace')
    self.assertEqual(plan['status'], 'ready')
    self.assertEqual({a['path'] for a in plan['actions']}, {
        str(fixture.facade / 'context-os'),
        str(fixture.facade / 'commands'),
        str(fixture.facade / 'rules'),
        str(fixture.facade / 'context-os-machine.json'),
    })
    self.assertTrue((fixture.facade / 'settings.local.json').exists())

def test_primary_plan_blocks_unexpected_context_os_file(self):
    fixture = make_three_machine_fixture(self.base)
    (fixture.facade / 'context-os').write_text('collision')
    plan = plan_machine_enrollment(fixture.topology, 'mac-mini-m4',
                                   fixture.facade, self.base / 'workspace')
    self.assertEqual(plan['status'], 'blocked')
    self.assertIn('unexpected existing path', plan['errors'][0])
```

- [ ] **Step 2: Run tests and verify missing enrollment interfaces**

Run: `rtk python3 -m unittest tests.test_machine_enrollment -v`

Expected: FAIL because `context_os.enrollment` does not exist.

- [ ] **Step 3: Implement deterministic enrollment planning**

The plan JSON contains `plan_id`, `machine_id`, `facade_root`, `shared_root`, `machine_root`, `runtime_root`, `status`, `errors`, `actions`, and `rollback`. Each action records `operation`, `path`, `target` or `content_sha256`, and `precondition` (`absent` or exact existing type/target/hash).

Only `context-os`, `commands`, `rules`, and `context-os-machine.json` are V3-owned primary enrollment entries. Existing entries outside that set are inventory evidence, not actions.

- [ ] **Step 4: Write failing apply/rollback tests**

```python
def test_apply_then_rollback_changes_only_manifest_paths(self):
    fixture = make_three_machine_fixture(self.base)
    before = inventory_tree(fixture.facade)
    plan = ready_plan(fixture)
    result = apply_machine_enrollment(plan)
    self.assertTrue((fixture.facade / 'context-os').is_symlink())
    self.assertFalse(str(result['runtime_root']).startswith(str(fixture.container)))
    rollback_machine_enrollment(Path(result['manifest']))
    after = inventory_tree(fixture.facade)
    self.assertEqual(before, after)

def test_apply_refuses_changed_precondition(self):
    fixture = make_three_machine_fixture(self.base)
    plan = ready_plan(fixture)
    (fixture.facade / 'rules').write_text('appeared after planning')
    with self.assertRaisesRegex(RuntimeError, 'precondition changed: .*rules'):
        apply_machine_enrollment(plan)
```

- [ ] **Step 5: Run apply tests and verify they fail before implementation**

Run: `rtk python3 -m unittest tests.test_machine_enrollment -v`

Expected: dry-run tests pass; apply/rollback tests fail because transaction functions are absent.

- [ ] **Step 6: Implement path-scoped apply and rollback**

Apply rechecks every precondition before the first write, writes the transaction manifest, creates only absent approved links/profile paths, creates the local runtime, and records exact created paths. On any failure it invokes path-scoped rollback. Rollback removes only transaction-created paths, restores any manifest-backed path, verifies the facade inventory against the pre-apply manifest, and never replaces the whole facade.

- [ ] **Step 7: Run focused enrollment tests**

Run: `rtk python3 -m unittest tests.test_machine_enrollment -v`

Expected: all enrollment tests pass.

- [ ] **Step 8: Record the checkpoint**

Record enrollment implementation/tests and the focused evidence.

---

### Task 5: Add Guarded Shared Activation and Verified Rollback

**Files:**
- Modify: `context_os/shared_migrate.py`
- Modify: `context_os/rollback.py`
- Modify: `tests/test_shared_migration.py`
- Modify: `tests/test_activation.py`

**Interfaces:**
- Consumes: verified `SharedMigration`, completed semantic review, ready primary enrollment plan.
- Produces: `activate_shared()`, `rollback_shared()`, and `probe_shared_rollback()`.

- [ ] **Step 1: Write failing activation-guard tests**

```python
def test_activate_shared_swaps_only_shared_directory(self):
    fixture = make_three_machine_fixture(self.base)
    machine_before = inventory_tree(fixture.container / 'machines')
    migration = verified_reviewed_shared_migration(fixture)
    result = activate_shared(migration)
    self.assertTrue((fixture.container / 'shared/context-os/VERSION').exists())
    self.assertEqual(inventory_tree(fixture.container / 'machines'), machine_before)
    self.assertEqual(Path(result['rollback_root']).parent, fixture.container)

def test_activate_shared_restores_old_shared_on_second_rename_failure(self):
    fixture = make_three_machine_fixture(self.base)
    migration = verified_reviewed_shared_migration(fixture)
    with fail_prepared_stage_rename():
        with self.assertRaises(OSError):
            activate_shared(migration)
    self.assertEqual((fixture.container / 'shared/CLAUDE.md').read_text(), fixture.original_claude)

def test_activation_requires_fresh_rollback_probe(self):
    migration = verified_reviewed_shared_migration(make_three_machine_fixture(self.base))
    (migration.paths.workspace / 'rollback-probe.json').unlink(missing_ok=True)
    with self.assertRaisesRegex(RuntimeError, 'rollback probe evidence missing'):
        activate_shared(migration)

def test_activation_rejects_shared_source_change_after_staging(self):
    fixture = make_three_machine_fixture(self.base)
    migration = verified_reviewed_shared_migration(fixture)
    (fixture.shared_root/'CLAUDE.md').write_text('changed after staging')
    with self.assertRaisesRegex(RuntimeError, 'shared source changed after staging'):
        activate_shared(migration)
```

- [ ] **Step 2: Run focused tests and verify activation guards are absent**

Run: `rtk python3 -m unittest tests.test_shared_migration tests.test_activation -v`

Expected: FAIL on missing guarded shared activation interfaces.

- [ ] **Step 3: Implement same-filesystem rollback probe**

The probe creates uniquely named `active` and `rollback` fixtures under the container, calls the real rollback function, verifies restored/displaced contents, writes evidence with filesystem paths and timestamp, and removes only its validated probe directory. Failed probes remain for diagnosis and block activation.

- [ ] **Step 4: Implement shared activation wrapper**

`activate_shared()` calls `verify_shared_stage(require_source_unchanged=True)` immediately before mutation, requires semantic review, validates fresh probe evidence and primary enrollment readiness, then delegates the rename transaction to `activate_verified_stage()` with `paths.source == topology.logical_root`. The strict verification compares the current shared inventory with the frozen source manifest so writes after staging block activation. It asserts no path under `machines/` is a mutation target.

- [ ] **Step 5: Implement verified shared rollback**

`rollback_shared()` calls the existing rename rollback, then inventories the restored shared root and compares it with `source-manifest.json`. A mismatch returns nonzero evidence and retains both restored and displaced roots.

- [ ] **Step 6: Run focused activation and rollback tests**

Run: `rtk python3 -m unittest tests.test_shared_migration tests.test_activation -v`

Expected: all shared and legacy activation tests pass.

- [ ] **Step 7: Record the checkpoint**

Record implementation files, focused counts, probe semantics, and exit code.

---

### Task 6: Expose Governed CLI Commands

**Files:**
- Modify: `contextctl.py`
- Modify: `tests/test_cli.py`
- Create: `tests/test_shared_nas_end_to_end.py`

**Interfaces:**
- Consumes: topology, shared migration, enrollment, activation, and rollback APIs.
- Produces: `adopt-shared`, `verify-shared`, `activate-shared`, `rollback-shared`, `enroll-machine`, and `rollback-machine` CLI commands.

- [ ] **Step 1: Write failing CLI contract tests**

```python
def test_adopt_shared_defaults_to_stage_only(self):
    result = run_cli('adopt-shared', '--root', str(self.container),
                     '--workspace', str(self.workspace),
                     '--primary-machine', 'mac-mini-m4',
                     '--facade', str(self.facade))
    self.assertEqual(result.returncode, 0, result.stderr)
    payload = json.loads(result.stdout)
    self.assertTrue(payload['verification']['ok'])
    self.assertNotIn('activation', payload)
    self.assertEqual((self.container / 'shared/CLAUDE.md').read_text(), self.original_claude)

def test_enroll_machine_is_dry_run_without_apply(self):
    result = run_cli('enroll-machine', '--root', str(self.container),
                     '--machine-id', 'mac-mini-m4', '--facade', str(self.facade),
                     '--workspace', str(self.workspace))
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertFalse((self.facade / 'context-os').exists())

def test_ea_context_reports_local_machine_profile(self):
    profile = self.facade/'context-os-machine.json'
    profile.write_text(json.dumps({'machine_id':'mac-mini-m4'}))
    result = run_cli('assistant-context', '--root', str(self.container/'shared'),
                     '--cwd', str(self.base), '--query', 'status',
                     env={'CONTEXT_OS_MACHINE_PROFILE':str(profile)})
    self.assertEqual(result.returncode, 0, result.stderr)
    payload = json.loads(result.stdout)
    self.assertEqual(payload['machine']['machine_id'], 'mac-mini-m4')
```

- [ ] **Step 2: Run CLI tests and verify parser rejection**

Run: `rtk python3 -m unittest tests.test_cli tests.test_shared_nas_end_to_end -v`

Expected: FAIL because the new commands are unknown.

- [ ] **Step 3: Add explicit parsers and handlers**

Required shared arguments are `--root`, `--workspace`, `--primary-machine`, repeatable `--secondary-machine`, and `--facade`. `activate-shared` has no semantic-review bypass. `enroll-machine` requires `--apply` for mutation. Rollback commands require exact manifest/workspace paths rather than selecting a latest directory implicitly. Extend `_ea_context()` to load `context-os-machine.json` from the local facade and return its non-secret machine identity/path metadata under `machine`; missing profiles return `machine: null` without changing deterministic OS control.

- [ ] **Step 4: Implement synthetic three-machine end-to-end coverage**

The fixture creates shared settings/instructions, all three machine roots, and a Mac Mini facade. The test stages, marks semantic review complete, verifies, probes rollback, activates shared, enrolls the Mac Mini, runs `doctor`, reindex/FTS, hook ingestion, EA context, machine rollback, and shared rollback. It asserts the complete `machines/` inventory is identical before and after the shared transaction.

- [ ] **Step 5: Run focused CLI and end-to-end tests**

Run: `rtk python3 -m unittest tests.test_cli tests.test_shared_nas_end_to_end -v`

Expected: all focused tests pass.

- [ ] **Step 6: Record the checkpoint**

Record CLI signatures, test evidence, and exact mutation defaults.

---

### Task 7: Release-Candidate Verification and Documentation

**Files:**
- Modify: `README.md`
- Modify: `ADOPTION_PROTOCOL.md`
- Modify: `VERIFICATION_REPORT.md`
- Modify: `RELEASE_MANIFEST.json`
- Verify: all implementation and test files from Tasks 1-6.

**Interfaces:**
- Consumes: verified command behavior and test output.
- Produces: accurate operator instructions and release evidence; no real activation.

- [ ] **Step 1: Run all focused topology gates**

Run: `rtk python3 -m unittest tests.test_shared_topology tests.test_shared_migration tests.test_machine_enrollment tests.test_shared_nas_end_to_end -v`

Expected: all topology-focused tests pass.

- [ ] **Step 2: Run the complete regression suite once**

Run: `rtk python3 -m unittest discover -s tests -v`

Expected: exit 0 with no failures or errors. Record the actual test count; do not predeclare it.

- [ ] **Step 3: Run compilation and local-only gates**

Run: `rtk python3 -m compileall context_os template_root contextctl.py`

Expected: exit 0.

Run: `rtk python3 contextctl.py local-only-audit`

Expected: `ok: true`, `findings: []`, and `runtime_web_dependencies: false`.

Run: `rtk python3 -m json.tool RELEASE_MANIFEST.json`

Expected: valid JSON and exit 0.

- [ ] **Step 4: Update documentation from actual evidence**

Document the single-system path separately from `shared-nas-v1`; include exact stage-only, review, verification, probe, activation, enrollment, and rollback commands. Update the release manifest test count and feature list only from Step 2 output. State that real shared activation has not occurred.

- [ ] **Step 5: Perform read-only comparison against the real topology**

Run `adopt-shared` without activation against `/Volumes/BryzConfig/Claude`, using a new timestamped local workspace. Inspect the topology guard, shared backup verification, migration report, semantic-review queue, primary enrollment dry run, and runtime resolution. Confirm no active marker, shared rollback root, or facade transaction marker was created.

- [ ] **Step 6: Stop at the activation gate**

Report package changes, test evidence, real staged-migration evidence, semantic-review requirements, rollback-probe evidence, and exact next commands. Do not run `activate-shared` or `enroll-machine --apply` until the user reviews that evidence and explicitly authorizes the activation phase.
