# ProjectOS Phase 3D-A Clean-Host Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local-only acceptance package, native scheduler runners, acceptance probe, host transaction, sanitized evidence, and reconciliation tooling required before separately authorized macOS and Windows host runs.

**Architecture:** A new `projectos.acceptance` package owns portable acceptance data, package assets, host authority, injected native runners, transaction state, and evidence. The ordinary CLI can only build and verify packages/evidence; a separate `projectos.acceptance_host` module owns gated native execution. An acceptance-only probe reuses the existing runtime coordinator with an in-memory fake gateway while production `runtime sync` remains unchanged.

**Tech Stack:** Python 3.11+ standard library, SQLite through existing ProjectOS APIs, deterministic ZIP/JSON/SHA-256 artifacts, `unittest`, macOS `launchctl` argument arrays, Windows `schtasks.exe` argument arrays, existing GAS Node tests.

**Spec:** `docs/superpowers/specs/2026-09-27-projectos-phase-3d-clean-host-acceptance-design.md`

## Global Constraints

- Work remains detached and local; no push or authenticated external action.
- Phase 3D-A must not execute `launchctl`, `schtasks`, Google, GAS, Looker, or a live ContextOS command.
- Native lifecycle tests use injected recording executors only.
- Production `projectos runtime sync` remains real-gateway-only and gains no fake, fixture, or acceptance switch.
- Native state is restricted to `com.contextos.projectos.acceptance.sync` and `ContextOS\ProjectOS\Acceptance\Sync`.
- Host execution requires `CLEAN_HOST_NATIVE_ACCEPTANCE`, clean fixture and acceptance receipts, non-elevated standard-user state, and no force option.
- Acceptance runtime, database, configuration, logs, staging, raw diagnostics, and evidence spool remain local and outside ContextOS/shared roots.
- Portable evidence contains no absolute path, username, hostname, machine identifier, email, external identifier, command line, native output, credential reference, token, password, or private key.
- Support status remains `SIMULATED` until separately authorized real-host evidence verifies.
- Python commands use `/opt/homebrew/bin/python3` in this build workspace and every shell command is prefixed with `rtk`.

## Review Focus

- A pre-existing native task with the acceptance name but a foreign definition must stop preflight and must never be disabled, replaced, or removed; Tasks 4, 5, and 6 test this.
- A crash after native enablement but before the next journal write must be discovered from native inspection and recovered without deleting mismatched state; Task 6 tests every persisted boundary and this unjournaled edge.
- Acceptance and evidence ZIPs with traversal, case-insensitive duplicates, symlink metadata, malformed canonical JSON, or extra members must fail closed; Tasks 1 and 7 test each archive shape.
- Localized, truncated, contradictory, or unexpected native command output must become a bounded failure rather than an inferred success; Tasks 4 and 5 test parser failure behavior.
- Host timestamps may be equal or clock-adjusted but must remain canonical and internally ordered by recorded sequence; Task 7 tests deterministic reconciliation without trusting wall-clock duration.

---

### Task 1: Acceptance Manifest and Deterministic Package

**Files:**
- Create: `src/projectos/acceptance/__init__.py`
- Create: `src/projectos/acceptance/model.py`
- Create: `src/projectos/acceptance/package.py`
- Create: `src/projectos/acceptance/assets/macos/run-projectos-acceptance.sh`
- Create: `src/projectos/acceptance/assets/windows/Run-ProjectOSAcceptance.ps1`
- Create: `src/projectos/acceptance/assets/docs/PHASE3D_HOST_OPERATIONS.md`
- Modify: `build_backend.py`
- Modify: `pyproject.toml`
- Create: `tests/test_acceptance_package.py`
- Modify: `tests/test_build_backend.py`

**Interfaces:**
- Produces: `REQUIRED_ACCEPTANCE_CASES: tuple[str, ...]`, `SupportState`, `AcceptanceManifest.from_mapping()`, `AcceptanceManifest.canonical_bytes()`, `AcceptancePackage`, `AcceptancePackageBuilder.build(wheel_path, source_revision, created_at, output_path) -> AcceptancePackage`, and `verify_acceptance_package(path) -> AcceptancePackage`.
- Consumes: ProjectOS version, deterministic wheel metadata, `HostFamily`, and existing secret/path validation primitives.

- [ ] **Step 1: Write failing manifest and package tests**

