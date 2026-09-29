# ProjectOS Phase 2 Google Interface Implementation Plan

> **For the implementing controller:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not delegate unless the user separately authorizes an implementation agent.

**Goal:** Build the portable, staged Google Sheet contract, retry-safe synchronization engine, and server-authorized GAS web application while keeping SQLite authoritative and all live Google writes disabled.

**Architecture:** Phase 2 extends the Phase 1 Python package with migration `0002`, canonical users/bindings, a pure contract layer, fake and optional real Google gateways, authorization/request/projection services, and a single-writer sync runner. GAS is built from ordered modular sources into deterministic Apps Script artifacts and reads only verified active projection revisions; all automated tests use invented fixtures and the fake gateway.

**Tech Stack:** Python 3.11+ standard library and SQLite; optional `google-api-python-client>=2,<3` and `google-auth>=2,<3` extras for the inert-by-default real gateway; Apps Script V8 JavaScript; Node.js 20+ built-in test runner and standard-library build scripts; HTML/CSS/vanilla JavaScript for the web UI.

**Spec:** `docs/superpowers/specs/2026-09-26-projectos-phase-2-google-interface-design.md`

## Global Constraints

- `projectos.db` remains the single source of truth; Google data is projection, proposal, access-event, conflict, or status data.
- The Phase 1 base is commit `267a035`; all Phase 1 tests remain mandatory.
- SQLite migration `0002` is forward-only, transactional, idempotent, and refuses newer schemas.
- Exactly one protected active Owner exists; Sheet/GAS input cannot replace, remove, disable, or demote that Owner.
- Admin may propose allowlisted changes to PUBLIC records only; User is PUBLIC view-only; unlisted, inactive, blank, or malformed callers receive no project data.
- PRIVATE existence is filtered before serialization, search, count, relationship, error, audit, analytics, and diagnostics paths.
- Direct Sheet access is Owner/automation-only and does not follow User Manifest membership.
- Machine paths, owner notes, credential references, conflicts, configuration, diagnostics, and raw audit data are Owner-only.
- Secret material is rejected before persistence, publication, logging, fixtures, exports, or diagnostic bundles.
- Remote request UUID/hash replays are idempotent; UUID reuse with different content is tampering.
- A local commit followed by remote failure is retried as publication only; the domain mutation is never applied twice.
- A projection revision becomes active only after read-back header, row-count, and hash verification.
- Sync checkpoints advance only after durable local results and verified remote activation.
- The fake gateway is the only gateway used by automated integration and release-candidate tests.
- The real gateway imports optionally and performs no network call without an explicit method invocation.
- Google writes require configured identifiers, resolved credentials, successful identity/contract/sharing preflight, binding `enabled=true`, binding `write_enabled=true`, real-gateway selection, and an explicit CLI write flag.
- No live Google, GAS, Drive, GCP, Context OS, `launchd`, or Looker state changes during this plan.
- At plan start, resolve a Python 3.11+ executable and substitute it for `<python>` in every command. On the current build host the validated executable is `/opt/homebrew/bin/python3`.

## Review Focus

- GAS returns a blank or malformed active-user email: `gas/test/auth.test.js` must prove generic denial and zero query/serialization calls.
- A previously received request row is edited, deleted, or reuses its UUID with a different payload: `tests/test_change_requests.py` must prove tamper rejection, immutable receipts, and no domain mutation.
- SQLite commits but remote result/projection publication fails: `tests/test_sync_service.py` must prove retry publishes the durable result without a second version increment or audit mutation.
- A PRIVATE entity is reachable indirectly through search text, counts, graph edges, child IDs, errors, diagnostics, or request results: `tests/test_authorization.py` and GAS serialization tests must prove no distinguishing output.
- The workbook has unexpected sharing, contract version, tabs, reordered headers, or unknown data: `tests/test_workbook_contract.py` and `tests/test_real_gateway.py` must prove a non-mutating plan or fail-closed preflight, never silent repair.

---

## File Structure

