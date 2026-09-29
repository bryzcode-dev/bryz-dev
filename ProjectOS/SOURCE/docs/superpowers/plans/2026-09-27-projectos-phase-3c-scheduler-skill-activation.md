# ProjectOS Phase 3C Scheduler, Skill, and Runtime Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify the fixture-only ProjectOS runtime activation layer: canonical skill discovery, one configured locked sync command, deterministic macOS/Windows scheduler definitions, reversible activation, and fail-closed deactivation.

**Architecture:** Phase 3C adds portable skill and scheduler contracts around the Phase 3B immutable definition transaction. Native adapters render and validate platform artifacts, while an injected fixture runner owns all candidate side effects; a separate activation journal enables the scheduler before atomically enabling discovery and reverses that order on failure. Both scheduled and skill-triggered synchronization use one profile-bound runtime coordinator and the existing SQLite/Google sync service.

**Tech Stack:** Python 3.11+, standard library only (`dataclasses`, `enum`, `hashlib`, `json`, `os`, `pathlib`, `plistlib`, `sqlite3`, `tempfile`, `time`, `xml.etree.ElementTree`), `unittest`, existing ProjectOS Phase 3A/3B contracts.

**Spec:** `docs/superpowers/specs/2026-09-27-projectos-phase-3c-scheduler-skill-activation-design.md`

## Global Constraints

- macOS and Windows are first-class host families; Windows must not require symlinks, Developer Mode, PowerShell wrappers, or a stored account password.
- SQLite remains the single source of truth. Runtime sync opens an existing current-schema database and never initializes or migrates it implicitly.
- The common command is `<python> -m projectos.cli --db <database> runtime sync --machine-profile <profile> --trigger <scheduler|skill>`; the explicit database must match the profile.
- Scheduler interval is exactly 7,200 seconds, execution limit is 1,800 seconds, overlap policy rejects a second instance, and rendered definitions start disabled.
- Scheduler and skill definitions contain no secrets, emails, Google identifiers, credential references, build-host identifiers, or shared/runtime overlap.
- Lock waiting is zero seconds for scheduler triggers and configurable from zero through thirty seconds for skill triggers, default ten.
- Skill discovery is read-only and returns no state-changing capability unless every ordered gate succeeds.
- Phase 3C state-changing CLI commands accept only acknowledged receipt-bound fixtures and only the fixture scheduler runner. There is no live target, native runner flag, force flag, or registry-enable shortcut.
- No candidate test may execute `launchctl`, `schtasks`, PowerShell, Task Scheduler COM, a real Google call, GAS, Looker, or production SQLite work.
- Every command returns one redacted JSON envelope. Validation exits `2`, operational/health failure exits `3`, and unexpected failure exits `1`.
- Use TDD for every production behavior and focused tests per task. The complete ProjectOS suite remains deferred until the full Phase 3 release-candidate gate.

## Review Focus

- A malformed, replaced, or disappearing lock-owner record must fail safely without extending the thirty-second bound or starting a duplicate run; Task 2 pins this with contention and injected-clock tests.
- XML/plist metacharacters in resolved target paths must be escaped as data and never become a shell command; Task 3 pins this with special-character path and exact-argv tests.
- A crash immediately before or after registry enablement must recover to exact disabled bytes before scheduler teardown; Task 6 injects both boundaries.
- A scheduler enabled successfully followed by skill or proof failure must leave neither discovery nor a scheduler fixture active; Task 6 injects those failures and verifies reverse-order rollback.
- A modified installed payload, skill, profile, database schema, configuration, or scheduler state must make discovery fail closed without repair or Google access; Task 5 tests every ordered gate.

---

## File Structure

