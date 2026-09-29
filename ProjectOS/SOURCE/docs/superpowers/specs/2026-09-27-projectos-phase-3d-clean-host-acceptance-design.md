# ProjectOS Phase 3D — Clean-Host Acceptance and Reconciliation Design

**Date:** 2026-09-27  
**Status:** Proposed for user review  
**Program:** ProjectOS  
**Parent specification:** `docs/superpowers/specs/2026-09-27-projectos-phase-3-cross-platform-contextos-adoption-design.md`  
**Prerequisite:** Phase 3C fixture-activation candidate at `bf70de8`

## 1. Purpose

Phase 3D converts the portable Phase 3C candidate into a clean-host acceptance system. It builds native scheduler runners, an acceptance-only synchronization probe, deterministic handoff artifacts, sanitized evidence collection, and cross-platform evidence reconciliation.

Phase 3D is split into two authorization boundaries:

- **3D-A — local acceptance build:** implement and test all acceptance tooling without installing a native scheduler or changing a live ContextOS installation.
- **3D-B — authorized host execution:** run the acceptance package first under a clean standard macOS account and later on a real standard-user Windows host. Each host execution requires separate user authorization.

Completing 3D-A does not declare either platform verified. Completing one 3D-B host run verifies only that platform. Cross-platform verification requires accepted evidence from both.

## 2. Desired outcome

ProjectOS can produce one deterministic release-acceptance package that a clean macOS or Windows operator can inspect and run without access to the build workspace. The package proves native per-user scheduler installation, safe execution, two-hour configuration, non-overlap, contention behavior, disablement, removal, recovery, and artifact cleanup against an isolated fixture.

The controlling build can validate returned evidence without trusting narrative claims or raw machine state. It reports one of these exact support states:

```text
SIMULATED
MACOS_VERIFIED
WINDOWS_VERIFIED
CROSS_PLATFORM_VERIFIED
```

No state advances when evidence is incomplete, mismatched, unsafe, or from a different release artifact.

## 3. Non-goals

Phase 3D does not:

- enroll an existing or production ContextOS installation;
- initialize, migrate, copy, or inspect a production ProjectOS database;
- authenticate Google or contact a real Sheet, Drive file, GAS deployment, or credential provider;
- migrate or inspect the Looker Git tracker;
- create system-wide daemons or tasks;
- require `sudo`, administrator elevation, Developer Mode, symlinks, stored account passwords, or shell wrappers;
- turn the production `projectos runtime sync` command into a fake-gateway command;
- automatically execute 3D-B after the 3D-A build;
- claim Windows support from macOS simulation.

## 4. Selected architecture

Phase 3D uses an acceptance-only execution path beside, not inside, the production runtime path.

The native scheduler definition uses the same platform adapter, argument-array structure, profile paths, lock path, database contract, interval, execution limit, working directory, and log locations as production. Its profile entrypoint is the isolated `projectos.acceptance_probe` module instead of `projectos.cli`. The probe calls `RuntimeSyncCoordinator` with `FakeGoogleGateway` only after validating a clean-host acceptance receipt.

Production `runtime sync` remains unchanged and continues to construct only the guarded real Google gateway. There is no `--gateway fake`, fixture file, environment-variable bypass, or acceptance flag on the production command.

The acceptance scheduler uses a dedicated task namespace so it cannot replace a production task:

- macOS: `com.contextos.projectos.acceptance.sync`;
- Windows: `ContextOS\ProjectOS\Acceptance\Sync`.

The evidence reconciler structurally compares the acceptance and production definitions. The only permitted semantic differences are the dedicated acceptance task identifier and the entrypoint module. Scheduling, arguments after the module, paths, timing, non-overlap policy, run context, and execution limits must match.

## 5. Trust and authorization model

### 5.1 3D-A local build

All 3D-A commands are pure, read-only, or fixture-local. Native process execution is tested only through recording executors. The normal ProjectOS CLI exposes package build, package verification, evidence verification, and reconciliation, but no native install or enable command.

### 5.2 3D-B host execution

The state-changing host runner is available only through a separate module:

```text
python -m projectos.acceptance_host run ...
```

It requires all of:

1. exact acknowledgement `CLEAN_HOST_NATIVE_ACCEPTANCE`;
2. a newly issued acceptance root and same-host receipt;
3. a newly issued Phase 3 fixture root and matching local receipt;
4. an isolated runtime outside ContextOS and shared roots;
5. an acceptance manifest matching the installed wheel SHA-256 and source revision;
6. the current host family matching the manifest;
7. a non-elevated standard-user session;
8. absence of the dedicated acceptance task before installation;
9. a pre-existing disposable current-schema database and invented local configuration;
10. an explicit evidence destination below the acceptance runtime.

