# ProjectOS Phase 3D-B Host Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the packaged ProjectOS acceptance host flow prepare, simulate, recover, seal, and verify a real native-scheduler transaction while keeping implementation and tests recording-only.

**Architecture:** Acceptance manifest schema version 2 binds the wheel and embedded ContextOS extension bundle in one deterministic archive. A one-shot preparation authority creates durable local inputs, controller adapters reuse the Phase 3B and 3C transactions, and a native-trigger coordinator proves scheduler-originated events before the existing host transaction can seal allowlisted evidence. The separate host module is the only state-changing surface; the ordinary CLI remains build/verify/reconcile only.

**Tech Stack:** Python 3.11+ standard library, SQLite through existing ProjectOS APIs, deterministic ZIP/JSON/SHA-256 artifacts, `unittest`, injected native-process executors, existing GAS Node tests.

**Spec:** `docs/superpowers/specs/2026-09-27-projectos-phase-3d-b-host-execution-design.md`

## Global Constraints

- Work remains detached and local; no push or authenticated external action.
- Implementation and automated tests must not execute `launchctl`, `schtasks.exe`, Google, GAS, Looker, a live ContextOS root, a shared root, or production SQLite.
- Acceptance manifest schema version `2` requires the embedded extension bundle; schema version `1` packages remain structurally verifiable only through their Phase 3D-A code and are not executable by the 3D-B host runner.
- Native process tests inject `RecordingProcessExecutor`; production executor construction occurs only after complete host preflight.
- `prepare` is fixture-local, one-shot, non-elevated, and performs no native action or fixture registry mutation.
- The ordinary `projectos` CLI gains no host preparation, native runner, force, task identifier, production-root, or purge option.
- Production `projectos runtime sync` remains real-gateway-only and unchanged.
- Portable artifacts exclude absolute paths, identities, external identifiers, credentials, command lines, native output, environment state, and raw logs.
- Support state remains `SIMULATED`; macOS and Windows native execution require separate later Owner authorization.
- Python commands use `/opt/homebrew/bin/python3` in this workspace and every shell command is prefixed with `rtk`.

## Review Focus

- A valid outer ZIP containing a changed, extra-member, symlinked, or wrong-release nested extension bundle must fail package verification before preparation; Task 1 tests this.
- Preparation interrupted before its canonical record must leave no reusable partial authority, staged bundle, or identifiers; Task 2 tests every write boundary.
- A process restart must reconstruct controller ownership from journals, while changed registry inventory or transaction IDs stop recovery without deletion; Task 3 tests this.
- Direct probe calls, stale spool events, duplicate barrier entrants, reordered events, and missing native-trigger windows must never count as native evidence; Task 4 tests this.
- A crash after a native effect but before its next journal write must inspect ownership and recover only a hash-matching acceptance task; Task 5 tests this.

---

### Task 1: Bind the ContextOS Extension Bundle into Acceptance Packages

**Files:**
- Modify: `src/projectos/acceptance/model.py`
- Modify: `src/projectos/acceptance/package.py`
- Modify: `src/projectos/acceptance/commands.py`
- Modify: `src/projectos/cli.py`
- Modify: `tests/test_acceptance_package.py`
- Modify: `tests/test_cli_phase3d.py`
- Modify: `tests/test_build_backend.py`

**Interfaces:**
- Produces: `ExtensionBundleMetadata`; manifest schema version `2`; `AcceptancePackageBuilder.build(wheel_path, extension_bundle_path, source_revision, created_at, output_path) -> AcceptancePackage`; `AcceptancePackage.extract_extension_bundle(destination) -> Path`.
- Consumes: `verify_extension_bundle(path, ArtifactPolicy)`, wheel metadata, release manifest, and deterministic archive validation.

- [ ] **Step 1: Write failing package-schema tests**

