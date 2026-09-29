# ProjectOS Phase 1 Local Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local ProjectOS SQLite system of record, deterministic domain APIs, discovery/provenance pipeline, safe credential-reference tracking, backup/restore, health checks, and structured CLI.

**Architecture:** ProjectOS is a standalone Python package with a machine-local SQLite database and versioned SQL migrations. Domain repositories expose typed operations; services add discovery, audit, backup, and health behavior; a JSON-first CLI is the stable boundary later consumed by Context OS. Phase 1 does not modify Context OS or connect to Google.

**Tech Stack:** Python 3.11+, standard-library `sqlite3`, `dataclasses`, `enum`, `argparse`, `json`, `pathlib`, `hashlib`, `shutil`, `tempfile`, and `unittest`; SQLite WAL and foreign keys; TOML build metadata through `pyproject.toml`.

**Spec:** `docs/superpowers/specs/2026-09-26-projectos-contextos-enhancement-design.md`

## Global Constraints

- `projectos.db` is the single source of truth; no projection or discovery input may overwrite it outside validated repository transactions.
- Phase 1 remains local-only and has no runtime web dependency.
- ProjectOS uses a separate database and never modifies the Context OS SQLite schema.
- Every canonical record has a stable UUID, integer version, timestamps, lifecycle state, and provenance.
- Local paths are machine scoped and normalized without discarding the user-supplied path.
- Secret values, tokens, private keys, passwords, and directly usable authentication material are prohibited from domain records, audit payloads, backups, and CLI output.
- Domain deletion is archival/tombstone behavior; Phase 1 provides no purge command.
- Schema changes are applied only by numbered SQL migrations recorded in `schema_migrations`.
- Mutations that affect multiple rows run in explicit transactions and append an audit event.
- All CLI success and failure output is structured JSON; success exits `0`, validation/conflict exits `2`, health failure exits `3`, and unexpected internal failure exits `1`.
- No live Context OS installation, Google account, Google Sheet, GAS project, scheduler, or Looker automation is changed in Phase 1.

## Review Focus

- A caller repeats the same migration, registration, or discovery batch: tests must prove idempotency without duplicated rows or audit events that falsely report canonical changes.
- A stale caller updates a project using an old version: tests must prove the repository rejects the update and preserves the current row.
- A path differs only through macOS symlink or `/var` versus `/private/var` resolution: tests must prove normalized comparison while preserving the original path string.
- A candidate or credential payload contains a secret-like key or value: tests must prove rejection/redaction before persistence, audit, backup, or CLI serialization.
- A database or backup is incomplete, corrupt, or from a newer schema: tests must prove fail-closed health/restore behavior without overwriting the current database.

---

## File Structure

```text
pyproject.toml                         Package metadata and `projectos` CLI entrypoint
README.md                              Phase 1 setup, commands, data boundaries, recovery
src/projectos/__init__.py              Public version and package exports
src/projectos/errors.py                Stable domain/CLI exception taxonomy
src/projectos/types.py                 Enums and immutable command/result dataclasses
src/projectos/validation.py            UUID, enum, URL/path, metadata, and secret-safety validation
src/projectos/database.py              SQLite connection, transactions, migration runner
src/projectos/migrations/0001.sql      Complete Phase 1 schema
src/projectos/repositories.py          Canonical project/resource/deployment/connection repositories
src/projectos/credentials.py           Safe credential references, usage, and redaction
src/projectos/audit.py                 Append-only audit API and safe serialization
src/projectos/discovery.py             Candidate findings, adapters, and apply/reject workflow
src/projectos/contextos_adapter.py     Read-only Context OS project-manifest discovery adapter
src/projectos/backup.py                Verified snapshot and fail-closed restore
src/projectos/health.py                Database/schema/integrity doctor
src/projectos/cli.py                   JSON-first command-line interface
tests/helpers.py                       Temporary database and fixture builders
tests/test_database.py                 Migration, transaction, and schema tests
tests/test_projects.py                 Project and version-conflict tests
tests/test_assets.py                   Locations/resources/deployments/connections tests
tests/test_credentials.py              Secret-safety and usage-impact tests
tests/test_discovery.py                Candidate, idempotency, and Context OS adapter tests
tests/test_backup_health.py             Backup, restore, corruption, and doctor tests
tests/test_cli.py                      Exit-code and JSON-contract tests
```

## Task 1: Package, Database Bootstrap, and Migration Runner

**Files:**
- Create: `pyproject.toml`
- Create: `src/projectos/__init__.py`
- Create: `src/projectos/errors.py`
- Create: `src/projectos/database.py`
- Create: `src/projectos/migrations/0001.sql`
- Create: `tests/__init__.py`
- Create: `tests/helpers.py`
- Create: `tests/test_database.py`