Add tests named `test_acceptance_manifest_has_exact_canonical_release_and_case_fields`, `test_acceptance_package_is_byte_identical`, `test_package_contains_only_manifest_wheel_assets_operations_and_hashes`, `test_package_rejects_wrong_wheel_hash_extra_member_casefold_duplicate_traversal_and_symlink`, `test_package_contains_no_private_identifier_or_secret`, and `test_wheel_contains_acceptance_assets_as_regular_members`. Assert the exact six package member groups and all required case IDs from the spec.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_acceptance_package tests.test_build_backend -v`  
Expected: FAIL because `projectos.acceptance` and its assets do not exist.

- [ ] **Step 3: Implement the model and deterministic package**

Implement strict field sets, canonical JSON, deterministic ZIP metadata, sorted SHA-256 inventory, source/wheel binding, portable member validation, case-insensitive duplicate rejection, symlink rejection, and identifier/secret scans. Extend the dependency-free build backend only for the reviewed `.sh`, `.ps1`, and `.md` acceptance assets below `projectos/acceptance/assets/`; continue rejecting every source symlink.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_acceptance_package tests.test_build_backend tests.test_extension_bundle -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance build_backend.py pyproject.toml tests/test_acceptance_package.py tests/test_build_backend.py
rtk git commit --no-gpg-sign -m "feat: build deterministic ProjectOS acceptance packages"
```

### Task 2: Clean-Host Authority, Receipt, Profile, and Local Store

**Files:**
- Create: `src/projectos/acceptance/authority.py`
- Create: `src/projectos/acceptance/profile.py`
- Create: `src/projectos/acceptance/store.py`
- Create: `tests/test_acceptance_authority.py`
- Create: `tests/test_acceptance_profile.py`

**Interfaces:**
- Consumes: `AcceptanceManifest`, `MachineProfile`, `FixtureInstallationTarget`, `HostPathPolicy`, fixture receipts, and local adoption stores.
- Produces: `HostSession`, `detect_host_session() -> HostSession`, `AcceptanceTarget.issue(root, runtime_root, host_family) -> AcceptanceTarget`, `AcceptanceTarget.open(root, runtime_root, acknowledgement, session) -> AcceptanceTarget`, `AcceptanceProfile.from_machine_profile(...)`, `AcceptanceProfile.canonical_bytes()`, `acceptance_machine_profile(profile) -> MachineProfile`, and `LocalAcceptanceStore.open(target, profile) -> LocalAcceptanceStore`.

- [ ] **Step 1: Write failing authority and profile tests**

Add tests named `test_acceptance_target_requires_new_empty_non_symlink_root_and_exact_ack`, `test_acceptance_receipt_is_same_host_runtime_bound_and_canonical`, `test_acceptance_target_rejects_fixture_contextos_shared_or_overlapping_roots`, `test_acceptance_authority_rejects_elevated_or_wrong_host_session`, `test_acceptance_profile_uses_only_acceptance_entrypoint_and_task_identifier`, `test_acceptance_profile_rejects_production_task_and_path_escape`, `test_acceptance_store_is_local_exclusive_and_never_initializes_database`, and `test_acceptance_metadata_contains_no_private_identifiers_or_secrets`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_acceptance_authority tests.test_acceptance_profile -v`  
Expected: FAIL because the authority, profile, and store interfaces do not exist.

- [ ] **Step 3: Implement authority and canonical local state**

Use a marker and same-host receipt separate from the Phase 3 fixture receipt. Store only safe hashes/IDs in canonical journals; keep resolved paths solely in the local profile. Replace exactly the machine profile entrypoint module and scheduler task ID for acceptance, preserving every other production runtime field.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_acceptance_authority tests.test_acceptance_profile tests.test_adoption_fixture tests.test_machine_profile tests.test_host_paths -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/authority.py src/projectos/acceptance/profile.py src/projectos/acceptance/store.py tests/test_acceptance_authority.py tests/test_acceptance_profile.py
rtk git commit --no-gpg-sign -m "feat: bind clean-host ProjectOS acceptance state"
```

### Task 3: Acceptance Probe and Scheduler Structural Equivalence

**Files:**
- Create: `src/projectos/acceptance/probe.py`
- Create: `src/projectos/acceptance/equivalence.py`
- Create: `src/projectos/acceptance_probe.py`
- Create: `tests/test_acceptance_probe.py`
- Create: `tests/test_scheduler_equivalence.py`