```text
pyproject.toml                              Optional Google dependency metadata
build_backend.py                           Emits optional dependency wheel metadata
config/projectos.example.toml              Identifier-free portable configuration
src/projectos/database.py                  Generic numbered migration runner, schema v2
src/projectos/migrations/0002.sql           Users, bindings, receipts, revisions, request extensions
src/projectos/users.py                     Protected Owner and User Manifest repository
src/projectos/bindings.py                  Workbook binding repository and write gates
src/projectos/google/__init__.py            Google interface package exports
src/projectos/google/types.py               Contract/gateway immutable data types
src/projectos/google/contract.py            Workbook/tab/header contract and hashes
src/projectos/google/bootstrap.py           Non-mutating bootstrap/repair planner
src/projectos/google/gateway.py             GoogleGateway protocol
src/projectos/google/fake_gateway.py        Deterministic fixture gateway and failure injection
src/projectos/google/real_gateway.py        Optional official-API adapter and read/write gates
src/projectos/google/config.py              Portable TOML loading and validation
src/projectos/google/diagnostics.py         Redacted diagnostic bundle service
src/projectos/sync/__init__.py              Sync package exports
src/projectos/sync/types.py                 Roles, permissions, requests, projections, run results
src/projectos/sync/authorization.py         Caller/visibility/field authorization
src/projectos/sync/mutations.py             Typed allowlisted domain mutation dispatch
src/projectos/sync/requests.py              Receipt, access-event, mutation, and conflict processing
src/projectos/sync/projection.py            Role-safe rows, hashes, revisions, publication
src/projectos/sync/lock.py                  Non-blocking machine-local file lock
src/projectos/sync/service.py               Plan/run/status/checkpoint orchestration
src/projectos/cli.py                        Phase 2 JSON CLI commands and exit mapping
gas/appsscript.json                         Staged Apps Script manifest without live IDs
gas/source-order.json                       One authoritative server build order
gas/src/server/*.js                         Modular Apps Script server sources
gas/src/client/index.html                   Web application shell
gas/src/client/styles.html                  Context OS Native styles
gas/src/client/app.html                     Browser interaction code
gas/scripts/build.mjs                       Deterministic GAS concatenation/build
gas/scripts/preview.mjs                     Local fixture-only UI preview server
gas/test/*.test.js                          Node authorization, request, filtering, and build tests
gas/test/fixtures/ui-roles.json              Invented Owner/Admin/User UI states
tests/fixtures/google/*.json                Invented workbook, request, role, drift, and failure fixtures
tests/test_database_phase2.py               v1-to-v2 and fresh-v2 migration tests
tests/test_users_bindings.py                Owner/User Manifest and write-gate tests
tests/test_workbook_contract.py             Contract, hashing, bootstrap, and drift tests
tests/test_fake_gateway.py                  Protocol and injected-failure tests
tests/test_authorization.py                 Cross-role/visibility/side-channel tests
tests/test_change_requests.py               Receipt, access, conflict, replay, and tamper tests
tests/test_projection.py                    Role-safe revision bundle tests
tests/test_sync_service.py                  Lock/checkpoint/interruption/retry integration tests
tests/test_real_gateway.py                  Optional import and fail-closed preflight tests
tests/test_diagnostics.py                   Redaction and PRIVATE-data exclusion tests
tests/test_cli_phase2.py                     JSON commands, flags, and exit-code tests
docs/PHASE2_OPERATIONS.md                    Staged operations and recovery
docs/PHASE2_SCHEMA.md                        SQLite/workbook/request contract reference
docs/PHASE2_VERIFICATION.md                  Exact release evidence
```

### Task 1: Generic Migration Runner and Schema Version 2

**Files:**
- Modify: `src/projectos/database.py`
- Create: `src/projectos/migrations/0002.sql`
- Create: `tests/test_database_phase2.py`
- Modify: `tests/test_database.py`

**Interfaces:**
- Consumes: Phase 1 `ProjectOSDatabase`, `schema_migrations`, operational tables, and schema version `1`.
- Produces: `Migration(version, name, sql)`; runtime-checkable `MigrationSource.list() -> tuple[Migration, ...]`; `PackagedMigrationSource`; optional `ProjectOSDatabase(path, migration_source=None)` injection; `SCHEMA_VERSION = 2`; ordered application of `NNNN.sql` migrations; fresh-v2 and v1-to-v2 databases; tables `users`, `google_bindings`, `remote_request_receipts`, `remote_access_receipts`, and `projection_revisions`; Phase 2 columns/indexes on existing request/sync tables.

- [ ] **Step 1: Write failing migration tests**

Add tests named `test_fresh_database_reaches_schema_two`, `test_phase_one_database_migrates_without_data_loss`, `test_migration_two_is_idempotent`, `test_migration_failure_rolls_back_version_and_schema`, and `test_newer_than_two_still_fails_closed`. Assert all Phase 1 rows survive, all Phase 2 tables/columns/indexes exist, and no partial `0002` row remains after injected SQL failure.

- [ ] **Step 2: Run tests and verify the intended failure**

Run: `<python> -m unittest tests.test_database_phase2 -v`  
Expected: FAIL because schema version `2` and migration `0002` do not exist.

- [ ] **Step 3: Implement generic ordered migrations and `0002.sql`**

Implement `PackagedMigrationSource` by enumerating packaged resources with a four-digit prefix. Validate that versions are unique, contiguous, and at most `SCHEMA_VERSION`; then apply each missing migration in order inside one explicit transaction and record its filename/version only after its SQL succeeds. Tests inject a deliberately failing `MigrationSource`, avoiding edits to packaged SQL. `0002.sql` implements the exact constraints and columns from Sections 5.1–5.7 of the spec without dropping or recreating Phase 1 domain tables.

