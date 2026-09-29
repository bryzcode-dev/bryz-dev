# ProjectOS Phase 3B Transaction Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the fail-closed ProjectOS transaction engine that persists target-local adoption state and proves snapshot, stage, verify, disabled-definition adoption, upgrade, rollback, and uninstall against explicitly marked isolated ContextOS fixtures.

**Architecture:** Phase 3B adds a local transaction store and an immutable version-directory installer. A marked fixture target is snapshotted, a verified Phase 3A bundle is expanded into local staging, a new namespaced version directory is copied into the fixture, and one atomic registry-file replacement makes that disabled definition current. Exact-byte registry snapshots and hash inventories drive rollback; no scheduler, skill discovery, database migration, Google work, or live-target factory exists in this phase.

**Tech Stack:** Python 3.11+, standard library only (`dataclasses`, `enum`, `hashlib`, `json`, `os`, `pathlib`, `shutil`, `tempfile`, `uuid`, `zipfile`), `unittest`, existing ProjectOS Phase 3A contracts.

**Spec:** `docs/superpowers/specs/2026-09-27-projectos-phase-3-cross-platform-contextos-adoption-design.md`

## Global Constraints

- macOS and Windows are first-class host families; Windows needs no symlink or Developer Mode privilege.
- SQLite remains the single source of truth and all runtime, journal, snapshot, archive, lock, and database state stays outside ContextOS/shared roots.
- Phase 3B accepts only an explicitly marked isolated fixture target. It exposes no live-target constructor, override, environment variable, or force flag.
- The ContextOS registry mutation is namespaced to `projectos`; unrelated entries and files are preserved.
- Installed version directories are immutable and addressed by product version plus bundle-hash prefix. Activation is one atomic registry-file replacement.
- Every transaction is resumable from a canonical local journal and every rollback decision is hash-checked.
- Registry entries remain `enabled:false`; Phase 3C owns skill discovery, scheduler integration, the common locked sync command, and activation.
- The engine never authenticates Google, reads or writes a Sheet, deploys GAS, inspects Looker, initializes or migrates production SQLite, or changes a scheduler.
- All CLI output remains one redacted JSON envelope using existing exit-code conventions.
- Use TDD for every production behavior and run focused tests per task. Do not run the complete ProjectOS regression suite until the full Phase 3 release-candidate gate.

## Review Focus

- A fixture marker copied into an actual ContextOS directory must not be sufficient by itself: the target must have been issued while empty, match a local fixture receipt, resolve outside the local ProjectOS runtime, and require the explicit fixture CLI acknowledgement.
- A crash after copying a version directory but before registry replacement must be recoverable without changing the previous registry entry or deleting an unknown directory.
- A crafted bundle with a symlink, duplicate case-folded path, traversal path, or post-verification byte change must fail before target mutation.
- A registry containing unrelated extension shapes or formatting must preserve their semantic data on adoption and restore the exact original bytes on rollback.
- Windows case-insensitive paths, drive roots, and UNC fixture roots must not permit the local transaction store to overlap the target or shared definitions.

---

## File Structure

```text
src/projectos/adoption/fixture.py       Fixture-only target boundary and marker validation
src/projectos/adoption/registry.py      Registry v1 parsing, ProjectOS entry planning, canonical output
src/projectos/adoption/store.py         Local profiles, journals, snapshots, archives, atomic local writes
src/projectos/adoption/staging.py       Verified bundle expansion and immutable staged inventory
src/projectos/adoption/transaction.py   State machine, adoption, rollback, upgrade, uninstall orchestration
src/projectos/cli.py                    Fixture-only Phase 3B command surface
tests/test_adoption_fixture.py          Target and path safety
tests/test_extension_registry.py        Registry preservation and entry validation
tests/test_adoption_store.py            Canonical local state and crash-safe writes
tests/test_adoption_staging.py          Bundle expansion and TOCTOU defenses
tests/test_adoption_transaction.py      Failure injection and recovery behavior
tests/test_cli_phase3b.py               JSON envelope and no-live-target CLI contract
docs/PHASE3B_OPERATIONS.md              Fixture workflow, recovery, and phase boundary
docs/PHASE3B_VERIFICATION.md            Candidate evidence
```