```text
src/projectos/adoption/skill.py                Canonical skill render and verification
src/projectos/adoption/scheduler.py            Shared scheduler values, protocols, commands, state
src/projectos/adoption/scheduler_macos.py      Deterministic launchd adapter
src/projectos/adoption/scheduler_windows.py    Deterministic Task Scheduler adapter
src/projectos/adoption/scheduler_fixture.py    Receipt-bound local fixture runner
src/projectos/adoption/discovery.py            Installed inventory and fail-closed skill discovery
src/projectos/adoption/activation_store.py     Local activation journals, snapshots, scheduler artifacts
src/projectos/adoption/activation.py           Activation/deactivation/recovery orchestration
src/projectos/runtime.py                       Profile-bound configured sync coordinator
src/projectos/database.py                      Existing/current-schema open modes
src/projectos/sync/lock.py                     Safe lock-owner inspection
src/projectos/sync/service.py                  Bounded wait around the existing common lock
src/projectos/adoption/registry.py             Disabled/enabled ProjectOS entry representation
src/projectos/adoption/transaction.py          Enabled-entry guards for Phase 3B operations
src/projectos/cli.py                            Runtime and fixture-only Phase 3C commands
tests/test_projectos_skill.py                  Canonical skill tests
tests/test_runtime_sync.py                     Existing DB, config, trigger, and contention tests
tests/test_scheduler_adapters.py               macOS/Windows render and lifecycle contract tests
tests/test_scheduler_fixture.py                Fixture runner state and persistence tests
tests/test_skill_discovery.py                  Ordered fail-closed discovery tests
tests/test_activation_transaction.py           Crash injection, deactivation, and recovery tests
tests/test_cli_phase3c.py                       JSON, database, and no-live-target CLI tests
docs/PHASE3C_OPERATIONS.md                      Fixture activation and recovery runbook
docs/PHASE3C_VERIFICATION.md                    Candidate evidence
```

### Task 1: Canonical Skill Contract and Enabled Registry State

**Files:**
- Create: `src/projectos/adoption/skill.py`
- Create: `tests/test_projectos_skill.py`
- Modify: `src/projectos/adoption/registry.py`
- Modify: `src/projectos/adoption/__init__.py`
- Modify: `tests/test_extension_registry.py`

**Interfaces:**
- Consumes: `ExtensionManifest`, `ArtifactPolicy`, `ProjectOSExtensionEntry`.
- Produces: `SKILL_DESCRIPTION`; `render_projectos_skill(manifest: ExtensionManifest) -> bytes`; `verify_projectos_skill(content: bytes, manifest: ExtensionManifest, policy: ArtifactPolicy) -> None`; `ProjectOSExtensionEntry.with_enabled(enabled: bool) -> ProjectOSExtensionEntry`; `plan_projectos_entry(manifest: ExtensionManifest, bundle_sha256: str, relative_manifest_path: str, adopted_at: str, *, enabled: bool) -> ProjectOSExtensionEntry`; the existing `plan_disabled_entry` remains a compatibility wrapper.

- [ ] **Step 1: Write failing skill and registry tests**

Add tests named `test_skill_render_is_canonical_and_binds_sorted_manifest_capabilities`, `test_skill_requires_sync_before_state_dependent_actions`, `test_skill_preserves_role_visibility_and_excludes_looker`, `test_skill_rejects_modified_text_extra_capability_secret_and_host_identifier`, `test_registry_accepts_canonical_enabled_projectos_entry`, and `test_registry_enabled_transition_changes_only_enabled_field`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_projectos_skill tests.test_extension_registry -v`  
Expected: FAIL because `projectos.adoption.skill` and enabled-entry interfaces do not exist.

- [ ] **Step 3: Implement the canonical contract**

Render deterministic UTF-8 Markdown with fixed YAML front matter and sorted allowlisted capabilities. Verification requires exact bytes and applies `ArtifactPolicy`. Relax only the ProjectOS `enabled` field from Phase 3B's required `false` to a strict Boolean; preserve all other registry invariants and unrelated values.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_projectos_skill tests.test_extension_registry tests.test_extension_bundle -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/skill.py src/projectos/adoption/registry.py src/projectos/adoption/__init__.py tests/test_projectos_skill.py tests/test_extension_registry.py
rtk git commit --no-gpg-sign -m "feat: define the canonical ProjectOS skill"
```

### Task 2: Existing-Database Runtime Sync and Bounded Lock Waiting

**Files:**
- Create: `src/projectos/runtime.py`
- Create: `tests/test_runtime_sync.py`
- Modify: `src/projectos/database.py`
- Modify: `src/projectos/sync/lock.py`
- Modify: `src/projectos/sync/service.py`
- Modify: `src/projectos/google/config.py`
- Modify: `tests/test_sync_service.py`
- Modify: `tests/test_process_lock.py`