**Interfaces:**
- Produces: `ProjectOSDatabase(path: Path)`, `ProjectOSDatabase.initialize() -> ProjectOSDatabase`, `ProjectOSDatabase.transaction() -> ContextManager[sqlite3.Connection]`, `ProjectOSDatabase.schema_version() -> int`, and exceptions `ProjectOSError`, `MigrationError`, `ValidationError`, `VersionConflict`, `HealthError`.
- Consumes: no earlier task interfaces.

- [ ] **Step 1: Write failing database tests**

Add tests named `test_initialize_creates_complete_schema`, `test_initialize_is_idempotent`, `test_transaction_rolls_back_all_rows_on_error`, `test_foreign_keys_are_enabled`, and `test_newer_schema_fails_closed`. Assert schema version `1`, required table names from the specification, WAL mode, no duplicate migration rows, complete rollback, and `MigrationError` for a stored version greater than supported.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python3 -m unittest tests.test_database -v`  
Expected: FAIL because the package and database interfaces do not exist.

- [ ] **Step 3: Implement package metadata, exceptions, migration SQL, and database interfaces**

Set package name `projectos`, initial version `0.1.0`, Python floor `>=3.11`, and console script `projectos = projectos.cli:main`. `0001.sql` creates every Phase 1 table from Sections 4.1–4.8 of the spec, indexes foreign keys and external IDs, enforces enumerated values with `CHECK`, and records migration `1`. `ProjectOSDatabase.initialize()` uses `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, explicit migration transactions, and refuses newer schemas.

- [ ] **Step 4: Run focused tests and verify pass**

Run: `python3 -m unittest tests.test_database -v`  
Expected: all database tests PASS.

- [ ] **Step 5: Commit the database foundation**

```bash
git add pyproject.toml src/projectos tests/helpers.py tests/test_database.py tests/__init__.py
git -c commit.gpgsign=false commit -m "feat: add ProjectOS database foundation"
```

## Task 2: Domain Types, Validation, and Project Repository

**Files:**
- Create: `src/projectos/types.py`
- Create: `src/projectos/validation.py`
- Create: `src/projectos/audit.py`
- Create: `src/projectos/repositories.py`
- Create: `tests/test_projects.py`
- Modify: `tests/helpers.py`

**Interfaces:**
- Consumes: `ProjectOSDatabase.transaction()` and exception types from Task 1.
- Produces: enums `ProjectStatus`, `ProjectVisibility`, `ProjectType`; dataclasses `ProjectCreate`, `ProjectPatch`, `ProjectRecord`; `ProjectRepository.create(command: ProjectCreate, actor: str) -> ProjectRecord`; `ProjectRepository.get(project_id: UUID) -> ProjectRecord | None`; `ProjectRepository.list(include_archived: bool = False) -> list[ProjectRecord]`; `ProjectRepository.update(project_id: UUID, expected_version: int, patch: ProjectPatch, actor: str) -> ProjectRecord`; `ProjectRepository.archive(project_id: UUID, expected_version: int, actor: str) -> ProjectRecord`; and `AuditLog.append(connection, event_type: str, actor: str, entity_type: str, entity_id: str, payload: Mapping[str, Any]) -> str`.

- [ ] **Step 1: Write failing project and review-focus tests**

Add tests named `test_create_project_assigns_stable_uuid_version_and_provenance`, `test_duplicate_slug_is_rejected`, `test_update_requires_current_version`, `test_archive_increments_version_without_delete`, `test_list_excludes_archived_by_default`, `test_repeated_identical_registration_is_idempotent`, and `test_audit_is_in_same_transaction`. Assert timestamps are UTC ISO-8601, visibility accepts only `PUBLIC`/`PRIVATE`, stale updates raise `VersionConflict`, and rollback removes both domain and audit rows.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python3 -m unittest tests.test_projects -v`  
Expected: FAIL because domain and repository interfaces do not exist.

- [ ] **Step 3: Implement types, validation, audit, and project repository**

Use immutable dataclasses for inputs/results and canonical JSON serialization for provenance and metadata. Idempotent registration uses a caller-supplied `source_key` in provenance; replay returns the existing record without a false mutation audit. Updates construct explicit column lists from `ProjectPatch` and use `WHERE project_id = ? AND version = ?` optimistic concurrency.

- [ ] **Step 4: Run project and database tests**

Run: `python3 -m unittest tests.test_projects tests.test_database -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit project-domain behavior**