**Interfaces:**
- Consumes: `AcceptanceTarget`, `AcceptanceProfile`, `RuntimeSyncCoordinator`, `RuntimeTrigger`, canonical `FakeGoogleGateway`, scheduler adapters, and the local evidence spool.
- Produces: `AcceptanceProbe.run(profile_path, database_path, trigger, case_id) -> ProbeResult`, `acceptance_probe.main(argv) -> int`, `DefinitionEquivalence`, and `compare_scheduler_definitions(production, acceptance) -> DefinitionEquivalence`.

- [ ] **Step 1: Write failing probe and equivalence tests**

Add tests named `test_probe_refuses_without_receipt_acceptance_entrypoint_and_local_paths`, `test_probe_has_no_gateway_fixture_network_or_production_alias`, `test_probe_runs_complete_and_locked_through_one_runtime_coordinator_and_lock`, `test_probe_barrier_is_receipt_bound_bounded_and_records_only_one_started_invocation`, `test_probe_events_are_canonical_bounded_and_identifier_clean`, `test_acceptance_definition_diff_allows_only_task_id_and_entrypoint_module`, and `test_equivalence_rejects_timing_path_argument_policy_or_definition_drift`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_acceptance_probe tests.test_scheduler_equivalence -v`  
Expected: FAIL because the acceptance probe and comparator do not exist.

- [ ] **Step 3: Implement the probe and comparator**

Keep fake gateway creation inside the acceptance probe, accept no arbitrary fixture input, and delegate all synchronization to `RuntimeSyncCoordinator`. Implement an atomic append-only bounded event spool and monotonic bounded barrier. Normalize only the two spec-authorized definition differences before exact comparison.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_acceptance_probe tests.test_scheduler_equivalence tests.test_runtime_sync tests.test_scheduler_adapters tests.test_process_lock tests.test_sync_service -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/probe.py src/projectos/acceptance/equivalence.py src/projectos/acceptance_probe.py tests/test_acceptance_probe.py tests/test_scheduler_equivalence.py
rtk git commit --no-gpg-sign -m "feat: add isolated ProjectOS acceptance probe"
```

### Task 4: macOS Native Acceptance Runner

**Files:**
- Create: `src/projectos/acceptance/native.py`
- Create: `src/projectos/acceptance/native_macos.py`
- Create: `tests/test_native_scheduler_macos.py`

**Interfaces:**
- Consumes: `AcceptanceTarget`, acceptance `SchedulerDefinition`, `SchedulerAction`, and `NativeProcessExecutor.run(argv: tuple[str, ...], timeout_seconds: int) -> NativeProcessResult`.
- Produces: `NativeProcessResult`, `RecordingProcessExecutor`, `SubprocessNativeExecutor.run(argv, timeout_seconds) -> NativeProcessResult`, `MacOSNativeSchedulerRunner.perform(action, definition) -> SchedulerInspection`, and `MacOSNativeSchedulerRunner.planned_actions(definition) -> tuple[tuple[str, ...], ...]`.

- [ ] **Step 1: Write failing macOS runner tests**

Add tests named `test_subprocess_executor_uses_argument_array_shell_false_bounded_timeout_and_redacts_output`, `test_macos_runner_uses_only_fixed_per_user_launchctl_argument_arrays`, `test_macos_runner_never_uses_shell_sudo_or_system_launch_locations`, `test_macos_runner_stages_disabled_then_enable_kickstart_disable_bootout`, `test_macos_runner_refuses_root_production_task_existing_foreign_task_and_changed_hash`, `test_macos_runner_is_idempotent_only_for_owned_definition`, and `test_macos_runner_fails_closed_on_localized_truncated_or_contradictory_output`. Mock the subprocess boundary so no actual native command runs.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_native_scheduler_macos -v`  
Expected: FAIL because the native executor and macOS runner do not exist.

- [ ] **Step 3: Implement the executor contract and macOS runner**

Use only `gui/<uid>` domains, verified plist bytes below acceptance runtime, bounded timeouts, fixed action arrays, safe inspection codes, and definition-hash ownership. Implement the production executor as a narrow `subprocess.run` adapter with `shell=False`, no environment override, bounded captured output, and safe result codes; every 3D-A lifecycle test injects `RecordingProcessExecutor` or mocks that subprocess boundary.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_native_scheduler_macos tests.test_scheduler_adapters tests.test_scheduler_fixture -v`  
Expected: PASS and recording history contains the exact lifecycle without native execution.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/native.py src/projectos/acceptance/native_macos.py tests/test_native_scheduler_macos.py
rtk git commit --no-gpg-sign -m "feat: plan guarded macOS acceptance scheduling"
```

### Task 5: Windows Native Acceptance Runner

**Files:**
- Create: `src/projectos/acceptance/native_windows.py`
- Create: `tests/test_native_scheduler_windows.py`

**Interfaces:**
- Consumes: Task 4's executor contract, `AcceptanceTarget`, acceptance `SchedulerDefinition`, and `SchedulerAction`.
- Produces: `WindowsNativeSchedulerRunner.perform(action, definition) -> SchedulerInspection` and `WindowsNativeSchedulerRunner.planned_actions(definition) -> tuple[tuple[str, ...], ...]`.

- [ ] **Step 1: Write failing Windows runner tests**

Add tests named `test_windows_runner_uses_only_fixed_schtasks_argument_arrays`, `test_windows_runner_imports_verified_xml_with_interactive_least_privilege_and_no_password`, `test_windows_runner_create_disabled_enable_run_query_disable_delete`, `test_windows_runner_refuses_elevation_production_task_existing_foreign_task_and_changed_hash`, `test_windows_runner_requires_no_powershell_com_developer_mode_or_symlink`, and `test_windows_runner_fails_closed_on_localized_truncated_or_contradictory_output`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_native_scheduler_windows -v`  
Expected: FAIL because the Windows native runner does not exist.