**Interfaces:**
- Consumes: `MachineProfile`, `ProjectOSGoogleConfig`, `ProjectOSDatabase`, `GoogleSyncService`, `GoogleGateway`.
- Produces: `ProjectOSDatabase.open_existing(path: Path, *, read_only: bool = False) -> ProjectOSDatabase`; immutable `LockOwner`; `ProjectOSFileLock.read_owner(path: Path) -> LockOwner | None`; bounded parameters on `GoogleSyncService.run(binding_id, trigger, *, wait_seconds=0.0, monotonic=time.monotonic, sleeper=time.sleep) -> SyncRunResult`; `RuntimeTrigger`; `runtime_sync_argv(profile: MachineProfile, profile_path: Path, trigger: RuntimeTrigger) -> tuple[str, ...]`; `RuntimeSyncCoordinator.run(profile_path, database_path, trigger, gateway, *, wait_seconds=None, monotonic=time.monotonic, sleeper=time.sleep) -> SyncRunResult`.

- [ ] **Step 1: Write failing runtime and contention tests**

Add tests named `test_open_existing_never_creates_or_migrates_database`, `test_open_existing_read_only_does_not_create_wal_or_shm`, `test_runtime_sync_requires_database_and_config_to_match_profile`, `test_runtime_sync_requires_current_schema_and_enabled_google_writes`, `test_scheduler_and_skill_use_same_service_and_profile_lock`, `test_scheduler_never_waits_and_skill_defaults_to_ten_seconds`, `test_skill_wait_rejects_negative_or_above_thirty_seconds`, `test_contention_returns_only_safe_owner_metadata`, and `test_malformed_replaced_or_disappearing_owner_never_starts_duplicate_sync`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_runtime_sync tests.test_sync_service tests.test_process_lock -v`  
Expected: FAIL because existing-database, owner-inspection, and runtime coordinator interfaces are absent.

- [ ] **Step 3: Implement existing/current-schema database opens**

Read-only mode uses SQLite URI `mode=ro`, does not create parent directories or set WAL mode, and validates schema version without applying migrations. Writable runtime mode requires the file before connecting and validates the current schema without calling `initialize()`.

- [ ] **Step 4: Implement bounded locking and runtime coordination**

Keep the existing nonblocking native backends. Retry only in `GoogleSyncService.run` using injected monotonic time/sleeper. Validate lock-owner JSON through the owned format and return bounded fields. Build the one exact scheduler/skill argv tuple in `runtime_sync_argv`, with no shell rendering. `RuntimeSyncCoordinator` strictly reloads the profile/config, validates locality and exact database equality, chooses the trigger wait policy, and calls the existing service once after lock acquisition.

- [ ] **Step 5: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_runtime_sync tests.test_sync_service tests.test_process_lock tests.test_database tests.test_database_phase2 -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add src/projectos/runtime.py src/projectos/database.py src/projectos/sync/lock.py src/projectos/sync/service.py src/projectos/google/config.py tests/test_runtime_sync.py tests/test_sync_service.py tests/test_process_lock.py
rtk git commit --no-gpg-sign -m "feat: add configured locked runtime sync"
```

### Task 3: Deterministic macOS and Windows Scheduler Adapters

**Files:**
- Create: `src/projectos/adoption/scheduler.py`
- Create: `src/projectos/adoption/scheduler_macos.py`
- Create: `src/projectos/adoption/scheduler_windows.py`
- Create: `tests/test_scheduler_adapters.py`
- Modify: `src/projectos/adoption/__init__.py`

**Interfaces:**
- Consumes: `MachineProfile`, `HostFamily`, `SchedulerKind`, and Task 2's `runtime_sync_argv`.
- Produces: `SCHEDULE_INTERVAL_SECONDS = 7200`; `EXECUTION_LIMIT_SECONDS = 1800`; `SchedulerAction`; `SchedulerState`; immutable `SchedulerDefinition` and `SchedulerInspection`; runtime-checkable `SchedulerRunner`; `SchedulerAdapter` protocol with `render(profile, profile_path)`, `verify`, `install`, `enable`, `inspect`, `disable`, and `remove`; `LaunchdSchedulerAdapter`; `WindowsTaskSchedulerAdapter`; `adapter_for(profile) -> SchedulerAdapter`.