The host runner refuses root, `sudo`, an elevated Windows token, a live ContextOS root, a production scheduler identifier, a database outside the acceptance runtime, a symlinked path, or an existing task it does not own. There is no force or overwrite option.

## 6. Acceptance package

`AcceptancePackageBuilder` produces a deterministic ZIP containing:

```text
acceptance-manifest.json
projectos-0.1.0-py3-none-any.whl
macos/run-projectos-acceptance.sh
windows/Run-ProjectOSAcceptance.ps1
docs/PHASE3D_HOST_OPERATIONS.md
SHA256SUMS.txt
```

`acceptance-manifest.json` contains only:

- schema version;
- ProjectOS version;
- exact source revision;
- wheel filename, size, member count, and SHA-256;
- supported host families;
- supported Python and ContextOS contract ranges;
- acceptance task identifiers;
- required case identifiers;
- package creation timestamp supplied explicitly by the release build;
- hashes for every package member.

The package contains no absolute path, username, hostname, machine identifier, email, spreadsheet identifier, credential reference, token, password, key, native receipt, or database.

The builder rejects symlinks, executable content outside the two reviewed operator scripts, unexpected archive members, noncanonical JSON, path traversal, duplicate case-insensitive names, secret-like content, and a wheel hash that differs from the manifest.

## 7. Acceptance profile and probe

`AcceptanceProfile` binds:

- the regular `MachineProfile`;
- the acceptance task identifier;
- acceptance root and receipt identifier;
- definition transaction and activation identifiers;
- release and wheel hashes;
- required test cases;
- evidence spool location;
- maximum probe duration.

It is canonical local JSON stored below `<runtime>/acceptance/`. It is never placed in the portable package or returned evidence.

`projectos.acceptance_probe` accepts the same `--db`, `runtime sync`, `--machine-profile`, and `--trigger scheduler` arguments produced by `runtime_sync_argv`. It then:

1. validates the acceptance receipt and profile;
2. verifies that the database and configuration remain below the isolated runtime;
3. refuses any non-acceptance task identifier or production entrypoint;
4. constructs the canonical fake gateway fixture in memory;
5. calls `RuntimeSyncCoordinator` with the same database, configuration, and lock;
6. appends one canonical bounded probe event to the local evidence spool;
7. returns success only for `COMPLETE` or the test case's expected `LOCKED` result.

The probe has no network client, credential factory, arbitrary fixture input, Google identifier output, or production invocation alias.

For native non-overlap testing, the probe supports a receipt-bound barrier case. The first invocation records `STARTED` and waits for a bounded local release marker. The host runner requests a second native trigger while the first is active. Exactly one probe invocation may reach the barrier. The barrier times out safely, contains no command line or process details, and is unavailable outside acceptance mode.

## 8. Native scheduler runners

`MacOSNativeSchedulerRunner` and `WindowsNativeSchedulerRunner` implement the existing `SchedulerRunner` protocol through injected process executors.

Both runners:

- accept only canonical definitions produced by the matching adapter;
- accept only the dedicated acceptance task identifier;
- use fixed argument arrays with `shell=False` semantics;
- persist native definition files only below the acceptance runtime;
- reject environment overrides, shell metacharacter interpretation, elevation, and unmanaged existing tasks;
- return bounded `SchedulerInspection` values without native command output;
- record raw native output only in local excluded diagnostics when a failure requires it;
- make disable and remove idempotent for a runner-owned task;
- never remove a task whose installed definition hash differs from the journal.

### 8.1 macOS

The macOS runner uses the per-user `gui/<uid>` launchd domain. It validates plist bytes before invoking fixed `launchctl` argument arrays. It never writes `/Library/LaunchDaemons`, `/Library/LaunchAgents`, or another user's home. It proves bootstrap, disabled staging, enablement, immediate kickstart, inspection, disablement, bootout, and absence.

### 8.2 Windows

The Windows runner uses fixed `schtasks.exe` argument arrays against `ContextOS\ProjectOS\Acceptance\Sync`. It imports only the verified XML stored below the acceptance runtime, uses `InteractiveToken` and `LeastPrivilege`, stores no password, and refuses elevation. It proves create-disabled, enable, immediate run, query, disable, delete, and absence without PowerShell task-registration wrappers or COM automation.

Native command construction is unit tested on both platforms with recording executors. Actual command execution happens only during separately authorized 3D-B host runs.

## 9. Host acceptance transaction

The host runner persists a local canonical journal with these states:

