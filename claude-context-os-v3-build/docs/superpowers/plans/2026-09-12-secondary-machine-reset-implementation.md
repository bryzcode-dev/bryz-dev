# Secondary Machine Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a recoverable, local-only reset and enrollment workflow for `bryans-macbook-pro` and `bryan-mac-neo` after the Mac Mini shared-NAS deployment is complete.

**Architecture:** Build on the verified topology and enrollment APIs from the primary plan. Each secondary Mac runs the command locally; existing machine and selected facade state move to timestamped archives before a fresh machine root, symlink facade, machine profile, and local runtime are created.

**Tech Stack:** Python 3 standard library, `unittest`, JSON manifests, filesystem rename/symlink operations.

**Spec:** `docs/superpowers/specs/2026-09-12-shared-nas-topology-design.md`

## Global Constraints

- Do not start this plan until the primary implementation plan is complete and the Mac Mini passes post-activation health.
- Refuse `mac-mini-m4` as a reset target.
- Dry-run is the default; mutation requires `--apply` and exact machine/facade paths.
- Move old state into timestamped archives; never permanently delete archives.
- Run the command locally on the Mac being enrolled.
- Preserve the active shared root and never modify another machine's directory.
- Keep runtime state local and verify rollback before declaring enrollment complete.
- The package is not a Git repository; use changed-file/test checkpoints instead of commits.

---

### Task 1: Plan a Secondary Reset and Refuse Unsafe Targets

**Files:**
- Modify: `context_os/enrollment.py`
- Create: `tests/test_secondary_reset.py`

**Interfaces:**
- Consumes: verified `SharedNasTopology`, secondary machine ID, local facade, workspace.
- Produces: `plan_secondary_reset() -> dict`.

- [ ] **Step 1: Write failing safety tests**

```python
class SecondaryResetTests(SharedNasTestCase):
    def setUp(self):
        super().setUp()
        self.machine_id = 'bryans-macbook-pro'
        self.facade = make_secondary_facade(self.fixture, self.machine_id)
        self.machine_root = self.topology.machines_root / self.machine_id

    def test_refuses_primary_machine_reset(self):
        with self.assertRaisesRegex(RuntimeError, 'primary machine cannot be reset'):
            plan_secondary_reset(self.topology, 'mac-mini-m4', self.facade, self.workspace)

    def test_refuses_running_for_a_different_machine_facade(self):
        with self.assertRaisesRegex(RuntimeError, 'machine profile does not match'):
            plan_secondary_reset(self.topology, 'bryans-macbook-pro',
                                 self.other_machine_facade, self.workspace)

    def test_dry_run_records_archive_and_rebuild_actions_without_writing(self):
        before = inventory_tree(self.facade)
        plan = plan_secondary_reset(self.topology, 'bryans-macbook-pro',
                                    self.facade, self.workspace)
        self.assertEqual(plan['status'], 'ready')
        self.assertEqual(inventory_tree(self.facade), before)
        self.assertTrue(plan['machine_archive'].startswith(str(self.topology.machines_root)))
```

- [ ] **Step 2: Run tests and verify missing planner behavior**

Run: `rtk python3 -m unittest tests.test_secondary_reset -v`

Expected: FAIL because `plan_secondary_reset()` is absent.

- [ ] **Step 3: Implement the reset planner**

The plan records exact source/archive paths, selected facade entries, expected precondition fingerprints, new shared links, new machine links, machine profile content/hash, runtime path, and rollback order. It validates that the current machine is the requested secondary through an existing local profile or an explicit machine-ID confirmation file created during dry-run review.

- [ ] **Step 4: Run focused planner tests**

Run: `rtk python3 -m unittest tests.test_secondary_reset -v`

Expected: all planning and refusal tests pass.

- [ ] **Step 5: Record the checkpoint**

Record changed files, test count, and exit code.

---

### Task 2: Apply and Roll Back the Archival Reset

**Files:**
- Modify: `context_os/enrollment.py`
- Modify: `tests/test_secondary_reset.py`

**Interfaces:**
- Consumes: reviewed ready reset plan.
- Produces: `apply_secondary_reset()` and `rollback_secondary_reset()`.

- [ ] **Step 1: Write failing transaction tests**