- [ ] **Step 4: Run migration and Phase 1 database tests**

Run: `<python> -m unittest tests.test_database_phase2 tests.test_database -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/projectos/database.py src/projectos/migrations/0002.sql tests/test_database.py tests/test_database_phase2.py
git -c commit.gpgsign=false commit -m "feat: add ProjectOS phase 2 schema"
```

### Task 2: Protected Users and Workbook Bindings

**Files:**
- Create: `src/projectos/google/__init__.py`
- Create: `src/projectos/google/types.py`
- Create: `src/projectos/users.py`
- Create: `src/projectos/bindings.py`
- Create: `tests/test_users_bindings.py`

**Interfaces:**
- Consumes: schema-v2 tables and Phase 1 audit/validation/transaction contracts.
- Produces: `UserRole`; immutable `UserCreate`, `UserPatch`, `UserRecord`, `GoogleBindingCreate`, `GoogleBindingPatch`, and `GoogleBindingRecord`; `UserRepository(database, protected_owner_email)` with `seed_owner`, `create`, `get_by_email`, `list`, `update`, and `deactivate`; `GoogleBindingRepository` with `create`, `get`, `update`, `list`, and `assert_write_ready`.

- [ ] **Step 1: Write failing protected-owner and binding tests**

Add tests named `test_seed_owner_is_idempotent_and_normalizes_email`, `test_second_owner_is_rejected`, `test_protected_owner_cannot_be_demoted_disabled_or_replaced`, `test_admin_and_user_records_version_normally`, `test_binding_contains_only_safe_credential_reference`, `test_binding_write_gate_requires_every_flag_and_identifier`, and `test_user_and_binding_audits_share_the_mutation_transaction`.

- [ ] **Step 2: Run tests and verify failure**

Run: `<python> -m unittest tests.test_users_bindings -v`  
Expected: FAIL because user/binding interfaces do not exist.

- [ ] **Step 3: Implement repositories and immutable types**

Normalize emails with trim/lowercase and reject blank/malformed addresses. Anchor the protected Owner in the repository constructor; ordinary mutations may manage only non-Owner users. Binding readiness requires safe IDs, contract version, enabled/write-enabled flags, and an existing credential reference, but never resolves a credential value.

- [ ] **Step 4: Run user, credential, and database tests**

Run: `<python> -m unittest tests.test_users_bindings tests.test_credentials tests.test_database_phase2 -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/projectos/google src/projectos/users.py src/projectos/bindings.py tests/test_users_bindings.py
git -c commit.gpgsign=false commit -m "feat: add protected users and Google bindings"
```

### Task 3: Workbook Contract and Non-Mutating Bootstrap Planner

**Files:**
- Create: `src/projectos/google/contract.py`
- Create: `src/projectos/google/bootstrap.py`
- Create: `tests/fixtures/google/empty-contract-v1.json`
- Create: `tests/fixtures/google/populated-contract-v1.json`
- Create: `tests/fixtures/google/drifted-contract.json`
- Create: `tests/test_workbook_contract.py`

**Interfaces:**
- Consumes: Phase 2 contract types.
- Produces: `WorkbookContract.current() -> WorkbookContract`; `canonical_json_bytes(value) -> bytes`; `contract_hash(contract) -> str`; `WorkbookSnapshot`; `BootstrapAction`; `BootstrapPlan`; and `WorkbookBootstrapPlanner.plan(snapshot, contract) -> BootstrapPlan` with no gateway/write dependency.

- [ ] **Step 1: Write failing contract/hash/plan tests**

Add tests named `test_contract_v1_has_exact_tabs_headers_and_visibility_classes`, `test_canonical_hash_matches_cross_language_golden_fixture`, `test_empty_workbook_plan_creates_without_mutating`, `test_compliant_workbook_plan_is_noop`, `test_reordered_or_missing_headers_are_explicit_drift`, `test_unknown_populated_tab_is_never_repurposed`, and `test_owner_drafts_access_events_and_request_columns_match_spec`.

- [ ] **Step 2: Run tests and verify failure**

Run: `<python> -m unittest tests.test_workbook_contract -v`  
Expected: FAIL because contract/planner interfaces do not exist.

- [ ] **Step 3: Implement the pure workbook contract and planner**

Encode every tab/header from Section 6 in one immutable contract. Hash UTF-8 canonical JSON with recursively sorted object keys, preserved array order, and compact separators. Plans classify create, protect, format, repair, unknown-data, and blocking-drift actions without performing them.

- [ ] **Step 4: Run workbook tests**

Run: `<python> -m unittest tests.test_workbook_contract -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/projectos/google/contract.py src/projectos/google/bootstrap.py tests/fixtures/google tests/test_workbook_contract.py
git -c commit.gpgsign=false commit -m "feat: define the ProjectOS workbook contract"
```

### Task 4: Google Gateway Protocol and Deterministic Fake