- [ ] **Step 3: Implement the Windows runner**

Use `schtasks.exe` arrays only, the fixed acceptance task path, verified XML below the acceptance runtime, bounded execution, explicit safe state parsing, and definition-hash ownership. Do not import `subprocess` platform behavior, PowerShell, COM, or `msvcrt` until the injected production executor is explicitly used on Windows.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_native_scheduler_windows tests.test_scheduler_adapters tests.test_scheduler_fixture tests.test_host_paths -v`  
Expected: PASS on macOS using simulated Windows paths and recording execution only.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/native_windows.py tests/test_native_scheduler_windows.py
rtk git commit --no-gpg-sign -m "feat: plan guarded Windows acceptance scheduling"
```

### Task 6: Host Acceptance Transaction and Recovery

**Files:**
- Create: `src/projectos/acceptance/journal.py`
- Create: `src/projectos/acceptance/transaction.py`
- Create: `tests/test_host_acceptance_transaction.py`

**Interfaces:**
- Consumes: `AcceptanceTarget`, `AcceptanceProfile`, `LocalAcceptanceStore`, verified package/extension bundle, Phase 3B `AdoptionTransaction`, Phase 3C `RuntimeActivation`, scheduler adapter, native runner, probe, and boundary hook.
- Produces: `HostAcceptanceState`, `HostAcceptanceJournal`, `HostAcceptanceContext`, `HostAcceptanceTransaction.begin(context, boundary_hook=noop)`, `.resume(run_id)`, `.recover(run_id)`, and `HostAcceptanceResult`.

- [ ] **Step 1: Write failing transaction tests**

Add tests named `test_host_transaction_requires_verified_package_clean_authority_and_disposable_database`, `test_host_transaction_runs_every_state_in_exact_order`, `test_registry_is_disabled_before_native_scheduler_teardown`, `test_transaction_proves_immediate_lock_non_overlap_schedule_discovery_cleanup_and_database_health`, `test_foreign_existing_task_is_never_changed`, `test_recovery_at_every_persisted_boundary_is_idempotent`, `test_recovery_after_native_enable_before_journal_write_inspects_and_removes_owned_task`, `test_recovery_stops_on_definition_registry_or_inventory_mismatch`, and `test_host_journal_contains_only_bounded_identifier_clean_metadata`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_host_acceptance_transaction -v`  
Expected: FAIL because host transaction state and orchestration do not exist.

- [ ] **Step 3: Implement journal and transaction orchestration**

Persist before/after ownership needed for recovery, reuse Phase 3B and 3C transactions rather than duplicating their mutations, and use injected runner/probe controllers. On ordinary failure, record `FAILED` and recover; crash injection uses the existing boundary-hook pattern so tests can verify explicit resume/recovery.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_host_acceptance_transaction tests.test_activation_transaction tests.test_adoption_transaction tests.test_skill_discovery tests.test_scheduler_fixture -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/journal.py src/projectos/acceptance/transaction.py tests/test_host_acceptance_transaction.py
rtk git commit --no-gpg-sign -m "feat: transact clean-host ProjectOS acceptance"
```