- [ ] **Step 1: Write failing adapter tests**

Add tests named `test_launchd_render_is_canonical_disabled_two_hour_and_local`, `test_windows_render_is_canonical_disabled_two_hour_interactive_and_nonoverlapping`, `test_definitions_use_exact_common_runtime_argv_and_explicit_database`, `test_render_escapes_xml_metacharacters_without_shell_or_wrapper`, `test_verify_rejects_changed_hash_interval_limit_task_id_or_enabled_state`, `test_adapter_lifecycle_uses_runner_actions_in_order`, and `test_windows_definition_requires_no_password_symlink_or_developer_mode`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_scheduler_adapters -v`  
Expected: FAIL because scheduler modules do not exist.

- [ ] **Step 3: Implement the shared scheduler contract and adapters**

Use `plistlib` for canonical launchd bytes and `xml.etree.ElementTree` for Task Scheduler XML. Obtain the exact argv tuple only through `runtime_sync_argv`; adapters must not reconstruct the command. Adapters delegate lifecycle actions to `SchedulerRunner`; they never call subprocesses or a shell.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_scheduler_adapters tests.test_machine_profile tests.test_host_paths -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/scheduler.py src/projectos/adoption/scheduler_macos.py src/projectos/adoption/scheduler_windows.py src/projectos/adoption/__init__.py tests/test_scheduler_adapters.py
rtk git commit --no-gpg-sign -m "feat: render native ProjectOS scheduler definitions"
```

### Task 4: Receipt-Bound Fixture Scheduler Runner

**Files:**
- Create: `src/projectos/adoption/scheduler_fixture.py`
- Create: `tests/test_scheduler_fixture.py`
- Modify: `src/projectos/adoption/__init__.py`

**Interfaces:**
- Consumes: `FixtureInstallationTarget`, `MachineProfile`, `LocalAdoptionStore`, Task 3 definitions/actions.
- Produces: `FixtureSchedulerRunner.open(target, profile, store) -> FixtureSchedulerRunner`; `perform(action: SchedulerAction, definition: SchedulerDefinition) -> SchedulerInspection`; `inspect(definition) -> SchedulerInspection`; local state below `<runtime>/adoption/scheduler-fixtures/<task-hash>/` only.

- [ ] **Step 1: Write failing fixture-runner tests**

Add tests named `test_fixture_runner_persists_only_under_local_adoption_store`, `test_fixture_runner_install_enable_disable_remove_lifecycle`, `test_fixture_runner_rejects_enable_before_install_and_changed_definition`, `test_fixture_runner_rejects_nonfixture_overlap_symlink_and_native_executable_request`, `test_fixture_runner_is_idempotent_for_same_definition`, and `test_fixture_runner_state_contains_no_secret_or_absolute_contextos_path`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_scheduler_fixture -v`  
Expected: FAIL because the fixture runner does not exist.

- [ ] **Step 3: Implement local fixture state**

Persist canonical metadata and definition bytes with sibling temporary files, flush, `fsync`, and `os.replace`. Bind state to the fixture ID, installation ID, definition hash, scheduler kind, and task ID. Legal transitions are `ABSENT -> INSTALLED_DISABLED -> ENABLED -> INSTALLED_DISABLED -> ABSENT`.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_scheduler_fixture tests.test_scheduler_adapters tests.test_adoption_fixture tests.test_adoption_store -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/scheduler_fixture.py src/projectos/adoption/__init__.py tests/test_scheduler_fixture.py
rtk git commit --no-gpg-sign -m "feat: simulate scheduler lifecycle in fixtures"
```

### Task 5: Installed Inventory and Fail-Closed Skill Discovery

**Files:**
- Create: `src/projectos/adoption/discovery.py`
- Create: `tests/test_skill_discovery.py`
- Modify: `src/projectos/adoption/staging.py`
- Modify: `src/projectos/adoption/__init__.py`