### Task 1: Fixture-Only Installation Boundary

**Files:**
- Create: `src/projectos/adoption/fixture.py`
- Create: `tests/test_adoption_fixture.py`
- Modify: `src/projectos/adoption/__init__.py`

**Interfaces:**
- Consumes: `HostFamily`, `ContextOSInstallation`, `HostPathPolicy`.
- Produces: `FIXTURE_MARKER = ".projectos-contextos-fixture-v1"`; immutable `FixtureReceipt` and `FixtureInstallationTarget`; `issue_empty_fixture(root, runtime_root, family, machine_id, contextos_version="3.0.1") -> FixtureReceipt`; `FixtureInstallationTarget.open(installation, runtime_root, acknowledgement) -> FixtureInstallationTarget`; properties `fixture_id`, `root`, `extensions_root`, `skills_root`, `registry_path`; `assert_managed_path(path) -> None`.

- [ ] **Step 1: Write failing boundary tests**

Add tests named `test_issue_fixture_requires_new_or_empty_root_and_writes_local_receipt`, `test_fixture_target_requires_matching_receipt_marker_and_acknowledgement`, `test_copied_marker_cannot_authorize_an_existing_contextos_root`, `test_fixture_target_rejects_runtime_overlap_in_both_directions`, `test_fixture_target_rejects_symlinked_root_or_managed_ancestors`, `test_fixture_target_uses_component_aware_windows_drive_and_unc_rules`, and `test_fixture_target_open_is_read_only`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `rtk <python> -m unittest tests.test_adoption_fixture -v`  
Expected: FAIL because `projectos.adoption.fixture` does not exist.

- [ ] **Step 3: Implement the fixture target**

Issuance accepts only a new or empty non-symlink directory, generates a UUID fixture ID, writes the marker plus a minimal compatible ContextOS contract/machine profile, and writes a matching receipt below `<runtime_root>/adoption/fixture-receipts/`. The canonical marker contains only `format` and `fixture_id`; the local receipt also binds the normalized root, host family, and marker hash. Opening requires acknowledgement `FIXTURE_ONLY` and an exact receipt/marker match; reject missing/extra fields, symlinked target/managed ancestors, runtime containment in either direction, and target/registry paths outside the inspected ContextOS root. Opening the target performs no writes.

- [ ] **Step 4: Run focused verification**

Run: `rtk <python> -m unittest tests.test_adoption_fixture tests.test_contextos_adoption tests.test_host_paths -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/fixture.py src/projectos/adoption/__init__.py tests/test_adoption_fixture.py
rtk git commit --no-gpg-sign -m "feat: add fixture-only ContextOS target boundary"
```

### Task 2: Versioned Extension Registry

**Files:**
- Create: `src/projectos/adoption/registry.py`
- Create: `tests/test_extension_registry.py`
- Modify: `src/projectos/adoption/__init__.py`

**Interfaces:**
- Consumes: `ExtensionManifest`, `FixtureInstallationTarget`.
- Produces: `REGISTRY_VERSION = 1`; immutable `ProjectOSExtensionEntry`; `ExtensionRegistry.load(path) -> ExtensionRegistry`; `ExtensionRegistry.empty() -> ExtensionRegistry`; `with_projectos(entry) -> ExtensionRegistry`; `without_projectos() -> ExtensionRegistry`; `canonical_bytes() -> bytes`; `projectos_entry() -> ProjectOSExtensionEntry | None`; `plan_disabled_entry(manifest, bundle_sha256, relative_manifest_path, adopted_at) -> ProjectOSExtensionEntry`.