### Task 7: Sanitized Evidence, Verification, and Reconciliation

**Files:**
- Create: `src/projectos/acceptance/evidence.py`
- Create: `src/projectos/acceptance/reconcile.py`
- Create: `tests/test_acceptance_evidence.py`
- Create: `tests/test_acceptance_reconcile.py`

**Interfaces:**
- Consumes: verified manifest/package, terminal host journal, bounded probe events, scheduler inspections, safe host-version facts, and required case IDs.
- Produces: `AcceptanceCaseResult`, `HostAcceptanceRecord`, `AcceptanceEvidenceBuilder.build(...) -> AcceptanceEvidence`, `AcceptanceEvidenceVerifier.verify(path, manifest) -> VerifiedHostEvidence`, and `AcceptanceReconciler.reconcile(manifest, records) -> ReconciliationReport`.

- [ ] **Step 1: Write failing evidence and reconciliation tests**

Add tests named `test_evidence_contains_exact_allowlisted_fields_cases_hashes_and_cleanup`, `test_evidence_excludes_paths_identities_external_ids_commands_native_output_and_raw_logs`, `test_evidence_archive_rejects_traversal_casefold_duplicate_symlink_extra_binary_and_bad_hash`, `test_verifier_rejects_missing_duplicate_unknown_skipped_failed_or_simulated_native_case`, `test_verifier_rejects_release_host_elevation_definition_and_cleanup_mismatch`, `test_equal_or_adjusted_wall_timestamps_use_sequence_not_duration`, `test_reconcile_zero_macos_windows_and_both_records_to_exact_support_states`, and `test_reconcile_rejects_mixed_release_or_duplicate_host_records`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_acceptance_evidence tests.test_acceptance_reconcile -v`  
Expected: FAIL because evidence and reconciliation interfaces do not exist.

- [ ] **Step 3: Implement safe evidence and fail-closed verification**

Build evidence from typed allowlisted events, not copied logs. Use sequence numbers for ordering, canonical JSON and deterministic ZIP metadata, explicit excluded-artifact names, cross-platform path-pattern scans, exact attachment inventories, and matching release/host constraints. Treat integrity as SHA-256 binding only and never label it a signature.

- [ ] **Step 4: Run focused verification**

Run: `rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest tests.test_acceptance_evidence tests.test_acceptance_reconcile tests.test_acceptance_package tests.test_diagnostics -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/acceptance/evidence.py src/projectos/acceptance/reconcile.py tests/test_acceptance_evidence.py tests/test_acceptance_reconcile.py
rtk git commit --no-gpg-sign -m "feat: verify ProjectOS host acceptance evidence"
```

### Task 8: Local CLI, Separate Host Module, Installed-Wheel Flow, and Phase 3 Release Candidate

**Files:**
- Create: `src/projectos/acceptance/commands.py`
- Create: `src/projectos/acceptance_host.py`
- Modify: `src/projectos/cli.py`
- Create: `tests/test_cli_phase3d.py`
- Create: `tests/test_acceptance_installed.py`
- Modify: `tests/test_build_backend.py`
- Create: `docs/PHASE3D_HOST_OPERATIONS.md`
- Modify: `src/projectos/acceptance/assets/docs/PHASE3D_HOST_OPERATIONS.md`
- Create: `docs/PHASE3D_VERIFICATION.md`
- Modify: `docs/PHASE3C_VERIFICATION.md`
- Modify: `docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: all Tasks 1–7 interfaces.
- Produces: ordinary local-only `acceptance package build|verify`, `acceptance evidence verify`, and `acceptance reconcile` commands; separate `acceptance_host preflight|run|recover`; installed-wheel acceptance package/probe/evidence flow; operator and verification documents.

- [ ] **Step 1: Write failing CLI and installed-wheel tests**

Add tests named `test_ordinary_cli_exposes_only_build_and_read_only_acceptance_commands`, `test_ordinary_cli_has_no_native_run_runner_force_or_production_task_option`, `test_host_module_requires_exact_ack_receipts_manifest_profile_and_evidence_root`, `test_host_preflight_is_read_only_and_returns_planned_native_actions`, `test_host_run_is_unreachable_through_projectos_cli`, `test_phase3d_errors_are_one_json_envelope_and_never_echo_private_values`, `test_prior_cli_contracts_remain_unchanged`, `test_extracted_wheel_builds_and_verifies_acceptance_package`, `test_extracted_wheel_runs_probe_and_simulated_lifecycle_without_native_or_network_calls`, and `test_extracted_wheel_builds_verifies_and_reconciles_sanitized_evidence`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `rtk /opt/homebrew/bin/python3 -m unittest tests.test_cli_phase3d tests.test_acceptance_installed -v`  
Expected: FAIL because the command adapters and host module do not exist.