**Interfaces:**
- Consumes: enabled `ExtensionRegistry`, `ExtensionManifest`, Task 1 skill verifier, `MachineProfile`, `FixtureInstallationTarget`, `ProjectOSDatabase.open_existing(read_only=True)`, `ProjectOSDoctor`, scheduler inspection.
- Produces: immutable `InstalledProjectOSExtension`, `DiscoveryDiagnostic`, `AdapterInvocation`, `DiscoveredSkill`, and `SkillDiscoveryResult`; `load_installed_extension(target, profile, policy) -> InstalledProjectOSExtension`; `SkillDiscoveryService.resolve(target, profile_path, store, runner, policy) -> SkillDiscoveryResult`.

- [ ] **Step 1: Write failing installed-inventory and discovery tests**

Add tests named `test_installed_extension_verifies_manifest_payload_and_bundle_hash_prefix`, `test_discovery_is_read_only_and_never_calls_google`, `test_discovery_returns_verified_skill_only_after_every_gate`, `test_discovery_fails_in_order_for_disabled_registry_inventory_skill_profile_database_and_scheduler`, `test_discovery_rejects_modified_payload_symlink_profile_or_config`, `test_discovery_read_only_database_check_creates_no_wal_shm_or_migration`, and `test_discovered_adapter_descriptor_contains_no_resolved_path_or_private_identifier`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_skill_discovery -v`  
Expected: FAIL because installed discovery interfaces do not exist.

- [ ] **Step 3: Implement installed inventory reconstruction**

Expose a non-mutating inventory helper from staging rather than duplicating hash rules. Validate the registry path, immutable version name, bundle-hash prefix, canonical manifest, payload hashes/sizes, symlink absence, compatibility, and canonical skill.

- [ ] **Step 4: Implement ordered discovery**

Return the first bounded diagnostic without repair. Open the existing database read-only, run health checks compatible with read-only inspection, and require an enabled fixture scheduler inspection. Return only portable adapter capability descriptors.

- [ ] **Step 5: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_skill_discovery tests.test_projectos_skill tests.test_scheduler_fixture tests.test_adoption_staging tests.test_backup_health -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add src/projectos/adoption/discovery.py src/projectos/adoption/staging.py src/projectos/adoption/__init__.py tests/test_skill_discovery.py
rtk git commit --no-gpg-sign -m "feat: gate ProjectOS skill discovery"
```

### Task 6: Runtime Activation, Deactivation, and Recovery Transaction

**Files:**
- Create: `src/projectos/adoption/activation_store.py`
- Create: `src/projectos/adoption/activation.py`
- Create: `tests/test_activation_transaction.py`
- Modify: `src/projectos/adoption/transaction.py`
- Modify: `src/projectos/adoption/__init__.py`
- Modify: `tests/test_adoption_transaction.py`

**Interfaces:**
- Consumes: completed Phase 3B definition journal, disabled registry entry, installed extension/discovery, scheduler adapter and fixture runner, Task 2 runtime coordinator.
- Produces: `ActivationState`; immutable `ActivationJournal`, `ActivationResult`, and `ActivationProofResult`; `LocalActivationStore`; runtime-checkable `ActivationProof` with `run(discovered: DiscoveredSkill, coordinator: RuntimeSyncCoordinator) -> ActivationProofResult`; `RuntimeActivation(target, profile_path, store, runner, policy, proof, *, boundary_hook=noop)`; `begin(definition_transaction_id: UUID) -> ActivationResult`; `resume(activation_id: UUID) -> ActivationResult`; `deactivate(activation_id: UUID) -> ActivationResult`; and `recover(activation_id: UUID) -> ActivationResult`; private ordered steps `preflight`, `stage_scheduler`, `verify_runtime`, `enable_scheduler`, `enable_skill`, and `prove`.

- [ ] **Step 1: Write failing activation-state tests**

Add tests named `test_activation_requires_completed_matching_phase3b_transaction`, `test_activation_requires_ordered_preflight_stage_runtime_scheduler_skill_proof`, `test_activation_enables_scheduler_before_atomically_enabling_only_projectos`, `test_activation_proof_resolves_skill_and_runs_both_triggers_with_fake_gateway`, `test_failure_before_and_after_registry_enable_restores_exact_disabled_bytes_first`, `test_scheduler_enabled_then_skill_or_proof_failure_leaves_no_discovery_or_active_fixture`, `test_recovery_at_every_activation_boundary_is_idempotent`, `test_deactivation_disables_discovery_before_scheduler_teardown`, and `test_activation_journal_contains_only_bounded_local_metadata`.