```bash
git add src/projectos/types.py src/projectos/validation.py src/projectos/audit.py src/projectos/repositories.py tests/helpers.py tests/test_projects.py
git -c commit.gpgsign=false commit -m "feat: add canonical project repository"
```

## Task 3: Locations, Resources, Deployments, and Connections

**Files:**
- Modify: `src/projectos/types.py`
- Modify: `src/projectos/validation.py`
- Modify: `src/projectos/repositories.py`
- Create: `tests/test_assets.py`

**Interfaces:**
- Consumes: `ProjectRepository` and Task 2 validation/audit contracts.
- Produces: `LocationRepository.upsert(project_id: UUID, command: LocationUpsert, actor: str) -> LocationRecord`; `ResourceRepository.upsert(project_id: UUID, command: ResourceUpsert, actor: str) -> ResourceRecord`; `DeploymentRepository.upsert(project_id: UUID, command: DeploymentUpsert, actor: str) -> DeploymentRecord`; `ConnectionRepository.upsert(command: ConnectionUpsert, actor: str) -> ConnectionRecord`; `ConnectionRepository.impact(resource_id: UUID) -> ImpactReport`; and matching typed list/get methods.

- [ ] **Step 1: Write failing asset and path tests**

Add tests named `test_project_can_have_multiple_machine_locations`, `test_location_preserves_original_and_normalizes_resolved_path`, `test_var_and_private_var_compare_as_same_location`, `test_resource_identity_uses_provider_and_external_id_not_url`, `test_project_supports_multiple_prod_and_dev_deployments`, `test_connection_requires_existing_endpoints`, `test_connection_cannot_broaden_private_visibility`, and `test_impact_lists_direct_and_related_projects`.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python3 -m unittest tests.test_assets -v`  
Expected: FAIL because asset repository interfaces do not exist.

- [ ] **Step 3: Implement typed asset repositories**

Normalize paths using `Path.resolve(strict=False)` while retaining the original string. Treat `/var/...` and `/private/var/...` consistently on macOS. Preserve stable resource identity across URL changes. Enforce that dependent records inherit the project visibility and that connections cannot expose a PRIVATE endpoint through a PUBLIC project.

- [ ] **Step 4: Run asset and project tests**

Run: `python3 -m unittest tests.test_assets tests.test_projects -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit asset and relationship support**

```bash
git add src/projectos/types.py src/projectos/validation.py src/projectos/repositories.py tests/test_assets.py
git -c commit.gpgsign=false commit -m "feat: model project assets and connections"
```

## Task 4: Safe Credential References and Usage Analysis

**Files:**
- Create: `src/projectos/credentials.py`
- Modify: `src/projectos/validation.py`
- Modify: `src/projectos/audit.py`
- Create: `tests/test_credentials.py`

**Interfaces:**
- Consumes: database transactions, audit, validation, and project/resource IDs from Tasks 1–3.
- Produces: `CredentialReferenceService.create(command: CredentialReferenceCreate, actor: str) -> CredentialReferenceRecord`; `CredentialReferenceService.link_usage(credential_id: UUID, project_id: UUID, resource_id: UUID | None, purpose: str, actor: str) -> CredentialUsageRecord`; `CredentialReferenceService.impact(credential_id: UUID) -> CredentialImpactReport`; `reject_secret_material(value: Any, path: str = "$.") -> None`; and `redact_sensitive(value: Any) -> Any`.

- [ ] **Step 1: Write failing secret-safety tests**

Add tests named `test_safe_reference_never_stores_secret_value`, `test_secret_like_keys_are_rejected_recursively`, `test_private_key_and_token_patterns_are_rejected`, `test_audit_payload_redacts_sensitive_values`, `test_impact_lists_all_consuming_projects_and_resources`, and `test_backup_serialization_path_uses_same_redactor`. Include nested dictionaries, lists, common token prefixes, and PEM private-key markers.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python3 -m unittest tests.test_credentials -v`  
Expected: FAIL because credential interfaces do not exist.

- [ ] **Step 3: Implement reference-only storage, rejection, redaction, and impact queries**

Allow safe storage-system names and opaque reference labels but reject raw secret material before opening a mutation transaction. Audit serialization always passes through `redact_sensitive`; redaction keys are case-insensitive and include password, secret, token, private key, API key, refresh token, and recovery code variants.

- [ ] **Step 4: Run credential and domain tests**

Run: `python3 -m unittest tests.test_credentials tests.test_projects tests.test_assets -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit credential-reference safety**

```bash
git add src/projectos/credentials.py src/projectos/validation.py src/projectos/audit.py tests/test_credentials.py
git -c commit.gpgsign=false commit -m "feat: track safe credential references"
```

