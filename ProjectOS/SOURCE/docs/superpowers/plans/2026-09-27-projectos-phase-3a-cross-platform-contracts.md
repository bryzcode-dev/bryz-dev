# ProjectOS Phase 3A Cross-Platform Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not delegate unless the user separately authorizes an implementation agent.

**Goal:** Build the dependency-free Windows/macOS host contracts, ContextOS discovery model, machine-profile planner, deterministic extension manifest and bundle format, and read-only adoption CLI needed by later Phase 3 activation work.

**Architecture:** Phase 3A adds a platform-neutral `projectos.adoption` package and moves all operating-system decisions behind explicit host interfaces. It produces inspectable plans and deterministic staged artifacts only: transaction execution, native scheduler activation, live skill installation, and live ContextOS changes remain in later Phase 3 candidates.

**Tech Stack:** Python 3.11+ standard library, dataclasses, `pathlib` pure path flavors, TOML/JSON, SHA-256, deterministic ZIP archives, SQLite, and `unittest`; no new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-09-27-projectos-phase-3-cross-platform-contextos-adoption-design.md`

## Global Constraints

- Windows and macOS are first-class product requirements; neither platform may be represented by a developer-machine path or a renamed adapter for the other.
- `projectos.db` remains the local SQLite single source of truth; databases, WAL/SHM files, locks, credentials, caches, queues, and transient logs never enter shared ContextOS storage.
- Configuration precedence is explicit CLI argument, ProjectOS environment variable, adopted machine profile, then platform default.
- macOS defaults to `$HOME/Library/Application Support/ProjectOS`; Windows defaults to `%LOCALAPPDATA%\ProjectOS` and fails closed when that value is unavailable unless an explicit local override exists.
- Windows drive, UNC, separator, and case behavior must be modeled with Windows path semantics even when tests run on macOS.
- Windows package import and read-only adoption planning cannot require `fcntl`, Developer Mode, symlink privileges, PowerShell, or an active Task Scheduler service.
- ContextOS integration uses a versioned extension contract; an absent, malformed, or incompatible contract produces a read-only diagnostic and no mutation.
- The extension bundle contains no secret material, developer username, machine name, home path, NAS name, live Google identifier, or resolved target-host path.
- Phase 3A uses only the fake Google gateway and performs no network calls.
- Phase 3A does not install or enable a scheduler, register a skill, initialize a live ProjectOS database, or modify a live ContextOS installation.
- Every CLI result remains one structured JSON document with the existing exit-code and redaction contract.
- Existing Phase 1 and Phase 2 interfaces remain compatible.
- At plan start, resolve a Python 3.11+ executable and substitute it for `<python>` in every command.

## Review Focus

- A Windows path differs only by drive-letter or component case, uses mixed separators, escapes with `..`, or crosses from a drive path to UNC: `tests/test_host_paths.py` must prove host-correct normalization and containment without relying on the build host.
- `%LOCALAPPDATA%` is absent, relative, or points inside a declared shared ContextOS root: `tests/test_host_paths.py` and `tests/test_machine_profile.py` must prove fail-closed planning and zero filesystem writes.
- A ContextOS root has a missing, malformed, newer, or incompatible extension contract: `tests/test_contextos_adoption.py` must return a bounded incompatibility result without creating a database, registry, skill, or profile.
- A bundle input is a symlink, traversal path, duplicate case-folded Windows name, secret-bearing file, or contains a supplied build-machine identifier: `tests/test_extension_bundle.py` must reject it before the output archive is replaced.
- The package imports or sync locking is exercised on Windows where `fcntl` does not exist: `tests/test_process_lock.py` and the wheel smoke test must prove lazy native backend loading and preserve current POSIX lock behavior.

---

## File Structure

```text
src/projectos/adoption/__init__.py          Public Phase 3A adoption exports
src/projectos/adoption/host.py              HostFamily detection and immutable host identity
src/projectos/adoption/paths.py             Platform defaults, overrides, and local runtime layout
src/projectos/adoption/path_policy.py       POSIX/Windows normalization and containment rules
src/projectos/adoption/lock.py              Lazy POSIX/Windows advisory-lock backends
src/projectos/adoption/contextos.py         ContextOS extension-contract model and locator
src/projectos/adoption/profile.py           Pure machine-profile planning and validation
src/projectos/adoption/manifest.py          Extension manifest types and compatibility validation
src/projectos/adoption/bundle.py            Artifact policy, inventory, deterministic ZIP build/verify
src/projectos/sync/lock.py                   Backward-compatible ProjectOSFileLock facade
src/projectos/google/config.py               Platform-aware default configuration resolution
src/projectos/cli.py                         Database-free Phase 3A adoption commands
build_backend.py                             Cross-platform wheel-content and deterministic build support
tests/test_host_paths.py                     macOS/Windows defaults, overrides, and path policy
tests/test_process_lock.py                   Lazy backend selection and lock behavior
tests/test_contextos_adoption.py             Contract parsing, discovery, and incompatibility gates
tests/test_machine_profile.py                Pure profile plans and local/shared separation
tests/test_extension_bundle.py               Manifest, policy, deterministic build, and verification
tests/test_cli_phase3a.py                     JSON adoption commands and no-DB/no-live-write proof
tests/test_build_backend.py                   Wheel contents and cross-platform import smoke tests
docs/PHASE3_CONTEXTOS_EXTENSION_CONTRACT.md   Exact ContextOS-side JSON contract required by ProjectOS
docs/PHASE3A_OPERATIONS.md                    Read-only discovery and staging operations
docs/PHASE3A_VERIFICATION.md                  Candidate evidence and deferred live gates
docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md
                                               Windows-machine execution and evidence handoff