- [ ] **Step 2: Write failing Phase 3B integration guards**

Add `test_phase3b_upgrade_rollback_and_uninstall_refuse_enabled_registry` to `tests/test_adoption_transaction.py` and assert that deactivation is required before any definition mutation.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_activation_transaction tests.test_adoption_transaction -v`  
Expected: FAIL because activation modules and enabled-entry guards do not exist.

- [ ] **Step 4: Implement canonical local activation persistence**

Store activation journals, exact disabled-registry bytes, scheduler definition bytes/hash, and bounded proof results under `<runtime>/adoption/activations/<activation-id>/`. Use strict parsing, exclusive IDs, atomic writes, legal transitions, and no database/config/private catalog copies.

- [ ] **Step 5: Implement activation and reverse-order recovery**

Use an injected no-op boundary hook for deterministic crash injection at every journal transition and immediately before/after registry replacement. Enable the fixture scheduler before the single atomic registry change. On failure, verify fixture, installation, transaction, registry, and scheduler ownership; restore exact disabled registry bytes first, then disable/remove scheduler fixture state. Deactivation follows the same order and recovery is idempotent.

- [ ] **Step 6: Add Phase 3B enabled-entry guards**

Upgrade, rollback, and uninstall inspect the current registry and reject `enabled:true` with a bounded deactivation-required validation error before snapshot or mutation.

- [ ] **Step 7: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_activation_transaction tests.test_adoption_transaction tests.test_skill_discovery tests.test_scheduler_fixture tests.test_extension_registry -v`  
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
rtk git add src/projectos/adoption/activation_store.py src/projectos/adoption/activation.py src/projectos/adoption/transaction.py src/projectos/adoption/__init__.py tests/test_activation_transaction.py tests/test_adoption_transaction.py
rtk git commit --no-gpg-sign -m "feat: activate ProjectOS runtime in fixtures"
```

### Task 7: Runtime and Fixture-Only Phase 3C CLI

**Files:**
- Modify: `src/projectos/cli.py`
- Create: `tests/test_cli_phase3c.py`

**Interfaces:**
- Consumes: `RuntimeSyncCoordinator`, scheduler adapters, fixture runner, discovery, activation transaction.
- Produces: `runtime sync`; `adoption fixture scheduler render`; `adoption fixture activate`; `adoption fixture deactivate`; `adoption fixture activation-recover`; and `adoption fixture skill inspect` commands from the spec.

- [ ] **Step 1: Write failing CLI tests**

Add tests named `test_runtime_sync_opens_exact_existing_profile_database_without_initialize`, `test_runtime_sync_rejects_fake_gateway_fixture_and_database_mismatch`, `test_runtime_sync_triggers_share_one_json_contract_and_lock`, `test_phase3c_fixture_commands_are_database_lazy_until_runtime_verification`, `test_scheduler_render_is_disabled_and_does_not_execute_native_command`, `test_fixture_activate_inspect_deactivate_round_trip`, `test_activation_failure_returns_exit_three_and_recovery_is_idempotent`, `test_cli_has_no_live_activate_native_runner_enable_or_force_flag`, `test_phase3c_errors_never_echo_profile_path_email_identifier_or_secret`, and `test_phase3a_phase3b_and_catalog_commands_remain_unchanged`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_cli_phase3c -v`  
Expected: FAIL because the Phase 3C parser and dispatch paths do not exist.

- [ ] **Step 3: Implement parser and dispatch**