- [ ] **Step 1: Write failing registry tests**

Add tests named `test_empty_registry_round_trip_is_canonical`, `test_registry_preserves_unrelated_extension_values`, `test_projectos_entry_is_portable_disabled_and_hash_bound`, `test_registry_rejects_absolute_traversal_and_casefold_namespace_collision`, `test_registry_rejects_secret_material_and_wrong_types`, and `test_registry_load_does_not_create_missing_file`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `rtk <python> -m unittest tests.test_extension_registry -v`  
Expected: FAIL because the registry interfaces do not exist.

- [ ] **Step 3: Implement registry v1**

Use top-level fields `registry_version` and `extensions`. Preserve unrelated JSON values exactly as parsed, reserve the case-insensitive namespace `projectos`, and require the ProjectOS entry fields `extension_id`, `product_version`, `manifest`, `bundle_sha256`, `enabled`, and `adopted_at`. `enabled` must be `false` in Phase 3B. Manifest paths are portable relative paths under `projectos/versions/`.

- [ ] **Step 4: Run focused verification**

Run: `rtk <python> -m unittest tests.test_extension_registry tests.test_extension_bundle -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/registry.py src/projectos/adoption/__init__.py tests/test_extension_registry.py
rtk git commit --no-gpg-sign -m "feat: define the ProjectOS extension registry"
```

### Task 3: Local Transaction Store and Snapshot Inventory

**Files:**
- Create: `src/projectos/adoption/store.py`
- Create: `tests/test_adoption_store.py`
- Modify: `src/projectos/adoption/profile.py`
- Modify: `src/projectos/adoption/__init__.py`

**Interfaces:**
- Consumes: `MachineProfile`, `machine_profile_mapping`, `FixtureInstallationTarget`, `HostPathPolicy`.
- Produces: `machine_profile_from_mapping(value: Mapping[str, object]) -> MachineProfile`; `AdoptionOperation` enum with `ADOPT`, `UPGRADE`, `ROLLBACK`, `UNINSTALL`; `TransactionState` enum with `DISCOVERED`, `PREFLIGHTED`, `SNAPSHOTTED`, `STAGED`, `VERIFIED`, `ADOPTED`, `ROLLED_BACK`, `UNINSTALLED`, `FAILED`; immutable `SnapshotEntry`, `AdoptionSnapshot`, `TransactionJournal`; `LocalAdoptionStore.open(profile) -> LocalAdoptionStore`; `save_profile(profile) -> Path`; `load_profile(path) -> MachineProfile`; `create_journal(operation: AdoptionOperation, target: FixtureInstallationTarget, bundle_sha256: str | None, transaction_id: str) -> TransactionJournal`; `save_journal(journal) -> None`; `snapshot_target(target, transaction_id) -> AdoptionSnapshot`; `archive_managed_version(target, relative_version_path, expected_inventory, transaction_id) -> Path`.

- [ ] **Step 1: Write failing local-state tests**

Add tests named `test_machine_profile_round_trip_is_strict_and_canonical`, `test_store_is_derived_from_local_profile_and_rejects_shared_overlap`, `test_profile_and_journal_writes_are_atomic_and_canonical`, `test_journal_transition_graph_rejects_skip_or_reversal`, `test_snapshot_preserves_registry_exact_bytes_and_hashes_managed_files`, `test_snapshot_rejects_symlinks_and_secret_material`, and `test_archive_never_contains_database_lock_log_or_unrelated_contextos_files`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `rtk <python> -m unittest tests.test_adoption_store -v`  
Expected: FAIL because the local store does not exist.

- [ ] **Step 3: Implement local persistence**

Store state below `<runtime_root>/adoption/`: `machine-profile.json`, `transactions/<uuid>/journal.json`, `transactions/<uuid>/snapshot/`, and `archives/`. Use sibling temporary files plus flush, `fsync`, and `os.replace`. A journal contains only bounded operation metadata, state, safe error codes, target-relative managed paths, hashes, and timestamps; it never contains credentials or private catalog data.