```

### Task 1: Host Families, Platform Paths, and Path Policy

**Files:**
- Create: `src/projectos/adoption/__init__.py`
- Create: `src/projectos/adoption/host.py`
- Create: `src/projectos/adoption/paths.py`
- Create: `src/projectos/adoption/path_policy.py`
- Modify: `src/projectos/google/config.py`
- Modify: `src/projectos/cli.py`
- Create: `tests/test_host_paths.py`
- Modify: `tests/test_real_gateway.py`

**Interfaces:**
- Consumes: Python environment mappings, optional explicit paths, `Path.home()`, and the existing `ValidationError` contract.
- Produces: `HostFamily(MACOS="macos", WINDOWS="windows")`; `HostIdentity(family, machine_id)`; `detect_host_family(system_name: str | None = None) -> HostFamily`; `PlatformPathOverrides(runtime_root=None, database_path=None, config_path=None)`; `PlatformPaths(runtime_root, database_path, config_path, lock_path, log_root, staging_root)`; `resolve_platform_paths(family, environ, home, overrides=None) -> PlatformPaths`; `default_database_path(family=None, environ=None, home=None) -> Path`; `ProjectOSGoogleConfig.resolve_path(path, environ, family=None, home=None) -> Path`; and `HostPathPolicy(family)` with `normalize(value: str) -> str`, `is_absolute(value: str) -> bool`, `is_within(candidate: str, root: str) -> bool`, and `assert_local_runtime(runtime: str, shared_roots: Sequence[str]) -> None`.

- [ ] **Step 1: Write failing host-path tests**

Add tests named `test_macos_defaults_are_under_supplied_home`, `test_windows_defaults_use_localappdata`, `test_windows_missing_localappdata_requires_explicit_runtime`, `test_explicit_and_environment_overrides_precede_defaults`, `test_windows_normalization_handles_case_mixed_separators_and_dot_segments`, `test_windows_drive_and_unc_roots_never_compare_as_contained`, `test_component_containment_rejects_string_prefix_collision`, `test_runtime_inside_any_shared_root_is_rejected`, and `test_google_config_uses_platform_paths_without_real_identifiers`. Assert exact default child names and no filesystem creation.

- [ ] **Step 2: Run tests and verify the intended failure**

Run: `rtk <python> -m unittest tests.test_host_paths tests.test_real_gateway -v`  
Expected: FAIL because `projectos.adoption` and platform-aware default resolution do not exist.

- [ ] **Step 3: Implement the host and path interfaces**

Use `PurePosixPath` and `PureWindowsPath` for lexical policy so Windows behavior is testable on macOS. Reject relative runtime roots, unresolved parent escapes, drive/UNC family changes, and runtime containment within any declared shared root. Update default database and Google configuration resolution to consume `PlatformPaths`; retain explicit `--db`, `PROJECTOS_DB`, explicit config, and `PROJECTOS_HOME` behavior.

- [ ] **Step 4: Run focused path/config tests**

Run: `rtk <python> -m unittest tests.test_host_paths tests.test_real_gateway tests.test_cli -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption src/projectos/google/config.py src/projectos/cli.py tests/test_host_paths.py tests/test_real_gateway.py
rtk git -c commit.gpgsign=false commit -m "feat: add cross-platform ProjectOS paths"
```

### Task 2: Cross-Platform Process Lock Foundation

**Files:**
- Create: `src/projectos/adoption/lock.py`
- Modify: `src/projectos/sync/lock.py`
- Create: `tests/test_process_lock.py`
- Modify: `tests/test_sync_service.py`

**Interfaces:**
- Consumes: `HostFamily`, the current `ProjectOSFileLock(path, trigger, run_id)` context-manager contract, and existing lock metadata format `projectos-lock-v1`.
- Produces: runtime-checkable `NativeLockBackend.acquire(file) -> None` and `release(file) -> None`; `backend_for(family: HostFamily) -> NativeLockBackend`; `PosixLockBackend` with lazy `fcntl` import; `WindowsLockBackend` with lazy `msvcrt` import; and the existing `ProjectOSFileLock` facade selecting a backend only on entry.

- [ ] **Step 1: Write failing lock tests**

Add tests named `test_posix_backend_is_loaded_lazily`, `test_windows_backend_is_loaded_without_importing_fcntl`, `test_windows_lock_rewinds_and_locks_one_metadata_byte`, `test_backend_contention_maps_to_lock_unavailable`, `test_malformed_prior_metadata_remains_fail_closed`, and `test_existing_projectos_file_lock_api_is_unchanged`. Inject small fake native modules rather than patching the build host.

- [ ] **Step 2: Run tests and verify the intended failure**

Run: `rtk <python> -m unittest tests.test_process_lock tests.test_sync_service -v`  
Expected: FAIL because `sync.lock` imports `fcntl` unconditionally and has no Windows backend.

- [ ] **Step 3: Implement lazy native lock backends**

Preserve metadata validation, PID diagnostics, exclusive non-blocking behavior, `fsync`, and exception mapping. The Windows backend ensures a reserved first byte exists, uses `msvcrt.locking` on that byte, and always seeks before acquire/release. Do not add stale-lock deletion or waiting in Phase 3A; bounded waits remain Phase 3C.

- [ ] **Step 4: Run lock and sync tests**

Run: `rtk <python> -m unittest tests.test_process_lock tests.test_sync_service -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/lock.py src/projectos/sync/lock.py tests/test_process_lock.py tests/test_sync_service.py
rtk git -c commit.gpgsign=false commit -m "feat: make ProjectOS locking host portable"
```

### Task 3: ContextOS Extension Contract and Read-Only Locator

**Files:**
- Create: `src/projectos/adoption/contextos.py`
- Create: `tests/test_contextos_adoption.py`
- Create: `docs/PHASE3_CONTEXTOS_EXTENSION_CONTRACT.md`

**Interfaces:**
- Consumes: `HostFamily`, `HostPathPolicy`, an explicit root, `CONTEXTOS_ROOT`, a supplied home directory, and JSON files under a candidate ContextOS root.
- Produces: `CONTEXTOS_EXTENSION_CONTRACT_VERSION = 1`; `ContextOSExtensionContract(contract_version, contextos_version, extensions_root, skills_root, runtime_root_template, supported_hosts)` with `from_mapping`; `ContextOSInstallation(root, config_path, machine_profile_path, contract_path, contract, machine_id)`; `ContextOSLocator(family, environ, home)` with `candidates(explicit_root=None) -> tuple[str, ...]` and `inspect(explicit_root=None) -> ContextOSInstallation`; and `ContextOSCompatibilityError(ValidationError)`.

- [ ] **Step 1: Write failing locator and compatibility tests**

Add tests named `test_explicit_root_precedes_environment_and_default`, `test_environment_root_precedes_platform_default`, `test_windows_default_uses_userprofile_dot_claude`, `test_locator_reads_compatible_contract_without_writes`, `test_missing_contract_fails_without_fallback_mutation`, `test_malformed_contract_is_bounded_validation_error`, `test_newer_contract_version_fails_closed`, `test_unsupported_host_fails_closed`, `test_extensions_and_skills_must_stay_within_contextos_root`, and `test_machine_profile_identifier_is_optional_but_validated_when_present`.

- [ ] **Step 2: Run tests and verify the intended failure**

Run: `rtk <python> -m unittest tests.test_contextos_adoption -v`  
Expected: FAIL because ContextOS contract and locator interfaces do not exist.

- [ ] **Step 3: Implement contract parsing and read-only discovery**

Use exact integer contract versions and dotted numeric ContextOS versions; Phase 3A supports ContextOS `>=3.0.1` and `<4.0.0`. Validate relative registry/skill paths against the discovered root with `HostPathPolicy`. Discovery reads only and never creates a root, profile, database, extension directory, or contract. Document the exact `extension-contract.json` keys, types, relative-path requirements, compatibility rule, macOS/Windows examples, and fail-closed behavior for the separate ContextOS implementation.

- [ ] **Step 4: Run locator tests**

Run: `rtk <python> -m unittest tests.test_contextos_adoption tests.test_host_paths -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/contextos.py tests/test_contextos_adoption.py docs/PHASE3_CONTEXTOS_EXTENSION_CONTRACT.md
rtk git -c commit.gpgsign=false commit -m "feat: inspect ContextOS extension contracts"
```

### Task 4: Pure Machine-Profile Planning

**Files:**
- Create: `src/projectos/adoption/profile.py`
- Create: `tests/test_machine_profile.py`

**Interfaces:**
- Consumes: `ContextOSInstallation`, `HostIdentity`, `PlatformPaths`, Python executable, ProjectOS version, scheduler kind, and declared shared roots.
- Produces: `MACHINE_PROFILE_VERSION = 1`; `SchedulerKind(LAUNCHD="launchd", WINDOWS_TASK_SCHEDULER="windows-task-scheduler")`; immutable `MachineProfile`; `MachineProfilePlan(profile, checks, ready, errors)`; `plan_machine_profile(installation, identity, paths, python_executable, projectos_version, scheduler_kind, shared_roots=()) -> MachineProfilePlan`; and `machine_profile_mapping(profile) -> dict[str, object]`.

- [ ] **Step 1: Write failing profile tests**

Add tests named `test_macos_profile_contains_only_target_host_values`, `test_windows_profile_contains_localappdata_and_task_scheduler`, `test_profile_rejects_scheduler_for_other_host`, `test_profile_rejects_relative_python_executable`, `test_profile_rejects_runtime_database_lock_or_log_under_shared_root`, `test_profile_rejects_contextos_contract_mismatch`, `test_profile_planning_does_not_write_files`, and `test_profile_mapping_is_stable_and_contains_every_spec_field`.

- [ ] **Step 2: Run tests and verify the intended failure**

Run: `rtk <python> -m unittest tests.test_machine_profile -v`  
Expected: FAIL because the machine-profile planner does not exist.

- [ ] **Step 3: Implement immutable profile planning**

Return every check and bounded error in `MachineProfilePlan`; do not raise after ordinary incompatibility discovery. Reserve exceptions for malformed programmer input. The plan must not write the profile or create its parent directory; Phase 3B owns transactional persistence.

- [ ] **Step 4: Run profile, path, and locator tests**

Run: `rtk <python> -m unittest tests.test_machine_profile tests.test_host_paths tests.test_contextos_adoption -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/profile.py tests/test_machine_profile.py
rtk git -c commit.gpgsign=false commit -m "feat: plan ProjectOS machine profiles"
```

### Task 5: Extension Manifest and Deterministic Bundle

**Files:**
- Create: `src/projectos/adoption/manifest.py`
- Create: `src/projectos/adoption/bundle.py`
- Create: `tests/test_extension_bundle.py`

**Interfaces:**
- Consumes: a validated machine-profile reference, ProjectOS/ContextOS compatibility values, capability allowlist, safe optional Google references, payload files from an isolated staging root, and caller-supplied forbidden build identifiers.
- Produces: `EXTENSION_MANIFEST_VERSION = 1`; `BUNDLE_FORMAT_VERSION = 1`; immutable `SkillDeclaration`, `CompatibilityDeclaration`, `CommandDeclaration`, `PayloadEntry`, and `ExtensionManifest`; `ExtensionManifest.from_mapping`, `to_mapping`, and `validate`; `ArtifactPolicy(forbidden_values)` with `inspect(relative_name, source_path, content) -> None`; `ExtensionBundleBuilder.build(manifest, payload_root, output_path, policy) -> BundleResult`; and `verify_extension_bundle(path, policy) -> BundleVerification`.

- [ ] **Step 1: Write failing manifest and bundle tests**

Add tests named `test_manifest_requires_projectos_namespace_supported_hosts_and_allowlisted_commands`, `test_manifest_rejects_absolute_build_host_paths_and_secret_fields`, `test_manifest_round_trip_is_canonical`, `test_bundle_is_byte_identical_across_two_builds`, `test_bundle_inventory_hashes_every_payload_and_excludes_self_reference`, `test_bundle_rejects_traversal_absolute_and_duplicate_casefolded_names`, `test_bundle_rejects_symlink_inputs`, `test_bundle_rejects_private_key_token_and_forbidden_host_identifier`, `test_failed_build_never_replaces_existing_output`, and `test_verify_rejects_hash_or_inventory_tampering`.

- [ ] **Step 2: Run tests and verify the intended failure**

Run: `rtk <python> -m unittest tests.test_extension_bundle -v`  
Expected: FAIL because manifest and bundle interfaces do not exist.

- [ ] **Step 3: Implement manifest validation and deterministic ZIP construction**

Use canonical UTF-8 JSON, sorted archive names, fixed ZIP timestamps and permissions, and SHA-256 payload inventory. Validate archive paths with both POSIX and Windows rules. Write to a sibling temporary file, verify it, then replace the requested output atomically. Inventory excludes `manifest.json` to avoid a circular manifest hash; the archive verification separately validates canonical manifest bytes.

- [ ] **Step 4: Run bundle tests twice**

Run twice:

```bash
rtk <python> -m unittest tests.test_extension_bundle -v
rtk <python> -m unittest tests.test_extension_bundle -v
```

Expected: both runs PASS and deterministic-byte assertions remain stable.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/adoption/manifest.py src/projectos/adoption/bundle.py tests/test_extension_bundle.py
rtk git -c commit.gpgsign=false commit -m "feat: build deterministic ProjectOS extension bundles"
```