Special-case `runtime sync` before the existing initialize-on-open database path and call `open_existing`. Keep scheduler render/skill inspect read-only and all activation commands in `DATABASE_FREE_COMMANDS` until their explicit runtime checks open existing local state. Construct only `FixtureSchedulerRunner`; expose no native runner selector.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_cli_phase3c tests.test_cli_phase3b tests.test_cli_phase3a tests.test_cli tests.test_cli_phase2 -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/cli.py tests/test_cli_phase3c.py
rtk git commit --no-gpg-sign -m "feat: expose fixture-only ProjectOS activation"
```

### Task 8: Packaging, Operations, Handoff, and Phase 3C Candidate Gate

**Files:**
- Modify: `tests/test_build_backend.py`
- Modify: `README.md`
- Create: `docs/PHASE3C_OPERATIONS.md`
- Create: `docs/PHASE3C_VERIFICATION.md`
- Modify: `docs/PHASE3B_VERIFICATION.md`
- Modify: `docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md`

**Interfaces:**
- Consumes: all Phase 3C modules and CLI commands.
- Produces: deterministic wheel evidence, fixture activation/deactivation runbook, corrected phase boundaries, and Windows fixture handoff without native activation.

- [ ] **Step 1: Write failing clean-wheel tests**

Add tests named `test_wheel_contains_all_phase3c_modules`, `test_phase3c_wheel_is_byte_identical`, `test_extracted_wheel_completes_fixture_activation_and_deactivation`, and `test_phase3c_wheel_scheduler_skill_and_fixture_evidence_contain_no_private_identifiers_or_secrets`.

- [ ] **Step 2: Run build tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_build_backend -v`  
Expected: FAIL until the extracted-wheel workflow exercises Phase 3C.

- [ ] **Step 3: Complete operations and Windows handoff**

Document prerequisite database/config preparation, exact fixture commands, scheduler artifacts, discovery diagnostics, lock contention, activation recovery, deactivation order, archive retention, and the native-activation prohibition. Update the Windows evidence package to run fixture activation as a standard user without invoking Task Scheduler.

- [ ] **Step 4: Run the Phase 3C candidate gate**

Run:

```bash
rtk /opt/homebrew/bin/python3 -m unittest \
  tests.test_projectos_skill \
  tests.test_runtime_sync \
  tests.test_scheduler_adapters \
  tests.test_scheduler_fixture \
  tests.test_skill_discovery \
  tests.test_activation_transaction \
  tests.test_cli_phase3c \
  tests.test_adoption_fixture \
  tests.test_extension_registry \
  tests.test_adoption_store \
  tests.test_adoption_staging \
  tests.test_adoption_transaction \
  tests.test_cli_phase3b \
  tests.test_cli_phase3a \
  tests.test_extension_bundle \
  tests.test_machine_profile \
  tests.test_process_lock \
  tests.test_sync_service \
  tests.test_build_backend -v
rtk /opt/homebrew/bin/python3 -m compileall -q src build_backend.py
rtk /opt/homebrew/bin/python3 -m pip wheel --no-deps --no-build-isolation -w <fresh-temp-directory> .
```

Expected: focused and affected-regression tests PASS, compilation exits `0`, and a deterministic `py3-none-any` wheel is produced.

- [ ] **Step 5: Scan and record evidence**

Scan every wheel member plus invented skill, scheduler, lock, activation journal, snapshot, proof, and fixture-runner artifact for build/target paths, usernames, hostnames, emails, external identifiers, passwords, credential references, private keys, token patterns, and symlink metadata. Record source revision, Python/platform, test count, wheel size/member count/hash, failure-injection count, fixture lifecycle proof, and remaining Phase 3D real-host gates.

- [ ] **Step 6: Commit**

```bash
rtk git add tests/test_build_backend.py README.md docs/PHASE3C_OPERATIONS.md docs/PHASE3C_VERIFICATION.md docs/PHASE3B_VERIFICATION.md docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md
rtk git commit --no-gpg-sign -m "docs: complete ProjectOS phase 3C handoff"
```

## Phase 3C Completion Gate

Phase 3C stops when all eight tasks are committed and the focused candidate gate passes. The completion report must include:

- commits created;
- focused test counts, candidate count, and compile result;
- deterministic wheel size, member count, and SHA-256;
- skill, scheduler, lock, activation, failure-injection, and extracted-wheel evidence;
- identifier, secret, symlink, shell, and native-execution scan results;
- agent runs, correction rounds, candidate/full-suite executions, and exhaustive implementation rulings;
- confirmation that no live ContextOS, native scheduler, real Google, GAS, Looker, shared-root, or production SQLite state changed;
- confirmation that macOS and Windows scheduler behavior remains rendered/fixture evidence only;
- remaining Phase 3D clean-account and real-Windows activation gates.

Do not begin Phase 3D automatically. Review the Phase 3C evidence and obtain the user's next-phase direction first.