Add tests named `test_v2_manifest_binds_exact_extension_bundle_metadata`, `test_acceptance_package_contains_exactly_seven_members`, `test_nested_extension_bundle_rejects_hash_inventory_symlink_extra_member_and_release_drift`, `test_extraction_writes_only_verified_bundle_atomically`, and `test_package_build_requires_extension_bundle`. Assert schema `2`, exact nested metadata, and no schema-1 execution fallback.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_acceptance_package tests.test_cli_phase3d tests.test_build_backend -v`
Expected: FAIL because acceptance manifests and package commands do not bind an extension bundle.

- [ ] **Step 3: Implement schema-2 package binding**

Add strict metadata parsing and canonical serialization, inspect the nested archive through the existing extension-bundle verifier, bind its release and skill contract to the ProjectOS version, add it to the outer checksum inventory, and extract its already-verified bytes through an atomic destination write.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_acceptance_package tests.test_extension_bundle tests.test_cli_phase3d tests.test_build_backend -v`
Expected: PASS with deterministic seven-member packages.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/model.py src/projectos/acceptance/package.py src/projectos/acceptance/commands.py src/projectos/cli.py tests/test_acceptance_package.py tests/test_cli_phase3d.py tests/test_build_backend.py
rtk git commit --no-gpg-sign -m "feat: bind ProjectOS extension into acceptance packages"
```

### Task 2: One-Shot Clean-Host Preparation

**Files:**
- Create: `src/projectos/acceptance/preparation.py`
- Modify: `src/projectos/acceptance/profile.py`
- Modify: `src/projectos/acceptance/store.py`
- Modify: `src/projectos/acceptance_host.py`
- Create: `tests/test_acceptance_preparation.py`
- Modify: `tests/test_cli_phase3d.py`

**Interfaces:**
- Produces: `AcceptancePreparationRecord`, `PreparedAcceptance`, `AcceptancePreparer.prepare(request) -> PreparedAcceptance`, and `AcceptancePreparer.open(request) -> PreparedAcceptance`.
- Consumes: verified schema-2 package, `AcceptanceTarget.issue/open`, fixture marker and receipt, fixture `MachineProfile`, `AcceptanceProfile`, and local acceptance store.

- [ ] **Step 1: Write failing preparation tests**

Add tests named `test_prepare_requires_new_authority_exact_acks_fixture_receipt_and_standard_user`, `test_prepare_binds_package_wheel_extension_source_profile_and_host`, `test_prepare_allocates_safe_definition_activation_and_preparation_ids`, `test_prepare_stages_only_verified_extension_below_runtime`, `test_prepare_is_one_shot_and_rejects_symlink_overlap_elevation_and_host_mismatch`, `test_prepare_failure_at_every_write_boundary_leaves_no_reusable_partial_state`, and `test_prepare_emits_one_redacted_json_envelope_without_native_execution`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_acceptance_preparation tests.test_cli_phase3d -v`
Expected: FAIL because preparation state and the host command do not exist.

- [ ] **Step 3: Implement preparation authority and command**

Use canonical records, atomic writes, caller-independent random identifiers, exact package/profile hashes, and a boundary hook for deterministic cleanup tests. Add `prepare` only to `projectos.acceptance_host`; keep its paths explicit and reject every pre-existing output.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_acceptance_preparation tests.test_acceptance_authority tests.test_acceptance_profile tests.test_cli_phase3d -v`
Expected: PASS and recording confirms zero native actions.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/preparation.py src/projectos/acceptance/profile.py src/projectos/acceptance/store.py src/projectos/acceptance_host.py tests/test_acceptance_preparation.py tests/test_cli_phase3d.py
rtk git commit --no-gpg-sign -m "feat: prepare isolated ProjectOS host acceptance"
```

### Task 3: Durable Definition and Activation Controllers

**Files:**
- Create: `src/projectos/acceptance/controllers.py`
- Modify: `src/projectos/adoption/activation_store.py`
- Modify: `src/projectos/adoption/activation.py`
- Create: `tests/test_acceptance_controllers.py`
- Modify: `tests/test_activation_transaction.py`

**Interfaces:**
- Produces: `DefinitionAcceptanceController`, `ActivationAcceptanceController`; optional `activation_id` on `LocalActivationStore.create_journal(...)` and `RuntimeActivation.begin(definition_transaction_id, activation_id=None)`.
- Consumes: preparation record, embedded extension bundle, `AdoptionTransaction`, `RuntimeActivation`, fixture runner, local adoption store, and activation store.

- [ ] **Step 1: Write failing controller tests**