## Task 5: Discovery Candidates and Context OS Manifest Adapter

**Files:**
- Create: `src/projectos/discovery.py`
- Create: `src/projectos/contextos_adapter.py`
- Create: `tests/test_discovery.py`
- Create: `tests/fixtures/contextos-project.json`
- Create: `tests/fixtures/contextos-project-private.json`

**Interfaces:**
- Consumes: project/location/resource repositories and secret validation from Tasks 2–4.
- Produces: protocol `DiscoveryAdapter.scan() -> Iterable[DiscoveryFinding]`; `DiscoveryService.run(adapter: DiscoveryAdapter, source_run_id: str) -> DiscoveryRunResult`; `DiscoveryService.apply(finding_id: UUID, actor: str) -> ApplyResult`; `DiscoveryService.reject(finding_id: UUID, actor: str, reason: str) -> DiscoveryFinding`; and `ContextOSManifestAdapter(projects_dir: Path, machine_id: str)`.

- [ ] **Step 1: Write failing candidate and adapter tests**

Add tests named `test_contextos_adapter_maps_project_without_mutating_catalog`, `test_discovery_records_provenance_and_evidence`, `test_repeated_scan_is_idempotent`, `test_changed_manifest_creates_new_candidate_version`, `test_apply_candidate_uses_repository_transaction`, `test_reject_candidate_preserves_history`, `test_secret_material_in_candidate_is_rejected_before_persistence`, and `test_missing_or_malformed_manifest_is_a_non_destructive_finding`.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python3 -m unittest tests.test_discovery -v`  
Expected: FAIL because discovery interfaces do not exist.

- [ ] **Step 3: Implement candidate-only discovery and Context OS mapping**

Map current Context OS project manifests into candidates for project identity, `context_os_registered`, local location, types, and safe resources. Hash normalized finding content for idempotency. Discovery never calls canonical repositories until `apply`; malformed sources create findings with evidence and do not abort unrelated files.

- [ ] **Step 4: Run discovery and existing tests**

Run: `python3 -m unittest tests.test_discovery tests.test_projects tests.test_assets tests.test_credentials -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit discovery workflow**

```bash
git add src/projectos/discovery.py src/projectos/contextos_adapter.py tests/test_discovery.py tests/fixtures
git -c commit.gpgsign=false commit -m "feat: add provenance-based project discovery"
```

## Task 6: Verified Backup, Restore, and Health Doctor

**Files:**
- Create: `src/projectos/backup.py`
- Create: `src/projectos/health.py`
- Create: `tests/test_backup_health.py`

**Interfaces:**
- Consumes: `ProjectOSDatabase`, schema version, and redaction from Tasks 1 and 4.
- Produces: `BackupService.create(destination_dir: Path) -> BackupManifest`; `BackupService.verify(manifest_path: Path) -> BackupVerification`; `BackupService.restore(manifest_path: Path, target_db: Path, replace: bool = False) -> RestoreResult`; `ProjectOSDoctor.check() -> HealthReport`; and dataclasses with stable `to_dict()` output.

- [ ] **Step 1: Write failing backup and fail-closed tests**

Add tests named `test_backup_uses_sqlite_consistent_snapshot_and_sha256_manifest`, `test_verify_detects_changed_or_missing_snapshot`, `test_restore_refuses_existing_target_without_replace`, `test_restore_corrupt_snapshot_preserves_current_database`, `test_restore_newer_schema_fails_closed`, `test_doctor_detects_foreign_key_and_integrity_failures`, and `test_backup_manifest_contains_no_secret_material`.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python3 -m unittest tests.test_backup_health -v`  
Expected: FAIL because backup and health interfaces do not exist.

- [ ] **Step 3: Implement verified backup, staged restore, and doctor**

Use SQLite's backup API for a transactionally consistent snapshot. Write a JSON manifest containing schema version, timestamp, source identity, byte size, and SHA-256. Restore copies to a temporary sibling, verifies checksum, opens it read-only enough to run integrity/schema checks, then uses an atomic replacement only when `replace=True`; preserve the prior database as a timestamped rollback file.

- [ ] **Step 4: Run backup and database tests**

Run: `python3 -m unittest tests.test_backup_health tests.test_database -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit recovery and health operations**

```bash
git add src/projectos/backup.py src/projectos/health.py tests/test_backup_health.py
git -c commit.gpgsign=false commit -m "feat: add verified ProjectOS recovery"
```

## Task 7: JSON-First CLI Contract