**Files:**
- Create: `src/projectos/google/gateway.py`
- Create: `src/projectos/google/fake_gateway.py`
- Create: `tests/test_fake_gateway.py`

**Interfaces:**
- Consumes: workbook contract/snapshot and immutable Google types.
- Produces: runtime-checkable `GoogleGateway` protocol with `preflight`, `read_contract`, `pull_requests`, `pull_access_events`, `publish_results`, and `publish_projection`; `FakeGoogleGateway.from_fixture`; `FailurePoint` enum; call log and deterministic failure injection before/after each boundary.

- [ ] **Step 1: Write failing protocol/fake tests**

Add tests named `test_fake_implements_gateway_protocol`, `test_fake_pull_order_and_cursor_are_deterministic`, `test_fake_records_calls_without_secret_values`, `test_failure_injection_is_one_shot_or_persistent_as_configured`, `test_fake_rejects_write_when_binding_gate_is_closed`, and `test_historical_payload_digest_detects_remote_edit_or_delete`.

- [ ] **Step 2: Run tests and verify failure**

Run: `<python> -m unittest tests.test_fake_gateway -v`  
Expected: FAIL because gateway interfaces do not exist.

- [ ] **Step 3: Implement the protocol and fake gateway**

The fake stores invented rows/revisions in memory, copies inputs/outputs to avoid test mutation, computes the same hashes as the contract layer, and exposes failure controls only through test construction.

- [ ] **Step 4: Run gateway and contract tests**

Run: `<python> -m unittest tests.test_fake_gateway tests.test_workbook_contract -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/projectos/google/gateway.py src/projectos/google/fake_gateway.py tests/test_fake_gateway.py
git -c commit.gpgsign=false commit -m "feat: add the fake Google gateway"
```

### Task 5: Authorization and Role-Safe Serialization

**Files:**
- Create: `src/projectos/sync/__init__.py`
- Create: `src/projectos/sync/types.py`
- Create: `src/projectos/sync/authorization.py`
- Create: `tests/fixtures/google/role-matrix.json`
- Create: `tests/test_authorization.py`

**Interfaces:**
- Consumes: canonical users/projects/assets and spec field classifications.
- Produces: `Capability`, `FieldPolicy`, `AuthorizationContext`; `AuthorizationService.resolve(email)`, `authorize_operation(context, operation)`, `filter_entity(context, entity)`, `filter_search`, `filter_counts`, `filter_connections`, and `safe_not_found`; role-safe DTOs that contain no database rows or unrestricted metadata mappings.

- [ ] **Step 1: Write the complete role/private-leak matrix**

Add tests named `test_blank_unlisted_inactive_and_malformed_callers_get_no_data`, `test_user_views_only_public_safe_fields`, `test_admin_edits_only_allowlisted_public_fields`, `test_owner_sees_owner_only_fields`, `test_private_absence_is_indistinguishable_from_not_found`, `test_search_counts_errors_graph_and_children_do_not_leak_private_existence`, and `test_connection_is_hidden_when_either_endpoint_is_invisible`.

- [ ] **Step 2: Run tests and verify failure**

Run: `<python> -m unittest tests.test_authorization -v`  
Expected: FAIL because authorization interfaces do not exist.

- [ ] **Step 3: Implement authorization before serialization**

Use explicit capability/field tables, not scattered role conditionals. Resolve role only from canonical active users. Build new allowlisted DTOs; never remove fields from a previously unrestricted dictionary after serialization.

- [ ] **Step 4: Run authorization and Phase 1 connection tests**

Run: `<python> -m unittest tests.test_authorization tests.test_assets tests.test_users_bindings -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/projectos/sync tests/fixtures/google/role-matrix.json tests/test_authorization.py
git -c commit.gpgsign=false commit -m "feat: enforce ProjectOS Google authorization"
```

### Task 6: Remote Receipts, Access Events, Mutations, and Conflicts

**Files:**
- Modify: `src/projectos/types.py`
- Modify: `src/projectos/repositories.py`
- Create: `src/projectos/sync/mutations.py`
- Create: `src/projectos/sync/requests.py`
- Create: `tests/fixtures/google/request-lifecycle.json`
- Create: `tests/test_change_requests.py`

**Interfaces:**
- Consumes: authorization service, repositories, transactions, audit, canonical JSON/hash, and receipt/conflict tables.
- Produces: immutable patch/command types for explicitly supported mutations; repository `update`/`archive` methods that require `expected_version`; `MutationRegistry.apply(request, context) -> MutationResult` with explicit Project, Location, Resource, Deployment, Connection, and non-Owner User handlers; `RemoteRequest`, `RemoteAccessEvent`, `RequestResult`, `RequestProcessor.ingest`, `RequestProcessor.process`, `AccessEventProcessor.ingest`; idempotent receipt lookup; typed result codes `ACCEPTED`, `CONFLICT`, `REJECTED_AUTHORIZATION`, `REJECTED_VALIDATION`, `REJECTED_TAMPERED`, and `RETRYABLE_REMOTE_FAILURE`.