- [ ] **Step 4: Run focused verification**

Run: `rtk <python> -m unittest tests.test_adoption_store tests.test_machine_profile tests.test_backup_health -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/store.py src/projectos/adoption/profile.py src/projectos/adoption/__init__.py tests/test_adoption_store.py
rtk git commit --no-gpg-sign -m "feat: persist local ProjectOS adoption transactions"
```

### Task 4: Verified Bundle Staging

**Files:**
- Create: `src/projectos/adoption/staging.py`
- Create: `tests/test_adoption_staging.py`
- Modify: `src/projectos/adoption/bundle.py`
- Modify: `src/projectos/adoption/__init__.py`

**Interfaces:**
- Consumes: `verify_extension_bundle`, `ArtifactPolicy`, `MachineProfile`, `LocalAdoptionStore`, `ExtensionManifest`.
- Produces: immutable `StagedExtension`; `stage_extension(bundle_path, profile, store, transaction_id, policy) -> StagedExtension`; `verify_staged_extension(staged, profile, policy) -> StagedExtension`; `copy_verified_version(staged, target) -> Path`.

- [ ] **Step 1: Write failing staging tests**

Add tests named `test_stage_expands_verified_bundle_only_under_local_transaction_root`, `test_stage_rejects_manifest_profile_or_host_incompatibility`, `test_stage_rejects_symlink_duplicate_traversal_and_secret_members`, `test_verify_detects_post_extraction_byte_change`, `test_copy_reverifies_source_and_refuses_existing_nonidentical_version`, and `test_copy_is_idempotent_for_identical_immutable_version`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `rtk <python> -m unittest tests.test_adoption_staging -v`  
Expected: FAIL because staging interfaces do not exist.

- [ ] **Step 3: Implement staging and immutable copy**

The local staged directory is `<transaction>/staged/projectos/versions/<product_version>-<bundle_hash_prefix>/`. Recheck ZIP metadata while extracting, write regular files only, compare the extracted inventory to the manifest, and hash again immediately before copying. The target copy uses a transaction-specific sibling directory and atomic rename to the final immutable version path; it never uses symlinks.

- [ ] **Step 4: Run focused verification**

Run: `rtk <python> -m unittest tests.test_adoption_staging tests.test_extension_bundle tests.test_host_paths -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/staging.py src/projectos/adoption/bundle.py src/projectos/adoption/__init__.py tests/test_adoption_staging.py
rtk git commit --no-gpg-sign -m "feat: stage verified ProjectOS extension versions"
```

### Task 5: Adoption and Rollback State Machine

**Files:**
- Create: `src/projectos/adoption/transaction.py`
- Create: `tests/test_adoption_transaction.py`
- Modify: `src/projectos/adoption/__init__.py`

**Interfaces:**
- Consumes: `AdoptionOperation`, `TransactionState`, `FixtureInstallationTarget`, `ExtensionRegistry`, `LocalAdoptionStore`, `StagedExtension`, Phase 3A profile and bundle verification.
- Produces: immutable `TransactionResult`; `AdoptionTransaction.begin(operation: AdoptionOperation, target: FixtureInstallationTarget, profile: MachineProfile, store: LocalAdoptionStore, policy: ArtifactPolicy, transaction_id: str, bundle_path: Path | None = None) -> AdoptionTransaction`; `AdoptionTransaction.resume(target, profile, store, policy, transaction_id) -> AdoptionTransaction`; `preflight() -> TransactionResult`; `snapshot() -> TransactionResult`; `stage() -> TransactionResult`; `verify() -> TransactionResult`; `adopt_disabled() -> TransactionResult`; `rollback() -> TransactionResult`; `uninstall() -> TransactionResult`; `recover() -> TransactionResult`.