```text
DISCOVERED -> PREFLIGHTED -> DEFINITION_ADOPTED -> RUNTIME_ACTIVATED
-> NATIVE_STAGED -> NATIVE_ENABLED -> IMMEDIATE_PROVED
-> NON_OVERLAP_PROVED -> SCHEDULE_PROVED -> DEACTIVATED
-> NATIVE_REMOVED -> DEFINITION_ROLLED_BACK -> EVIDENCE_SEALED
```

Any nonterminal state may transition to `FAILED`. Recovery works backward from recorded ownership:

1. restore the disabled registry entry if skill discovery was enabled;
2. release an acceptance barrier if present;
3. disable the owned native task;
4. remove it only when its definition hash matches;
5. deactivate the Phase 3C runtime transaction;
6. roll back the Phase 3B definition transaction;
7. retain the database, configuration, journals, raw diagnostics, and evidence spool locally.

Recovery is idempotent. A native definition mismatch, unexpected pre-existing task, registry ownership mismatch, or immutable inventory mismatch stops recovery and requires operator review. The runner never deletes uncertain state.

## 10. Required acceptance cases

Every host record must contain all applicable case identifiers:

```text
package_integrity
standard_user_non_elevated
fixture_authority
local_path_separation
definition_structural_equivalence
native_install_disabled
native_enable
immediate_trigger
common_lock_contention
native_non_overlap
two_hour_configuration
eligible_resume_configuration
skill_discovery
deactivation_order
native_disable_remove
definition_rollback
retained_database_health
identifier_secret_symlink_scan
```

`eligible_resume_configuration` verifies the platform's canonical configuration and inspected native state. It does not require keeping the acceptance task installed for two hours or across an uncontrolled restart. A later extended soak may supplement this record but cannot replace the required deterministic cases.

The immediate and contention cases use only the acceptance probe and fake gateway. No real Google request is permitted.

## 11. Evidence format

Each host produces `projectos-host-acceptance-v1.json` plus `SHA256SUMS.txt`. The canonical JSON contains:

- release, source, wheel, manifest, and definition hashes;
- host family, OS version, architecture, and Python version;
- a random acceptance run ID;
- standard-user and non-elevated booleans;
- case ID, status, bounded code, start/end timestamps, and safe measurements;
- scheduler state transitions and definition hash;
- activation/deactivation and definition rollback terminal states;
- cleanup result;
- relative hashes of safe evidence attachments;
- a list of excluded local-only artifacts.

It excludes absolute paths, usernames, account identifiers, machine names, emails, database rows, binding or credential UUIDs, spreadsheet IDs, commands, native stdout/stderr, environment variables, process listings, and task history containing user data.

The evidence builder scans canonical output and every attachment for private identifiers, secret patterns, symlink metadata, unexpected binaries, and absolute path shapes for both POSIX and Windows. Raw logs and the disposable database remain local and are never included.

Evidence is integrity-bound by SHA-256, not represented as cryptographically signed. The operator communicates the archive hash separately. Reconciliation reports integrity and release consistency; it does not claim identity attestation.

## 12. Evidence verification and reconciliation

`AcceptanceEvidenceVerifier.verify()` is read-only. It rejects:

- a schema, release, source, wheel, package, or definition mismatch;
- missing, duplicate, unknown, skipped, or failed required cases;
- a host-family mismatch;
- elevated execution;
- unsafe or noncanonical content;
- absent cleanup or rollback proof;
- attachment hash or archive inventory mismatch;
- a task remaining installed or enabled;
- evidence from the simulated fixture runner presented as native evidence.

`AcceptanceReconciler.reconcile()` consumes zero, one, or two verified host records for the same release:

- no verified records -> `SIMULATED`;
- verified macOS only -> `MACOS_VERIFIED`;
- verified Windows only -> `WINDOWS_VERIFIED`;
- verified macOS and Windows -> `CROSS_PLATFORM_VERIFIED`.

It writes a deterministic reconciliation report but never modifies source, release metadata, ContextOS, a scheduler, or a database. Support status becomes a release claim only after the user reviews this report.

## 13. CLI surface

The ordinary CLI adds only local build and verification commands:

```text
projectos acceptance package build ...
projectos acceptance package verify ...
projectos acceptance evidence verify ...
projectos acceptance reconcile ...
```

These commands never execute a native scheduler.

The separate host module exposes:

```text
python -m projectos.acceptance_host preflight ...
python -m projectos.acceptance_host run ...
python -m projectos.acceptance_host recover ACCEPTANCE_RUN_ID ...
```

`run` and `recover` require the same acceptance root, receipts, explicit acknowledgement, fixture root, machine profile, package manifest, and evidence directory. There is no ordinary-CLI alias, production task identifier, native runner selector, live ContextOS option, force flag, or purge command.

All commands print one JSON envelope. Validation exits `2`, an incomplete acceptance or health failure exits `3`, and unexpected failures exit `1` with redacted output.