- [ ] **Step 1: Write failing lifecycle, review-focus, and secret tests**

Add tests named `test_identical_request_replay_returns_durable_result`, `test_uuid_reuse_with_changed_payload_is_tampering`, `test_historical_row_edit_or_delete_fails_closed`, `test_unauthorized_and_secret_requests_never_open_domain_mutation`, `test_stale_base_version_creates_conflict_without_change`, `test_each_supported_entity_operation_uses_typed_allowlisted_handler`, `test_admin_cannot_change_stable_ids_visibility_paths_credentials_or_users`, `test_accepted_request_mutation_receipt_and_audit_are_atomic`, `test_owner_resolution_creates_new_transaction_without_rewriting_history`, and `test_access_event_is_idempotent_and_only_advances_last_access`.

- [ ] **Step 2: Run tests and verify failure**

Run: `<python> -m unittest tests.test_change_requests -v`  
Expected: FAIL because request processors do not exist.

- [ ] **Step 3: Implement deterministic validation and processing order**

Apply the ten validation stages from Section 8.2 verbatim. Route only recognized `(entity_type, operation)` pairs through `MutationRegistry`; each handler converts the allowlisted payload into a typed command, preserves immutable stable identifiers on update, and calls an optimistic repository method. `CREATE`, `UPDATE`, and `ARCHIVE` are implemented only where the workbook contract exposes them; unsupported pairs fail validation rather than falling back to generic SQL. Persist a normalized safe receipt before processing, use one outer transaction for accepted domain/audit/result writes, and store safe result codes/messages without invisible current values.

- [ ] **Step 4: Run request, authorization, and repository tests**

Run: `<python> -m unittest tests.test_change_requests tests.test_authorization tests.test_projects tests.test_assets -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/projectos/types.py src/projectos/repositories.py src/projectos/sync/mutations.py src/projectos/sync/requests.py tests/fixtures/google/request-lifecycle.json tests/test_change_requests.py
git -c commit.gpgsign=false commit -m "feat: process immutable Google change requests"
```

### Task 7: Projection Bundles and Verified Revision Publication

**Files:**
- Create: `src/projectos/sync/projection.py`
- Create: `tests/test_projection.py`

**Interfaces:**
- Consumes: role-safe serializers, canonical repositories, workbook contract, projection-revision table, and gateway publication methods.
- Produces: `ProjectionBuilder.build(connection, revision_id) -> ProjectionBundle`; stable per-tab rows/counts/hashes; `ProjectionPublisher.stage_and_activate(binding, bundle, gateway) -> PublicationReceipt`; revision state transitions `STAGED`, `ACTIVE`, `FAILED`, and `SUPERSEDED`.

- [ ] **Step 1: Write failing projection/revision tests**

Add tests named `test_bundle_uses_one_sqlite_read_snapshot`, `test_projection_rows_have_stable_order_version_revision_and_hash`, `test_private_and_owner_only_fields_never_enter_public_dtos`, `test_readback_mismatch_keeps_previous_revision_active`, `test_success_activates_pointer_last_and_supersedes_prior_revision`, and `test_result_publication_contains_only_safe_messages`.

- [ ] **Step 2: Run tests and verify failure**

Run: `<python> -m unittest tests.test_projection -v`  
Expected: FAIL because projection interfaces do not exist.

- [ ] **Step 3: Implement snapshot building and verified activation**

Sort rows by stable UUID, generate contract-ordered columns, and hash canonical cell representations. Persist local revision state around gateway calls; remote verification mismatch records failure and never changes the active pointer or checkpoint.

- [ ] **Step 4: Run projection, gateway, and authorization tests**

Run: `<python> -m unittest tests.test_projection tests.test_fake_gateway tests.test_authorization -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/projectos/sync/projection.py tests/test_projection.py
git -c commit.gpgsign=false commit -m "feat: publish verified Google projections"
```

### Task 8: Single-Writer Sync Runner, Checkpoints, and Retry Recovery

**Files:**
- Create: `src/projectos/sync/lock.py`
- Create: `src/projectos/sync/service.py`
- Create: `tests/fixtures/google/interruption-scenarios.json`
- Create: `tests/test_sync_service.py`

**Interfaces:**
- Consumes: database doctor, bindings, fake/real gateway protocol, request/access processors, projection publisher, sync runs/checkpoints.
- Produces: `ProjectOSFileLock(path)` non-blocking context manager; `GoogleSyncService.plan(binding_id) -> SyncPlan`; `run(binding_id, trigger) -> SyncRunResult`; `status(binding_id) -> SyncStatus`; safe lock metadata and structured run summaries.

- [ ] **Step 1: Write failing end-to-end and interruption tests**