- [ ] **Step 1: Write failing transaction tests**

Add tests named `test_adopt_requires_ordered_discover_preflight_snapshot_stage_verify`, `test_adopt_atomically_switches_only_disabled_projectos_registry_entry`, `test_failure_before_registry_replace_leaves_previous_registry_exact`, `test_failure_after_registry_replace_restores_exact_snapshot`, `test_recovery_removes_only_hash_matching_transaction_owned_version`, `test_upgrade_retains_previous_version_and_rollback_switches_back`, `test_uninstall_removes_only_projectos_and_archives_managed_versions`, `test_uninstall_preserves_database_profile_journals_and_unrelated_contextos_state`, and `test_failure_injection_at_every_boundary_is_resumable`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `rtk <python> -m unittest tests.test_adoption_transaction -v`  
Expected: FAIL because the transaction state machine does not exist.

- [ ] **Step 3: Implement the state machine**

All state changes are journaled before and after the boundary. Adoption copies the immutable version first and then atomically replaces only `registry.json`. Rollback restores the exact registry bytes captured by the snapshot; it removes a newly copied version only when the journal owns it and its current inventory matches. Upgrade uses the same path with a prior ProjectOS entry. Uninstall atomically writes a registry without `projectos`, archives managed versions locally, and removes only hash-matching ProjectOS paths after archive verification.

- [ ] **Step 4: Run focused verification**

Run: `rtk <python> -m unittest tests.test_adoption_transaction tests.test_adoption_store tests.test_adoption_staging tests.test_extension_registry -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/transaction.py src/projectos/adoption/__init__.py tests/test_adoption_transaction.py
rtk git commit --no-gpg-sign -m "feat: add recoverable ProjectOS adoption transactions"
```

### Task 6: Fixture-Only Transaction CLI

**Files:**
- Modify: `src/projectos/cli.py`
- Create: `tests/test_cli_phase3b.py`

**Interfaces:**
- Consumes: Phase 3A database-free dispatch, `FixtureInstallationTarget`, `LocalAdoptionStore`, `AdoptionTransaction`.
- Produces database-free commands: `adoption fixture init ROOT --runtime-root ROOT --host-family FAMILY --machine-id ID [--contextos-version VERSION]`; `adoption fixture preflight BUNDLE --fixture-ack FIXTURE_ONLY --contextos-root ROOT --machine-profile PROFILE [--forbid VALUE]...`; `adoption fixture adopt BUNDLE` and `upgrade BUNDLE` with the same required options; `adoption fixture rollback TRANSACTION_ID`, `uninstall`, and `recover TRANSACTION_ID` with the same target/profile acknowledgement options but no bundle.

- [ ] **Step 1: Write failing CLI tests**

Add tests named `test_phase3b_commands_are_database_free_and_one_json_envelope`, `test_fixture_init_refuses_nonempty_or_symlinked_root`, `test_cli_has_no_live_adopt_or_force_flag`, `test_fixture_acknowledgement_marker_and_local_receipt_are_all_required`, `test_preflight_and_failed_stage_do_not_mutate_target`, `test_fixture_adopt_upgrade_rollback_uninstall_round_trip`, `test_recover_is_idempotent_after_each_injected_failure`, `test_cli_never_echoes_paths_marked_sensitive_or_secret_input`, and `test_nonfixture_existing_commands_remain_unchanged`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `rtk <python> -m unittest tests.test_cli_phase3b -v`  
Expected: FAIL because the Phase 3B commands do not exist.

- [ ] **Step 3: Implement the CLI facade**

Keep all Phase 3B commands in `DATABASE_FREE_COMMANDS`. The CLI loads a previously planned machine-profile JSON, revalidates its host and local/shared separation, and uses the exact explicit fixture root. No parser path exposes live adoption, registry enablement, skill discovery, scheduler work, or a bypass flag. Operational failures use exit `3`; validation and compatibility failures use exit `2`.