- [ ] **Step 3: Implement command adapters and host module**

Keep ordinary CLI dispatch free of native runner construction. The separate host module constructs a platform runner only after complete preflight; tests patch its executor factory and assert recording-only behavior. Preserve exit `2` for pre-transaction validation, exit `3` once a host journal exists or acceptance is incomplete, and redacted exit `1` for unexpected errors.

- [ ] **Step 4: Complete operations and handoff documents**

Document package verification, isolated fixture/database preparation, preflight planned actions, exact 3D-B authorization boundary, recovery, retained local artifacts, safe evidence return, macOS standard-user workflow, Windows standard-user workflow, and reconciliation. Keep the packaged operations asset byte-identical to the repository handoff document, mark status `SIMULATED`, and do not include a command that targets an existing ContextOS root or real Google configuration.

- [ ] **Step 5: Run focused and affected-regression verification**

Run:

```bash
rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest \
  tests.test_cli_phase3d \
  tests.test_acceptance_installed \
  tests.test_acceptance_package \
  tests.test_acceptance_authority \
  tests.test_acceptance_profile \
  tests.test_acceptance_probe \
  tests.test_scheduler_equivalence \
  tests.test_native_scheduler_macos \
  tests.test_native_scheduler_windows \
  tests.test_host_acceptance_transaction \
  tests.test_acceptance_evidence \
  tests.test_acceptance_reconcile \
  tests.test_cli_phase3c \
  tests.test_build_backend -v
```

Expected: PASS with no native command or network call.

- [ ] **Step 6: Run the complete Phase 3 release-candidate gate once**

Run:

```bash
rtk /opt/homebrew/bin/python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v
rtk node --test gas/test/*.test.js
rtk /opt/homebrew/bin/python3 -m compileall -q src build_backend.py
```

Expected: every Python and GAS test passes and compilation exits `0`. This is the one complete ProjectOS regression execution for the Phase 3 release-candidate boundary; repeat it only after a correction when the final candidate is ready.

- [ ] **Step 7: Build and scan final artifacts**

Build the wheel and acceptance package into fresh temporary directories. Record source revision, Python/platform, Python and GAS test counts, wheel size/member count/SHA-256, acceptance package size/member count/SHA-256, failure-injection count, recording-executor action count, and support state `SIMULATED`. Scan all portable members and invented journals/profiles/probe events/evidence for identifiers, secrets, paths, symlinks, shell execution, native execution, and network access.

- [ ] **Step 8: Commit**

```bash
rtk git add src/projectos/acceptance/commands.py src/projectos/acceptance/assets/docs/PHASE3D_HOST_OPERATIONS.md src/projectos/acceptance_host.py src/projectos/cli.py tests/test_cli_phase3d.py tests/test_acceptance_installed.py tests/test_build_backend.py docs/PHASE3D_HOST_OPERATIONS.md docs/PHASE3D_VERIFICATION.md docs/PHASE3C_VERIFICATION.md docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md README.md
rtk git commit --no-gpg-sign -m "docs: complete ProjectOS phase 3D-A handoff"
```

## Phase 3D-A Completion Gate

Phase 3D-A stops when all eight tasks are committed, focused gates pass, the complete Python and GAS regression suites pass once on the final candidate, deterministic artifacts verify, and the reconciliation report remains `SIMULATED`.

The completion report must include:

- every commit created from base `8d546eb`;
- focused, affected-regression, complete Python, and GAS test counts;
- compilation result;
- wheel and acceptance-package sizes, member counts, and SHA-256 hashes;
- package, authority, probe, equivalence, native recording, transaction recovery, evidence, installed-wheel, identifier, secret, path, symlink, shell, native-execution, and network scan results;
- agent runs, correction rounds, candidate/full-suite executions, and implementation rulings;
- confirmation that no live ContextOS, native scheduler, real Google, GAS, Looker, shared-root, or production SQLite state changed;
- explicit status `SIMULATED`;
- the separate approvals still required for macOS 3D-B and Windows 3D-B.

Do not run Phase 3D-B, install a native scheduler, or claim platform verification automatically.