Add tests named `test_second_sync_exits_without_remote_or_database_write`, `test_preflight_failure_records_safe_run_and_preserves_checkpoint`, `test_happy_path_processes_requests_access_and_projection_then_advances_checkpoint`, `test_local_commit_remote_failure_retry_does_not_mutate_twice`, `test_failure_at_every_gateway_boundary_keeps_retry_invariants`, `test_checkpoint_never_advances_before_verified_activation`, and `test_stale_lock_recovery_requires_dead_pid_and_owned_lock_format`.

- [ ] **Step 2: Run tests and verify failure**

Run: `<python> -m unittest tests.test_sync_service -v`  
Expected: FAIL because lock/runner interfaces do not exist.

- [ ] **Step 3: Implement the 14-step sync sequence**

Keep the service as orchestration: it calls narrow components and owns run/checkpoint transitions. Use `fcntl.flock` on macOS, safe JSON lock metadata, deterministic receipt order, and explicit failure states. A retry reuses durable request outcomes and creates a new publication attempt without repeating domain mutations.

- [ ] **Step 4: Run sync and all local Google-domain tests**

Run: `<python> -m unittest tests.test_sync_service tests.test_change_requests tests.test_projection tests.test_fake_gateway -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/projectos/sync/lock.py src/projectos/sync/service.py tests/fixtures/google/interruption-scenarios.json tests/test_sync_service.py
git -c commit.gpgsign=false commit -m "feat: add retry-safe Google synchronization"
```

### Task 9: Portable Configuration, Real Gateway, and Safe Diagnostics

**Files:**
- Create: `config/projectos.example.toml`
- Create: `src/projectos/google/config.py`
- Create: `src/projectos/google/real_gateway.py`
- Create: `src/projectos/google/diagnostics.py`
- Modify: `pyproject.toml`
- Modify: `build_backend.py`
- Create: `tests/test_real_gateway.py`
- Create: `tests/test_diagnostics.py`
- Modify: `tests/test_build_backend.py`

**Interfaces:**
- Consumes: binding/gateway protocol, workbook planner, doctor, redaction, ProjectOS home resolution.
- Produces: `ProjectOSGoogleConfig.load(path=None, environ=None)`; `RealGoogleGateway` with optional imports and injected credential/client factories; read-only `preflight`; guarded write methods; `DiagnosticBundleService.create(destination) -> DiagnosticManifest`; optional wheel extra `projectos[google]`.

- [ ] **Step 1: Write failing portability, gate, and diagnostic tests**

Add tests named `test_config_resolution_uses_argument_then_projectos_home_then_macos_default`, `test_example_has_no_real_identifiers_or_absolute_home`, `test_core_imports_without_google_packages`, `test_real_gateway_does_no_network_work_on_construction`, `test_preflight_blocks_identity_contract_or_sharing_mismatch`, `test_write_requires_all_binding_and_cli_gates`, `test_diagnostic_bundle_excludes_secrets_emails_private_counts_and_rows`, and `test_wheel_metadata_contains_optional_google_extra_without_core_dependency`.

- [ ] **Step 2: Run tests and verify failure**

Run: `<python> -m unittest tests.test_real_gateway tests.test_diagnostics tests.test_build_backend -v`  
Expected: FAIL because config/real gateway/diagnostics and optional metadata do not exist.

- [ ] **Step 3: Implement optional official-API adapter and redacted diagnostics**

Import Google libraries inside an injected factory path and convert missing extras into a structured configuration error. Inspect Drive permissions read-only during preflight. Never auto-remove sharing. Extend the standard-library wheel backend to emit `Provides-Extra`/`Requires-Dist` from `pyproject.toml` without adding build dependencies.

- [ ] **Step 4: Run portability/package tests and build the core wheel offline**

Run: `<python> -m unittest tests.test_real_gateway tests.test_diagnostics tests.test_build_backend -v`  
Run: `<python> -m pip wheel . --no-deps --no-build-isolation -w build/wheel-check`  
Expected: tests PASS and one `projectos` wheel builds without downloading dependencies.

- [ ] **Step 5: Commit**

```bash
git add config/projectos.example.toml src/projectos/google/config.py src/projectos/google/real_gateway.py src/projectos/google/diagnostics.py pyproject.toml build_backend.py tests/test_real_gateway.py tests/test_diagnostics.py tests/test_build_backend.py
git -c commit.gpgsign=false commit -m "feat: add guarded real Google integration"
```

### Task 10: Phase 2 JSON CLI

**Files:**
- Modify: `src/projectos/cli.py`
- Create: `tests/test_cli_phase2.py`

**Interfaces:**
- Consumes: user/binding/contract/bootstrap/sync/conflict/diagnostic services.
- Produces commands `user seed-owner|create|list|update|deactivate`; `google binding create|get|list|update`; `google contract show|plan`; `google preflight`; `sync plan|run|status`; `conflict list|resolve`; and `diagnostics create`. Real writes require `sync run --gateway google --allow-google-writes` plus ready binding.