Add tests named `test_definition_controller_runs_existing_adoption_states_with_prepared_id`, `test_activation_controller_runs_existing_activation_states_with_prepared_id`, `test_existing_activation_callers_still_generate_ids`, `test_controllers_reconstruct_active_state_from_persisted_journals`, `test_controller_recovery_is_idempotent_after_process_reconstruction`, and `test_controller_recovery_stops_on_registry_inventory_release_or_id_mismatch`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_acceptance_controllers tests.test_activation_transaction -v`
Expected: FAIL because durable acceptance controllers and supplied activation IDs do not exist.

- [ ] **Step 3: Implement thin controller adapters**

Delegate every definition and activation transition to the existing transactions. Read active state from canonical journals, preserve UUID generation for callers that omit an ID, and reject reuse or cross-transaction binding.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_acceptance_controllers tests.test_activation_transaction tests.test_adoption_transaction tests.test_skill_discovery -v`
Expected: PASS with no duplicated adoption or activation mutation logic.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/controllers.py src/projectos/adoption/activation_store.py src/projectos/adoption/activation.py tests/test_acceptance_controllers.py tests/test_activation_transaction.py
rtk git commit --no-gpg-sign -m "feat: connect acceptance to durable adoption transactions"
```

### Task 4: Native Trigger Windows and Probe Proof

**Files:**
- Create: `src/projectos/acceptance/native_probe.py`
- Modify: `src/projectos/acceptance/native_macos.py`
- Modify: `src/projectos/acceptance/native_windows.py`
- Modify: `src/projectos/acceptance/probe.py`
- Modify: `src/projectos/acceptance/transaction.py`
- Create: `tests/test_native_probe.py`
- Modify: `tests/test_native_scheduler_macos.py`
- Modify: `tests/test_native_scheduler_windows.py`
- Modify: `tests/test_host_acceptance_transaction.py`

**Interfaces:**
- Produces: `MacOSNativeSchedulerRunner.trigger(definition)`, `WindowsNativeSchedulerRunner.trigger(definition)`, `NativeTriggerWindow`, and `NativeProbeController.prove_immediate()` / `.prove_non_overlap()`.
- Consumes: hash-owned enabled scheduler definition, acceptance profile, bounded event spool, receipt-bound barrier, and monotonic timeout.

- [ ] **Step 1: Write failing native-proof tests**

Add tests named `test_native_trigger_requires_enabled_hash_owned_acceptance_task`, `test_macos_trigger_is_one_fixed_kickstart_array`, `test_windows_trigger_is_one_fixed_schtasks_run_array`, `test_immediate_proof_requires_one_event_inside_native_trigger_window`, `test_non_overlap_proof_requires_started_then_second_native_trigger_then_locked`, `test_direct_probe_call_cannot_satisfy_native_case`, and `test_foreign_stale_duplicate_reordered_and_timed_out_events_fail_closed`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_native_probe tests.test_native_scheduler_macos tests.test_native_scheduler_windows tests.test_host_acceptance_transaction -v`
Expected: FAIL because native trigger and trigger-window proof interfaces do not exist.

- [ ] **Step 3: Implement trigger-only runner operations and coordinator**

Keep `SchedulerAction` unchanged. Trigger only an already enabled matching task, record safe local window identifiers before effect, wait through bounded polling, and replace the host transaction's direct `ProbeController.run(case_id)` calls with typed immediate and non-overlap proof results.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_native_probe tests.test_native_scheduler_macos tests.test_native_scheduler_windows tests.test_acceptance_probe tests.test_process_lock tests.test_host_acceptance_transaction -v`
Expected: PASS using recording executors only.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/native_probe.py src/projectos/acceptance/native_macos.py src/projectos/acceptance/native_windows.py src/projectos/acceptance/probe.py src/projectos/acceptance/transaction.py tests/test_native_probe.py tests/test_native_scheduler_macos.py tests/test_native_scheduler_windows.py tests/test_host_acceptance_transaction.py
rtk git commit --no-gpg-sign -m "feat: prove scheduler-originated acceptance probes"
```

### Task 5: Executable Host Context, Run, and Recovery

**Files:**
- Create: `src/projectos/acceptance/host_context.py`
- Modify: `src/projectos/acceptance/journal.py`
- Modify: `src/projectos/acceptance/transaction.py`
- Modify: `src/projectos/acceptance_host.py`
- Create: `tests/test_acceptance_host_context.py`
- Modify: `tests/test_cli_phase3d.py`
- Modify: `tests/test_host_acceptance_transaction.py`

**Interfaces:**
- Produces: `HostAcceptanceContextFactory.preflight(request) -> PreparedHostContext`, `.execution(request, executor_factory) -> HostAcceptanceContext`, `run_prepared_acceptance(request) -> HostAcceptanceResult`, and `recover_prepared_acceptance(request, run_id) -> HostAcceptanceResult`.
- Consumes: preparation, controllers, native runner, native probe controller, disposable database health, package/profile equivalence, and host journal.

- [ ] **Step 1: Write failing host-run tests**

Add tests named `test_preflight_constructs_no_subprocess_executor_and_returns_exact_actions`, `test_run_constructs_executor_only_after_complete_preflight`, `test_run_emits_run_id_after_first_journal_and_maps_terminal_exit_codes`, `test_recover_reconstructs_all_ownership_from_durable_state`, `test_crash_after_each_native_effect_recovers_only_matching_task`, `test_foreign_task_registry_inventory_or_release_mismatch_preserves_uncertain_state`, and `test_ordinary_cli_still_cannot_reach_prepare_run_or_recover`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_acceptance_host_context tests.test_cli_phase3d tests.test_host_acceptance_transaction -v`
Expected: FAIL because host execution remains blocked and no durable context factory exists.