**Files:**
- Create: `src/projectos/cli.py`
- Create: `tests/test_cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: all Phase 1 service interfaces.
- Produces: `main(argv: Sequence[str] | None = None) -> int`; commands `init`, `doctor`, `project create|get|list|update|archive`, `location upsert`, `resource upsert`, `deployment upsert`, `connection upsert|impact`, `credential create|link|impact`, `discover contextos|list|apply|reject`, and `backup create|verify|restore`.

- [ ] **Step 1: Write failing CLI contract tests**

Add tests named `test_success_is_single_json_document_and_exit_zero`, `test_validation_error_is_json_and_exit_two`, `test_version_conflict_is_json_and_exit_two`, `test_doctor_failure_is_json_and_exit_three`, `test_internal_error_is_redacted_json_and_exit_one`, `test_repeated_init_and_discovery_are_idempotent`, and `test_cli_never_emits_secret_input`. Assert every response contains `ok`, `command`, `data`, `errors`, and `meta.schema_version`.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python3 -m unittest tests.test_cli -v`  
Expected: FAIL because the CLI does not exist.

- [ ] **Step 3: Implement CLI parser, dispatch, serialization, and exit mapping**

Keep parsing separate from service dispatch. All paths and IDs enter services through typed commands. Write JSON only to stdout; diagnostics are represented in the JSON envelope. Unexpected exceptions return a redacted error identifier and may write a safe local traceback only when `PROJECTOS_DEBUG_LOG` points to an explicitly configured local file.

- [ ] **Step 4: Run CLI and full focused suite**

Run: `python3 -m unittest tests.test_cli tests.test_database tests.test_projects tests.test_assets tests.test_credentials tests.test_discovery tests.test_backup_health -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit stable CLI boundary**

```bash
git add src/projectos/cli.py tests/test_cli.py pyproject.toml
git -c commit.gpgsign=false commit -m "feat: expose ProjectOS local CLI"
```

## Task 8: Phase 1 Documentation and Release-Candidate Gate

**Files:**
- Create: `README.md`
- Create: `docs/PHASE1_OPERATIONS.md`
- Create: `docs/PHASE1_SCHEMA.md`
- Create: `docs/PHASE1_VERIFICATION.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: all completed Phase 1 commands and test names.
- Produces: operator setup/recovery instructions, schema reference, evidence checklist, and ignored local runtime patterns (`*.db`, `*.db-wal`, `*.db-shm`, backups, debug logs, and `.superpowers/`).

- [ ] **Step 1: Write documentation from verified commands**

Document installation, initialization, project registration, Context OS discovery, candidate review, credential-reference rules, impact queries, backup/restore, doctor output, data locations, exit codes, and the explicit Phase 1 prohibition on live Context OS/Google changes.

- [ ] **Step 2: Run the complete Phase 1 regression suite once**

Run: `python3 -m unittest discover -s tests -v`  
Expected: all tests PASS with no skips.

- [ ] **Step 3: Run packaging and static completion gates**

Run: `python3 -m compileall -q src tests`  
Expected: exit `0`.

Run: `python3 -m pip wheel . --no-deps --no-build-isolation -w build/wheel-check`  
Expected: one `projectos-0.1.0` wheel builds successfully without downloading build or runtime dependencies.

Run: `git diff --check`  
Expected: exit `0`.

- [ ] **Step 4: Exercise a clean-room smoke workflow**

Using a new temporary directory, run `projectos init`, create one PUBLIC GAS project, add development and production deployments, add a safe credential reference and usage, run Context OS fixture discovery, create and verify a backup, and run `projectos doctor`. Assert every command returns JSON with `ok: true`, the impact query names the project, the backup verifies, and doctor reports healthy.

- [ ] **Step 5: Reconcile release evidence**

Record exact commands and results in `docs/PHASE1_VERIFICATION.md`. Confirm the complete suite ran once for the release candidate, no Context OS or Google state changed, no secret-like fixture is persisted, and rollback artifacts from the smoke restore are recoverable.

- [ ] **Step 6: Commit the Phase 1 release candidate**

```bash
git add README.md docs/PHASE1_OPERATIONS.md docs/PHASE1_SCHEMA.md docs/PHASE1_VERIFICATION.md .gitignore
git -c commit.gpgsign=false commit -m "docs: complete ProjectOS phase 1 operations"
```

## Phase Boundary

Stop after Task 8. Report the Phase 1 release candidate, focused-test evidence, the single complete-suite execution, package build, smoke workflow, known limitations, commit list, and confirmation that live Context OS and Google state were untouched. Do not begin Phase 2 until Phase 1 is accepted and the Phase 2 Google-interface plan is written and reviewed.