### Task 6: Database-Free Adoption CLI

**Files:**
- Modify: `src/projectos/cli.py`
- Create: `tests/test_cli_phase3a.py`

**Interfaces:**
- Consumes: Tasks 1–5 public interfaces and the existing JSON envelope/error mapping.
- Produces: `DATABASE_FREE_COMMANDS`; `dispatch_without_database(arguments) -> object`; `adoption inspect [--host-family FAMILY] [--contextos-root PATH]`; `adoption profile plan --python-executable PATH [--host-family FAMILY] [--contextos-root PATH] [--projectos-home PATH]`; `adoption manifest validate MANIFEST`; `adoption bundle build MANIFEST PAYLOAD_ROOT OUTPUT [--forbid VALUE]...`; and `adoption bundle verify BUNDLE [--forbid VALUE]...`. Existing database-backed commands continue through `dispatch(arguments, database)` unchanged.

- [ ] **Step 1: Write failing Phase 3A CLI tests**

Add tests named `test_adoption_inspect_returns_one_json_document_without_creating_database`, `test_adoption_profile_plan_is_read_only_and_reports_ready`, `test_adoption_profile_plan_reports_incompatible_contract_without_traceback`, `test_manifest_validate_rejects_secret_without_echoing_it`, `test_bundle_build_writes_only_requested_staging_output`, `test_bundle_verify_is_read_only`, `test_adoption_commands_never_instantiate_projectos_database`, and `test_existing_database_commands_still_initialize_and_dispatch`.