- [ ] **Step 3: Implement the context factory and command execution**

Centralize all shared validation before executor construction, use `SubprocessNativeExecutor` only through the injected factory, persist effect intent before each native call, inspect after uncertain effects, and return one redacted JSON envelope with exits `0`, `1`, `2`, or `3`.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_acceptance_host_context tests.test_cli_phase3d tests.test_host_acceptance_transaction tests.test_acceptance_controllers tests.test_native_probe -v`
Expected: PASS with recording executors and no host command execution.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/host_context.py src/projectos/acceptance/journal.py src/projectos/acceptance/transaction.py src/projectos/acceptance_host.py tests/test_acceptance_host_context.py tests/test_cli_phase3d.py tests/test_host_acceptance_transaction.py
rtk git commit --no-gpg-sign -m "feat: execute guarded ProjectOS host acceptance"
```

### Task 6: Collect and Seal Native Host Evidence

**Files:**
- Create: `src/projectos/acceptance/collector.py`
- Modify: `src/projectos/acceptance/evidence.py`
- Modify: `src/projectos/acceptance/reconcile.py`
- Modify: `src/projectos/acceptance/transaction.py`
- Create: `tests/test_acceptance_collector.py`
- Modify: `tests/test_acceptance_evidence.py`
- Modify: `tests/test_acceptance_reconcile.py`

**Interfaces:**
- Produces: `HostEvidenceCollector.collect(context, result) -> HostAcceptanceRecord` and `.seal(context, result, output_path) -> AcceptanceEvidence`.
- Consumes: preparation hash, extension-bundle hash, typed transaction history, scheduler transitions, native trigger windows, probe events, cleanup inspection, and existing evidence builder.

- [ ] **Step 1: Write failing collector tests**

Add tests named `test_collector_maps_every_required_case_from_one_typed_durable_fact`, `test_native_cases_require_matching_native_trigger_windows`, `test_record_binds_preparation_and_extension_bundle_hashes`, `test_sealing_requires_absent_task_disabled_registry_rollback_and_database_health`, `test_collector_never_copies_commands_paths_identities_native_output_or_raw_logs`, and `test_verifier_and_reconciler_reject_old_release_or_mismatched_extension_bundle`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_acceptance_collector tests.test_acceptance_evidence tests.test_acceptance_reconcile -v`
Expected: FAIL because no typed collector or extension-bundle evidence binding exists.

- [ ] **Step 3: Implement evidence collection and sealing**

Map allowlisted facts explicitly, add strict new record fields, seal only after cleanup facts exist, and keep all diagnostics outside the archive. Update verification and reconciliation to require one schema-2 release and matching extension bundle.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_acceptance_collector tests.test_acceptance_evidence tests.test_acceptance_reconcile tests.test_diagnostics tests.test_host_acceptance_transaction -v`
Expected: PASS with deterministic, identifier-clean evidence.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/collector.py src/projectos/acceptance/evidence.py src/projectos/acceptance/reconcile.py src/projectos/acceptance/transaction.py tests/test_acceptance_collector.py tests/test_acceptance_evidence.py tests/test_acceptance_reconcile.py
rtk git commit --no-gpg-sign -m "feat: seal native ProjectOS acceptance evidence"
```

### Task 7: Installed-Wheel Flow, Operator Handoff, and Release Candidate

**Files:**
- Modify: `tests/test_acceptance_installed.py`
- Modify: `tests/test_build_backend.py`
- Modify: `docs/PHASE3D_HOST_OPERATIONS.md`
- Modify: `src/projectos/acceptance/assets/docs/PHASE3D_HOST_OPERATIONS.md`
- Create: `docs/PHASE3D_B_IMPLEMENTATION_AND_TROUBLESHOOTING.md`
- Create: `docs/PHASE3D_B_VERIFICATION.md`
- Modify: `docs/PHASE3D_VERIFICATION.md`
- Modify: `docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: all Tasks 1-6 interfaces.
- Produces: source-checkout-independent preparation/simulation/recovery/evidence flow and complete macOS/Windows operator and Claude troubleshooting handoff.