- [ ] **Step 4: Run focused verification**

Run: `rtk <python> -m unittest tests.test_cli_phase3b tests.test_cli_phase3a tests.test_cli tests.test_cli_phase2 -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/cli.py tests/test_cli_phase3b.py
rtk git commit --no-gpg-sign -m "feat: expose fixture-only adoption transactions"
```

### Task 7: Operations, Packaging, and Phase 3B Candidate Gate

**Files:**
- Modify: `build_backend.py`
- Modify: `tests/test_build_backend.py`
- Create: `docs/PHASE3B_OPERATIONS.md`
- Create: `docs/PHASE3B_VERIFICATION.md`
- Modify: `docs/PHASE3A_VERIFICATION.md`
- Modify: `docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: all Phase 3B modules and CLI commands.
- Produces: deterministic wheel coverage for the new modules; a fixture-only operations and recovery runbook; phase evidence; corrected 3B/3C boundaries in prior handoff documents.

- [ ] **Step 1: Write failing packaging and clean-room tests**

Add tests named `test_wheel_contains_all_phase3b_modules`, `test_phase3b_wheel_is_byte_identical`, `test_extracted_wheel_completes_fixture_adopt_and_rollback`, and `test_wheel_and_fixture_evidence_contain_no_build_or_target_identifiers`.

- [ ] **Step 2: Run build tests and verify RED**

Run: `rtk <python> -m unittest tests.test_build_backend -v`  
Expected: FAIL until the clean-room wheel workflow exercises the Phase 3B transaction modules.

- [ ] **Step 3: Complete packaging and documentation**

Document configuration precedence, fixture creation, exact marker/acknowledgement, local transaction locations, expected envelopes, failure recovery, archive retention, and the prohibition on live adoption. Correct earlier summaries so Phase 3B owns the disabled-definition transaction engine, Phase 3C owns skill discovery/schedulers/sync activation, and Phase 3D owns real-host reconciliation.

- [ ] **Step 4: Run the Phase 3B candidate gate**

Run:

```bash
rtk <python> -m unittest \
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
  tests.test_build_backend -v
rtk <python> -m compileall -q src build_backend.py
rtk <python> -m pip wheel --no-deps --no-build-isolation -w <fresh-temp-directory> .
```

Expected: focused and affected-regression tests PASS, compilation exits `0`, and a deterministic `py3-none-any` wheel is produced.

- [ ] **Step 5: Scan and record evidence**

Scan every wheel member plus invented fixture journals, snapshots, staged files, and archives for build/target home paths, usernames, hostnames, shared-root names, live identifiers, private keys, and high-confidence token patterns. Record Python/platform, test count, commit, wheel size/hash, transaction round trip, failure-injection count, and the remaining real-host and Phase 3C gates.

- [ ] **Step 6: Commit**

```bash
rtk git add build_backend.py tests/test_build_backend.py README.md docs/PHASE3B_OPERATIONS.md docs/PHASE3B_VERIFICATION.md docs/PHASE3A_VERIFICATION.md docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md
rtk git commit --no-gpg-sign -m "docs: complete ProjectOS phase 3B handoff"
```

## Phase 3B Completion Gate

Phase 3B stops when all seven tasks are committed and the focused candidate gate passes. The completion report must include:

- commits created;
- focused test counts and compile result;
- deterministic wheel hash and clean-room fixture round trip;
- failure-injection, identifier, secret, and symlink scan results;
- confirmation that no live ContextOS, scheduler, skill discovery, Google, GAS, Looker, shared-root, or production SQLite state changed;
- confirmation that macOS and Windows transaction semantics remain fixture/simulation evidence only;
- one exhaustive list of implementation rulings and deferred minors;
- the remaining Phase 3C and 3D boundaries.

Do not begin Phase 3C automatically. Review the Phase 3B evidence and obtain the user's next-phase direction first.