```python
def test_apply_archives_old_machine_and_builds_fresh_facade(self):
    plan = ready_secondary_plan(self.fixture, 'bryans-macbook-pro')
    result = apply_secondary_reset(plan)
    archive = Path(result['machine_archive'])
    self.assertTrue((archive / 'history.jsonl').exists())
    self.assertTrue((self.machine_root / 'projects').is_dir())
    self.assertTrue((self.facade / 'CLAUDE.md').is_symlink())
    self.assertTrue((self.facade / 'projects').is_symlink())
    self.assertFalse(str(result['runtime_root']).startswith(str(self.topology.container_root)))

def test_failure_rolls_back_archived_machine_and_facade(self):
    before_machine = inventory_tree(self.machine_root)
    before_facade = inventory_tree(self.facade)
    with fail_symlink_creation('projects'):
        with self.assertRaises(OSError):
            apply_secondary_reset(ready_secondary_plan(self.fixture, 'bryans-macbook-pro'))
    self.assertEqual(inventory_tree(self.machine_root), before_machine)
    self.assertEqual(inventory_tree(self.facade), before_facade)
```

- [ ] **Step 2: Run tests and verify transaction functions are missing**

Run: `rtk python3 -m unittest tests.test_secondary_reset -v`

Expected: planning tests pass and transaction tests fail.

- [ ] **Step 3: Implement ordered archival apply**

Apply revalidates every fingerprint, writes the transaction manifest, renames the machine root to its timestamped archive, archives only selected facade entries, creates the fresh machine root, creates native subdirectories, installs links/profile/runtime, and verifies enrollment. Any failure triggers rollback in reverse order.

- [ ] **Step 4: Implement rollback without deletion**

Rollback moves failed fresh state aside, restores the archived machine root and facade entries, verifies pre-reset manifests, and retains the failed fresh state for diagnosis. It refuses paths outside the approved container, machine root, facade, workspace, and local runtime.

- [ ] **Step 5: Run focused transaction tests**

Run: `rtk python3 -m unittest tests.test_secondary_reset -v`

Expected: all reset/apply/rollback tests pass.

- [ ] **Step 6: Record the checkpoint**

Record changed files and focused transaction evidence.

---

### Task 3: CLI, Documentation, and Secondary Release Gate

**Files:**
- Modify: `contextctl.py`
- Modify: `ADOPTION_PROTOCOL.md`
- Modify: `VERIFICATION_REPORT.md`
- Modify: `RELEASE_MANIFEST.json`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_shared_nas_end_to_end.py`

**Interfaces:**
- Consumes: secondary reset transaction APIs.
- Produces: `reset-machine` and `rollback-machine-reset` commands plus operator runbook.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_reset_machine_defaults_to_dry_run(self):
    result = run_cli('reset-machine', '--root', str(self.container),
                     '--machine-id', 'bryans-macbook-pro',
                     '--facade', str(self.facade), '--workspace', str(self.workspace))
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(json.loads(result.stdout)['status'], 'ready')
    self.assertTrue((self.machine_root / 'history.jsonl').exists())

def test_reset_machine_requires_secondary_id(self):
    result = run_cli('reset-machine', '--root', str(self.container),
                     '--machine-id', 'mac-mini-m4', '--facade', str(self.facade),
                     '--workspace', str(self.workspace), '--apply')
    self.assertNotEqual(result.returncode, 0)
```

- [ ] **Step 2: Run CLI tests and verify parser rejection**

Run: `rtk python3 -m unittest tests.test_cli tests.test_secondary_reset -v`

Expected: FAIL because reset commands are unknown.

- [ ] **Step 3: Add explicit reset and rollback handlers**

`reset-machine` requires `--root`, `--machine-id`, `--facade`, and `--workspace`; `--apply` enables mutation. `rollback-machine-reset` requires the exact transaction manifest. Neither command accepts a primary-machine override or permanent-delete option.

- [ ] **Step 4: Extend end-to-end coverage for both secondary IDs**

Run the same dry-run/apply/health/rollback sequence independently for `bryans-macbook-pro` and `bryan-mac-neo`. Assert the shared inventory and the non-target machine inventory remain unchanged for each transaction.

- [ ] **Step 5: Run the release-candidate gates once**

Run: `rtk python3 -m unittest discover -s tests -v`

Expected: exit 0 with no failures or errors.

Run: `rtk python3 -m compileall context_os template_root contextctl.py`

Expected: exit 0.

Run: `rtk python3 contextctl.py local-only-audit`

Expected: `ok: true` with no findings.

- [ ] **Step 6: Update the operator runbook from actual evidence**

Document dry-run, apply, verification, and rollback commands for each secondary machine. State that the command must run locally on the target Mac and that archives are retained.

- [ ] **Step 7: Stop before real secondary reset**

Present the exact commands and evidence for one secondary Mac at a time. Do not execute `--apply` until the user is working on that Mac and explicitly authorizes its reset.