- [ ] **Step 1: Write failing installed-wheel tests**

Add tests named `test_extracted_wheel_prepares_schema2_package_without_source_checkout`, `test_extracted_wheel_simulates_run_with_recording_executor_and_native_trigger_windows`, `test_extracted_wheel_recovers_each_persisted_boundary_after_process_reconstruction`, `test_extracted_wheel_seals_verifies_and_reconciles_native_shaped_evidence`, and `test_installed_flow_never_constructs_network_client_or_executes_native_command`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_acceptance_installed tests.test_build_backend -v`
Expected: FAIL because the installed wheel does not yet complete the prepared host flow.

- [ ] **Step 3: Complete operations and troubleshooting documents**

Document package/hash verification, offline installation, fixture creation, preparation, read-only preflight, the separate authorization before native `run`, recovery, evidence return, durable-state inspection, bounded error codes, and exact macOS/Windows differences. Keep the packaged operations document byte-identical to the repository version and status `SIMULATED`.

- [ ] **Step 4: Run the Phase 3D-B affected regression gate**

Run:

```bash
rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest \
  tests.test_acceptance_package \
  tests.test_acceptance_preparation \
  tests.test_acceptance_controllers \
  tests.test_native_probe \
  tests.test_native_scheduler_macos \
  tests.test_native_scheduler_windows \
  tests.test_host_acceptance_transaction \
  tests.test_acceptance_host_context \
  tests.test_acceptance_collector \
  tests.test_acceptance_evidence \
  tests.test_acceptance_reconcile \
  tests.test_acceptance_installed \
  tests.test_cli_phase3d \
  tests.test_acceptance_authority \
  tests.test_acceptance_profile \
  tests.test_acceptance_probe \
  tests.test_scheduler_equivalence \
  tests.test_activation_transaction \
  tests.test_adoption_transaction \
  tests.test_skill_discovery \
  tests.test_scheduler_fixture \
  tests.test_runtime_sync \
  tests.test_process_lock \
  tests.test_build_backend \
  tests.test_diagnostics -v
```

Expected: PASS with recording executors only and no network call.

- [ ] **Step 5: Run the complete release-candidate gate once**

```bash
rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v
rtk node --test gas/test/*.test.js
rtk /opt/homebrew/bin/python3 -m compileall -q src build_backend.py
```

Expected: every Python and GAS test passes and compilation exits `0`. Repeat only after the single allowed correction round when the final candidate is ready.

- [ ] **Step 6: Build and scan final artifacts**

Build the wheel, extension bundle, schema-2 acceptance package, simulated host evidence, and reconciliation report in fresh temporary roots. Record source revision, test counts, sizes, member counts, SHA-256 hashes, failure-injection boundaries, recording-executor actions, and support state `SIMULATED`. Scan all portable and local invented state for identifiers, secrets, path escape, symlinks, shell execution, unexpected native execution, and network access.

- [ ] **Step 7: Commit**

```bash
rtk git add tests/test_acceptance_installed.py tests/test_build_backend.py docs/PHASE3D_HOST_OPERATIONS.md src/projectos/acceptance/assets/docs/PHASE3D_HOST_OPERATIONS.md docs/PHASE3D_B_IMPLEMENTATION_AND_TROUBLESHOOTING.md docs/PHASE3D_B_VERIFICATION.md docs/PHASE3D_VERIFICATION.md docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md README.md
rtk git commit --no-gpg-sign -m "docs: complete ProjectOS phase 3D-B implementation handoff"
```

## Completion Gate

Implementation stops when all seven tasks are committed, focused and affected gates pass, the complete Python and GAS suites pass once on the final candidate, deterministic artifacts verify, simulated run and recovery work from the installed wheel, and reconciliation remains `SIMULATED`.

The completion report must include every commit from `5a4d65c`, focused and complete test counts, compilation result, artifact hashes and inventories, failure-injection and recording-action counts, scan results, agent runs, correction rounds, full-suite executions, implementation rulings, and confirmation that no live ContextOS, native scheduler, Google, GAS, Looker, shared-root, or production SQLite state changed.

Do not execute Phase 3D-B natively, advance platform support status, push, merge, or remove the detached worktree automatically.