- [ ] **Step 2: Run tests and verify the intended failure**

Run: `rtk <python> -m unittest tests.test_cli_phase3a tests.test_cli tests.test_cli_phase2 -v`  
Expected: FAIL because adoption commands and database-free dispatch do not exist.

- [ ] **Step 3: Implement parsers and database-free dispatch**

Parse host family explicitly for simulated planning and otherwise detect it. Require explicit output and payload roots for bundle build. Automatically add current home, username, hostname, and resolved ContextOS root to `ArtifactPolicy.forbidden_values` without serializing those values into the result. Keep errors generic and use existing exit code `2` for validation/compatibility failures.

- [ ] **Step 4: Run CLI regression tests**

Run: `rtk <python> -m unittest tests.test_cli_phase3a tests.test_cli tests.test_cli_phase2 -v`  
Expected: all tests PASS and every invocation emits exactly one JSON document.

- [ ] **Step 5: Commit**

```bash
rtk git add src/projectos/cli.py tests/test_cli_phase3a.py
rtk git -c commit.gpgsign=false commit -m "feat: expose read-only ProjectOS adoption CLI"
```

### Task 7: Portable Wheel, Operations, and Windows Handoff

**Files:**
- Modify: `build_backend.py`
- Modify: `tests/test_build_backend.py`
- Create: `docs/PHASE3A_OPERATIONS.md`
- Create: `docs/PHASE3A_VERIFICATION.md`
- Create: `docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: all Phase 3A modules and CLI commands.
- Produces: a deterministic `py3-none-any` wheel containing the adoption modules; a clean-room wheel import command; read-only macOS and Windows planning instructions; a Windows handoff evidence schema; and candidate verification records that distinguish simulated from real-host evidence.

- [ ] **Step 1: Write failing wheel portability tests**

Add tests named `test_wheel_contains_all_adoption_modules`, `test_two_wheels_are_byte_identical`, `test_wheel_has_no_build_machine_identifiers`, and `test_extracted_wheel_imports_with_fcntl_unavailable_until_posix_lock_selected`. Preserve existing metadata and optional Google-extra assertions.

- [ ] **Step 2: Run build tests and verify the intended failure**

Run: `rtk <python> -m unittest tests.test_build_backend -v`  
Expected: FAIL until the backend and wheel smoke test account for every Phase 3A module and lazy lock import.

- [ ] **Step 3: Update the wheel backend and write operations documentation**

Keep the wheel dependency-free and deterministic. Document command inputs, configuration precedence, output locations, compatibility errors, artifact inspection, recovery from a failed staging build, and the fact that no Phase 3A command activates ContextOS or a scheduler.

- [ ] **Step 4: Write the Windows implementation and troubleshooting handoff**

Include exact source revision placeholders, artifact-hash recording, Python/ContextOS prerequisites, PowerShell-safe clean-room setup, drive and UNC test cases, `%LOCALAPPDATA%` verification, no-symlink checks, Task Scheduler work deferred to 3C, expected JSON envelopes, evidence filenames, bounded remediation, and a prohibition on live adoption until later staged gates pass.

- [ ] **Step 5: Run the Phase 3A candidate gate**

Run:

```bash
rtk <python> -m unittest \
  tests.test_host_paths \
  tests.test_process_lock \
  tests.test_contextos_adoption \
  tests.test_machine_profile \
  tests.test_extension_bundle \
  tests.test_cli_phase3a \
  tests.test_real_gateway \
  tests.test_sync_service \
  tests.test_build_backend -v