## 14. macOS 3D-B workflow

After separate authorization, a clean standard macOS account will:

1. verify the independently communicated package hash;
2. install the wheel into a new virtual environment without an index;
3. create a new isolated ContextOS fixture and acceptance runtime;
4. prepare an invented local database and configuration;
5. run host preflight and inspect the exact proposed native actions;
6. run the acceptance transaction;
7. verify the dedicated launchd task is absent afterward;
8. scan and seal safe evidence;
9. retain the disposable runtime locally until controller reconciliation;
10. return only the evidence archive and separately communicated hash.

The run is non-elevated and per-user. It never uses the current development checkout or an existing ContextOS root.

## 15. Windows 3D-B workflow

The Windows package provides an equivalent standard-user PowerShell wrapper. It requires no Developer Mode, symlink privilege, administrator token, network share for runtime state, or stored task password. It tests drive-letter and UNC ContextOS fixture discovery while keeping runtime under `%LOCALAPPDATA%` or another explicit local path.

The operator returns only sanitized evidence. The controlling build does not mark Windows verified until `AcceptanceEvidenceVerifier` accepts the archive and the user reviews the reconciliation result.

## 16. Security and privacy

- The acceptance probe is the only fake-gateway native entrypoint and cannot be invoked as production sync.
- Native runners are restricted to dedicated acceptance task identifiers.
- No shell, elevation, system-wide scheduler location, stored password, or executable script interpolation is allowed.
- Fixture, acceptance, runtime, and evidence roots must be mutually compatible and locally contained.
- Existing native tasks are never overwritten.
- Definition hashes bind every state-changing native action and recovery step.
- Evidence is allowlisted and regenerated from bounded events rather than copied from raw logs.
- The Owner/Admin/User and PUBLIC/PRIVATE rules remain unchanged because acceptance uses the existing synchronization and authorization services.
- No live Google, GAS, Looker, shared-root, or production SQLite state is in scope.

## 17. Verification strategy

### 17.1 Phase 3D-A automated gates

Automated tests must prove:

- deterministic acceptance package bytes, member inventory, and hashes;
- exact wheel/source binding and rejection of altered packages;
- acceptance profile and receipt locality, ownership, canonical bytes, and secret rejection;
- acceptance probe refusal outside acceptance mode and both `COMPLETE` and `LOCKED` fake-gateway outcomes;
- structural equivalence between acceptance and production scheduler definitions;
- macOS and Windows native argument arrays without shell execution;
- elevated-session, wrong-host, production-task, existing-task, symlink, and definition-hash rejection;
- every host transaction boundary can recover idempotently with registry disablement before scheduler teardown;
- sanitized evidence excludes paths, identities, external identifiers, secrets, commands, and raw logs;
- evidence verifier rejects every missing or mismatched case;
- reconciler state transitions require matching verified host evidence;
- extracted-wheel acceptance-package build, probe, evidence verification, and simulated native lifecycle;
- all prior ProjectOS behavior through the complete regression suite once at the Phase 3 release-candidate boundary.

No automated 3D-A test calls `launchctl`, `schtasks`, Google, GAS, Looker, or a live ContextOS root.

### 17.2 Phase 3D-B gates

The macOS and Windows records must independently pass all cases in Section 10. The controller verifies the returned archive and hash, compares the release identifiers, and produces the reconciliation report. A platform remains unverified until its real-host record is accepted.

## 18. Implementation sequence

Phase 3D-A is implemented as bounded candidates:

1. acceptance manifest, receipt, profile, and deterministic package;
2. acceptance-only probe and structural scheduler equivalence;
3. injected native runners for macOS and Windows;
4. host acceptance journal, transaction, and recovery;
5. safe evidence model, scanner, verifier, and reconciler;
6. ordinary CLI, separate host module, extracted-wheel tests, and operator documents;
7. complete Phase 3 regression suite and deterministic release-candidate evidence.

After 3D-A is complete, work stops. The macOS 3D-B run requires explicit authorization. The Windows 3D-B run requires a separate explicit authorization on the target host. Neither begins automatically.

## 19. Completion criteria

Phase 3D-A is complete when:

- every local task is committed;
- focused tests and the complete ProjectOS regression suite pass;
- the wheel and acceptance package are deterministic and identifier-clean;
- recording-executor tests prove both native command lifecycles without executing them;
- extracted-wheel acceptance tooling passes;
- operations, recovery, evidence, macOS, and Windows handoff documents are complete;
- no native scheduler or external service was invoked;
- the release status remains `SIMULATED` pending 3D-B.

Full Phase 3 completes only after both separately authorized host records verify and the user accepts the `CROSS_PLATFORM_VERIFIED` reconciliation report.