- [ ] **Step 1: Write failing CLI contract and secret-safety tests**

Add tests named `test_phase2_commands_keep_single_json_envelope`, `test_user_and_binding_validation_exit_two`, `test_sync_lock_and_preflight_failure_exit_three`, `test_google_write_requires_explicit_gateway_and_flag`, `test_fake_sync_end_to_end_is_idempotent`, `test_conflict_resolution_is_owner_only`, `test_diagnostics_response_contains_manifest_not_private_data`, and `test_cli_parser_never_echoes_google_or_user_input`.

- [ ] **Step 2: Run tests and verify failure**

Run: `<python> -m unittest tests.test_cli_phase2 -v`  
Expected: FAIL because Phase 2 commands do not exist.

- [ ] **Step 3: Extend parsing and dispatch without weakening Phase 1 envelopes**

Keep typed conversion in dispatch helpers, print one JSON document, and retain exit codes `0`, `1`, `2`, and `3`. Default sync gateway is `fake`; selecting `google` without the explicit write flag permits preflight/plan only.

- [ ] **Step 4: Run Phase 2 and Phase 1 CLI tests**

Run: `<python> -m unittest tests.test_cli_phase2 tests.test_cli -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/projectos/cli.py tests/test_cli_phase2.py
git -c commit.gpgsign=false commit -m "feat: expose staged Google sync commands"
```

### Task 11: Deterministic GAS Build and Server Authorization

**Files:**
- Create: `gas/package.json`
- Create: `gas/appsscript.json`
- Create: `gas/source-order.json`
- Create: `gas/scripts/build.mjs`
- Create: `gas/src/server/00_Namespace.js`
- Create: `gas/src/server/10_Config.js`
- Create: `gas/src/server/20_Contract.js`
- Create: `gas/src/server/30_Auth.js`
- Create: `gas/src/server/40_DataService.js`
- Create: `gas/src/server/50_RequestService.js`
- Create: `gas/src/server/60_AdminService.js`
- Create: `gas/src/server/70_Menu.js`
- Create: `gas/src/server/90_Entry.js`
- Create: `gas/test/helpers/load-gas.js`
- Create: `gas/test/build.test.js`
- Create: `gas/test/auth.test.js`
- Create: `gas/test/serialization.test.js`
- Create: `gas/test/requests.test.js`

**Interfaces:**
- Consumes: workbook contract v1 and canonical hash golden fixtures copied/generated from Python tests.
- Produces: deterministic `gas/dist/Code.gs`; server functions `doGet`, role-safe project/search/detail/status query methods, `submitChangeRequest`, `submitOwnerDraft`, `submitUserChangeRequest`, and Owner-only conflict/admin query methods; no live IDs in manifest/source.

- [ ] **Step 1: Write failing Node build/auth/request tests**

Tests prove source order is explicit and deterministic; blank/unlisted/inactive callers invoke no data service; User/Admin/Owner responses match golden role-safe fixtures; PRIVATE values do not appear in serialized JSON; client roles are ignored; request hashes match Python; `LockService` guards request/access/draft append; and only protected Owner can invoke draft/user/admin operations.

- [ ] **Step 2: Run tests and verify failure**

Run: `node --test gas/test/*.test.js`  
Expected: FAIL because GAS sources/build/tests do not exist.

- [ ] **Step 3: Implement ordered GAS server sources and standard-library build**

Use one global namespace and late-bound functions so module initialization does not depend on Apps Script file order. The build script reads only `source-order.json`, concatenates server sources with source banners, copies HTML assets in later tasks, and writes deterministic `dist` output. Server functions resolve identity from `Session`, validate contract/active revision, filter before serialization, and map errors to generic safe codes.

- [ ] **Step 4: Run GAS and Python cross-language hash/authorization tests**

Run: `node --test gas/test/*.test.js`  
Run: `<python> -m unittest tests.test_workbook_contract tests.test_authorization -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add gas
git -c commit.gpgsign=false commit -m "feat: add server-authorized ProjectOS GAS app"
```

### Task 12: Context OS Native GAS Web UI

**Files:**
- Create: `gas/src/client/index.html`
- Create: `gas/src/client/styles.html`
- Create: `gas/src/client/app.html`
- Create: `gas/scripts/preview.mjs`
- Create: `gas/test/fixtures/ui-roles.json`
- Create: `gas/test/client.test.js`
- Create: `gas/test/accessibility.test.js`
- Modify: `gas/scripts/build.mjs`
- Modify: `gas/test/build.test.js`

**Interfaces:**
- Consumes: role-safe GAS server methods only.
- Produces: responsive project list/search/filter, project details, permitted relationship/deployment/resource views, request edit/status flow, and Owner-only Users/Conflicts/Audit/Settings routes; local preview fixture mode that never calls Google.

- [ ] **Step 1: Write failing UI behavior and accessibility tests**