rtk <python> -m compileall -q src build_backend.py
rtk <python> -m pip wheel --no-deps --no-build-isolation -w dist .
```

Expected: focused and affected regression tests PASS, compilation exits `0`, and one deterministic wheel is produced. Do not run the complete ProjectOS regression suite until the full Phase 3 release-candidate gate unless an affected test reveals broader coupling.

- [ ] **Step 6: Scan the candidate and record evidence**

Inspect the wheel member list and text-bearing members; assert no supplied build-home, username, hostname, ContextOS root, live identifier, or secret pattern. Record Python version, test counts, wheel SHA-256, commit, platform, simulated-Windows status, and the still-required real-Windows gate in `docs/PHASE3A_VERIFICATION.md`.

- [ ] **Step 7: Commit**

```bash
rtk git add build_backend.py tests/test_build_backend.py README.md docs/PHASE3A_OPERATIONS.md docs/PHASE3A_VERIFICATION.md docs/PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md
rtk git -c commit.gpgsign=false commit -m "docs: complete ProjectOS phase 3A handoff"
```

## Phase 3A Completion Gate

Phase 3A stops when all seven tasks are committed and the focused candidate gate passes. The completion report must include:

- commits created;
- focused test counts and compile result;
- deterministic wheel hash;
- build-identifier and secret scan result;
- confirmation that no live ContextOS, scheduler, Google, GAS, Looker, or shared-root state changed;
- confirmation that Windows behavior is simulated only and still requires the real-Windows gate;
- the remaining Phase 3B, 3C, and 3D boundaries.

Do not begin Phase 3B automatically. Review the Phase 3A evidence and obtain the user's next-phase direction first.