Tests prove User has no edit/admin controls; Admin has edit but no admin controls; Owner has admin routes; maintenance/access-denied/not-found/pending/conflict/rejected states render distinct safe copy; HTML uses landmarks, labels, keyboard-operable controls, focus styles, and no client role can unlock a server method.

- [ ] **Step 2: Run tests and verify failure**

Run: `node --test gas/test/*.test.js`  
Expected: FAIL because client assets and behavior do not exist.

- [ ] **Step 3: Implement the Context OS Native interface**

Use graphite surfaces, cobalt actions/focus, teal health, amber warnings, red errors, 44-pixel interactive targets, compact desktop layout, and responsive single-column behavior. Client code treats server authorization errors as final and never caches unrestricted workbook rows.

- [ ] **Step 4: Run automated and visual verification**

Run: `node --test gas/test/*.test.js`  
Run: `node gas/scripts/preview.mjs --fixture gas/test/fixtures/ui-roles.json --port 4173`  
Inspect `http://127.0.0.1:4173/?role=owner`, `?role=admin`, and `?role=user` at desktop and narrow widths, then stop the preview process.  
Expected: tests PASS and visual inspection confirms hierarchy, contrast, focus, role controls, empty/error states, and no PRIVATE fixture content outside Owner view.

- [ ] **Step 5: Commit**

```bash
git add gas/src/client gas/scripts/build.mjs gas/scripts/preview.mjs gas/test
git -c commit.gpgsign=false commit -m "feat: add the ProjectOS Google web interface"
```

### Task 13: Portable Operations, Clean-Room Verification, and Phase Boundary

**Files:**
- Modify: `README.md`
- Create: `docs/PHASE2_OPERATIONS.md`
- Create: `docs/PHASE2_SCHEMA.md`
- Create: `docs/PHASE2_VERIFICATION.md`
- Modify: `docs/PHASE2_CLAUDE_IMPLEMENTATION_AND_TROUBLESHOOTING.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: every Phase 2 command, fake workflow, GAS build, configuration, and diagnostic contract.
- Produces: identifier-free installation/operation/recovery documentation; exact release evidence; updated Claude handoff; ignored local config, diagnostics, GAS dist, and runtime state.

- [ ] **Step 1: Document staged operation and recovery**

Cover ProjectOS home resolution, owner onboarding, fake workflow, contract planning, activation Levels A/B/C, binding/write gates, request/conflict lifecycle, lock recovery, backup/restore, diagnostic bundles, GAS build, and the explicit prohibition on live deployment in this phase.

- [ ] **Step 2: Run the complete Python and GAS suites once for the release candidate**

Run: `<python> -m unittest discover -s tests -v`  
Run: `node --test gas/test/*.test.js`  
Expected: all tests PASS with no skips or warnings.

- [ ] **Step 3: Run packaging and static gates**

Run: `<python> -m compileall -q build_backend.py src tests`  
Run: `<python> -m pip wheel . --no-deps --no-build-isolation -w build/wheel-check`  
Run: `node gas/scripts/build.mjs` twice and compare checksums  
Run: `git diff --check`  
Expected: compilation and diff checks exit `0`; core wheel builds offline; both GAS builds are byte-identical.

- [ ] **Step 4: Exercise a clean-room local Level A workflow**

Install the wheel into a new temporary Python 3.11+ virtual environment, use an isolated `PROJECTOS_HOME`, initialize/migrate from a copied Phase 1 fixture, seed the protected Owner, create Admin/User and a disabled Google binding, plan the workbook, run fake sync requests covering accepted/rejected/conflict/access events, inject a post-commit publication failure, retry without a second mutation, publish/verify a revision, create/scan a diagnostic bundle, build GAS, and render all three role fixtures. Assert all CLI results are one JSON document, the final doctor is healthy, and no live gateway is instantiated.

- [ ] **Step 5: Reconcile evidence and commit the Phase 2 release candidate**

Record exact commands, counts, hashes, smoke results, agent/correction/full-suite counts, known limitations, and confirmation that Google and Context OS state were untouched.

```bash
git add README.md docs/PHASE2_OPERATIONS.md docs/PHASE2_SCHEMA.md docs/PHASE2_VERIFICATION.md docs/PHASE2_CLAUDE_IMPLEMENTATION_AND_TROUBLESHOOTING.md .gitignore
git -c commit.gpgsign=false commit -m "docs: complete ProjectOS phase 2 operations"
```

## Phase Boundary

Stop after Task 13. Report the Phase 2 local release candidate, migrations, fake sync evidence, authorization/private-leak evidence, GAS build/UI evidence, package and clean-room results, known limitations, commit list, and confirmation that no live external state changed. Do not authenticate Google, bootstrap a real Sheet, create/deploy GAS, install scheduling/Context OS adoption, or begin Looker work until the user reviews the evidence and approves a separately written live-staging plan.
