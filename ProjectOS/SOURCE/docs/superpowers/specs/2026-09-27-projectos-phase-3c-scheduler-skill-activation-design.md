# ProjectOS Phase 3C — Scheduler, Skill, and Runtime Activation Design

**Date:** 2026-09-27  
**Status:** Proposed for user review  
**Program:** ProjectOS  
**Parent specification:** `docs/superpowers/specs/2026-09-27-projectos-phase-3-cross-platform-contextos-adoption-design.md`  
**Prerequisite:** Phase 3B fixture transaction candidate at `1c74845`

## 1. Purpose

Phase 3C turns a verified but disabled Phase 3B ProjectOS definition into a conditionally discoverable ContextOS capability. It provides one configured synchronization entrypoint, deterministic native scheduler definitions for macOS and Windows, a portable ProjectOS skill contract, and a reversible runtime-activation transaction.

ContextOS remains the controller. SQLite remains the single source of truth. The Google Sheet remains a projection and change-request surface. Phase 3C does not authenticate a new Google account, create or alter a real Sheet, deploy GAS, migrate Looker, or activate a real ContextOS installation or native scheduler during local development.

## 2. Candidate boundary

Phase 3C delivers:

- a canonical portable ProjectOS skill with a manifest-bound capability allowlist;
- a read-only skill-discovery gate that fails closed;
- one configured `projectos runtime sync` command used by skill and scheduler triggers;
- bounded cross-process lock waiting and safe contention results;
- deterministic `launchd` and Windows Task Scheduler definitions;
- scheduler render, verify, install, enable, inspect, disable, and remove interfaces;
- a fixture scheduler runner that never calls a native scheduler;
- a fixture-only activation, rollback, and recovery transaction;
- structured CLI commands and local evidence for the complete lifecycle;
- macOS and simulated-Windows contract tests and an updated Windows handoff.

It does not deliver:

- a non-fixture activation CLI or force flag;
- execution of `launchctl`, `schtasks`, PowerShell, or Task Scheduler COM against the development host;
- live Google synchronization as part of activation proof;
- a two-hour job installed on any real account;
- real-host support claims. Those remain Phase 3D acceptance work.

## 3. Selected approach

Phase 3C uses fixture-first activation with injected scheduler execution. Native adapters own deterministic platform definitions and bounded native command construction. A runner protocol owns side effects. The Phase 3C CLI exposes only a receipt-bound fixture runner whose state is local to the fixture runtime. Native runners can be unit tested with recording executors but are not reachable from a state-changing CLI in this phase.

Render-only support was rejected because it cannot prove activation, disablement, or rollback ordering. Direct native activation was rejected because it would cross the separate live-activation authorization boundary and cannot provide real Windows evidence from the build Mac.

## 4. Portable skill contract

The bundle skill remains at the manifest-declared portable path, normally `skills/projectos/SKILL.md`, below the immutable installed extension version. No second copy or symlink is created under the ContextOS root. ContextOS discovers the skill through the enabled extension registry entry and versioned manifest.

The skill is canonical UTF-8 Markdown with deterministic YAML front matter containing only:

- `name: projectos`;
- a fixed non-secret description;
- `version`, equal to the manifest skill version;
- sorted manifest capability names.

The body instructs ContextOS to invoke adapter capabilities rather than embedding shell commands or resolved paths. It requires synchronization before state-dependent ProjectOS answers, reports bounded lock contention, preserves Owner/Admin/User and PUBLIC/PRIVATE authorization, and states that Looker capabilities remain unavailable.

`render_projectos_skill(manifest)` produces the only accepted bytes. `verify_projectos_skill(content, manifest)` requires exact byte equality with the renderer. Phase 3C activation therefore rejects a bundle whose skill is merely hash-valid but does not implement the canonical contract. Phase 3B may still stage such a bundle while its registry entry remains disabled.

The skill never contains an absolute path, machine name, username, email address, Google identifier, credential reference, token, scheduler identifier, or database location.

## 5. Skill discovery gate

`SkillDiscoveryService.resolve()` is read-only and returns either an immutable `DiscoveredSkill` or bounded diagnostic codes. It never repairs, enables, initializes, or migrates state.

Discovery succeeds only when all conditions pass in this order:

1. the target is an explicitly acknowledged receipt-bound fixture;
2. the registry contains exactly one canonical `projectos` entry with `enabled:true`;
3. the versioned manifest path stays below `projectos/versions/` and exists without symlinks;
4. manifest and payload hashes match the installed immutable inventory;
5. the version-directory bundle-hash prefix matches the registry bundle hash;
6. manifest, ContextOS, extension-contract, host, and ProjectOS versions are compatible;
7. the canonical skill bytes and capability allowlist match the manifest;
8. the local machine profile exists, matches the fixture and installation, and resolves outside ContextOS/shared roots;
9. the configured SQLite database exists and `projectos doctor` is healthy;
10. the runtime adapter contract and enabled scheduler state verify.

Failure returns codes such as `REGISTRY_DISABLED`, `INVENTORY_MISMATCH`, `SKILL_CONTRACT_INVALID`, `PROFILE_UNAVAILABLE`, `DATABASE_UNHEALTHY`, or `SCHEDULER_INACTIVE`. No state-changing capability is returned on partial success.

`DiscoveredSkill` exposes the skill ID, version, verified path, capabilities, and an adapter invocation descriptor. The descriptor names the `projectos runtime sync` entrypoint but obtains the local machine-profile path from the host adapter; the shared skill contains no resolved local path.

## 6. Common configured synchronization command

The platform-neutral command is:

```text
<python> -m projectos.cli --db <local-database> runtime sync \
  --machine-profile <local-profile> --trigger <scheduler|skill>
```

The machine profile supplies the canonical database, Google configuration, lock, log, runtime, and Python paths. The database argument is explicit and must exactly match the validated profile. The runtime command strictly reloads and validates the profile, then requires the profile path and every resolved path to remain local and mutually consistent. The Google configuration supplies the binding ID and protected Owner email; neither appears in the scheduler definition or skill.

The command opens the profile database but does not initialize or migrate it implicitly. It loads the existing Google configuration and requires both `google_enabled` and `google_write_enabled`. The real gateway remains fail-closed. Tests inject the fake gateway at the coordinator boundary; the production CLI has no fixture file or fake-gateway switch for this command.

Allowed triggers are exactly `scheduler` and `skill`. Scheduler runs use a zero-second lock wait. Skill runs use a bounded wait from zero through thirty seconds, defaulting to ten seconds. Waiting uses monotonic time and an injectable sleeper. On contention, the command returns a safe `LOCKED` result containing only the current run ID, trigger, start time, and whether the PID appears active. It never returns a lock path or command line.

Both triggers call the existing `GoogleSyncService` exactly once after acquiring the same profile lock. Checkpoint, retry, authorization, and projection behavior remain unchanged.

## 7. Scheduler model

`SchedulerDefinition` is an immutable value containing host family, scheduler kind, task ID, interval seconds, execution limit seconds, enabled state, canonical definition bytes, SHA-256, and the exact argument vector. Fixed values are:

- interval: 7,200 seconds;
- execution limit: 1,800 seconds;
- initial state: disabled;
- overlap policy: do not start a second instance;
- run context: enrolled interactive user;
- missed run: start when the user next becomes eligible;
- working directory, logs, Python, profile, database, and lock: resolved local profile values;
- secrets and credentials: prohibited.

`SchedulerAdapter` provides `render`, `verify`, `install`, `enable`, `inspect`, `disable`, and `remove`. Render and verify are pure/read-only. State-changing methods accept a `SchedulerRunner` and never invoke a shell.

### 7.1 macOS launchd

The macOS adapter renders canonical XML property-list bytes with:

- label `com.contextos.projectos.sync`;
- exact `ProgramArguments` for the common runtime command;
- `StartInterval` 7,200;
- `RunAtLoad` false;
- `KeepAlive` false;
- `ProcessType` `Background`;
- local working, stdout, and stderr paths;
- disabled staged state.

Native lifecycle commands use per-user `launchctl` domains and argument arrays. No command uses `shell=True`, a shell wrapper, `sudo`, or a system-wide daemon path.

### 7.2 Windows Task Scheduler

The Windows adapter renders canonical UTF-8 Task Scheduler XML with:

- task path `ContextOS\ProjectOS\Sync`;
- an interactive-token principal and no stored password;
- a two-hour calendar repetition trigger;
- `StartWhenAvailable` true;
- `MultipleInstancesPolicy` `IgnoreNew`;
- 30-minute execution limit;
- exact executable, arguments, and local working directory;
- disabled staged state.

Native lifecycle operations use fixed argument arrays or a typed Windows scheduler backend. They do not require Developer Mode, symlinks, PowerShell script wrappers, embedded credentials, or account passwords.

### 7.3 Fixture runner

`FixtureSchedulerRunner` persists canonical scheduler state only below `<runtime-root>/adoption/scheduler-fixtures/`. It verifies definition hashes and legal state transitions and simulates install, enable, inspect, disable, and remove. It rejects any non-fixture target or native executable request. This runner is the only scheduler runner reachable from the Phase 3C fixture CLI.

## 8. Runtime activation transaction

Runtime activation is a second local transaction that references a completed Phase 3B definition transaction. Its journal never alters or replaces the Phase 3B journal.

States are:

```text
DISCOVERED -> PREFLIGHTED -> SCHEDULER_STAGED -> RUNTIME_VERIFIED
-> SCHEDULER_ENABLED -> SKILL_ENABLED -> PROVED
```

Any nonterminal state may transition to `FAILED`; recovery ends at `ROLLED_BACK`. All journals, scheduler definitions, receipts, and proof results stay below the local adoption store.

The ordered activation is:

1. **Discover:** bind the fixture, disabled registry entry, installed version, machine profile, and prior definition transaction.
2. **Preflight:** verify the canonical skill, immutable inventory, compatible profile, pre-existing current database schema, Google configuration shape, scheduler adapter, local writable paths, and absence of secrets.
3. **Stage scheduler:** render and verify the disabled native definition; persist its canonical bytes and hash locally; install it through the fixture runner in disabled state.
4. **Verify runtime:** run doctor, verify the configured-sync command contract with injected fake dependencies, and confirm no Google call or database migration occurred during discovery.
5. **Enable scheduler:** enable through the fixture runner and verify active state.
6. **Enable skill:** atomically replace only the ProjectOS registry entry with an otherwise identical `enabled:true` entry.
7. **Prove:** resolve the skill through the full discovery gate and invoke the common sync coordinator with a fake gateway for both trigger values.

The scheduler becomes active before skill discovery. If skill enablement or proof fails, rollback first atomically restores the exact disabled registry bytes, then disables and removes the scheduler fixture state. Thus no discoverable skill remains when runtime activation is incomplete.

Activation never initializes or migrates a database. A fixture acceptance setup may create and seed its own isolated database before activation. A production database migration remains a separately reviewed operation.

## 9. Deactivation, upgrade, rollback, and uninstall integration

Phase 3B rollback or uninstall must not operate on an enabled registry entry. Phase 3C adds a precondition requiring runtime deactivation first.

Deactivation order is:

1. atomically restore an `enabled:false` ProjectOS registry entry;
2. prove skill discovery now fails with `REGISTRY_DISABLED`;
3. disable the scheduler and verify inactive state;
4. remove the scheduler definition;
5. retain the activation journal, proofs, database, configuration, logs, and Phase 3B recovery artifacts.

An upgrade keeps the previous immutable version until the new definition and runtime activation prove healthy. If activation of the new version fails, exact disabled registry bytes and scheduler state are restored before the Phase 3B definition rollback runs.

Permanent purge remains out of scope.

## 10. CLI surface and exit behavior

Phase 3C adds database-free/local-control fixture commands:

```text
projectos adoption fixture scheduler render ...
projectos adoption fixture activate DEFINITION_TRANSACTION_ID ...
projectos adoption fixture deactivate ACTIVATION_TRANSACTION_ID ...
projectos adoption fixture activation-recover ACTIVATION_TRANSACTION_ID ...
projectos adoption fixture skill inspect ...
```

Every state-changing command retains the existing marker, local receipt, `FIXTURE_ONLY` acknowledgement, explicit ContextOS root, and explicit machine-profile requirements. There is no non-fixture alias, live target, native runner option, scheduler force option, or registry-enable shortcut.

`projectos runtime sync` is not database-free: it opens only the database declared in the validated machine profile. Validation and compatibility errors exit `2`; operational or health failures exit `3`; unexpected failures remain redacted exit `1`. Every invocation prints one JSON envelope.

## 11. Security and privacy

- Registry enablement changes only the `enabled` value of the verified ProjectOS entry.
- Skill and scheduler definitions are scanned for build host, target host, home path, username, email, external identifier, token, password, private-key, and credential material.
- Scheduler argument vectors are constructed as arrays and XML/plist values are escaped by standard-library encoders.
- Runtime configuration paths must be local and outside ContextOS/shared roots.
- Lock waiting is bounded and cannot be configured above thirty seconds.
- Discovery and status commands perform no Google operations.
- Activation proof uses a fake gateway and an isolated fixture database.
- Logs and JSON envelopes contain bounded codes and safe identifiers only.
- Windows support requires no symlink privilege and stores no account password.

## 12. Verification strategy

### 12.1 Platform-independent candidate gate

Automated tests must prove:

- canonical skill render/verify and manifest capability binding;
- rejection of modified skill text, extra capability claims, paths, secrets, and host identifiers;
- fail-closed discovery at every ordered condition;
- one common configured-sync path for skill and scheduler triggers;
- zero/ten/thirty-second lock policy, injectable time, safe contention metadata, and no duplicate sync run;
- deterministic plist and Task Scheduler XML with exact two-hour, disabled, non-overlap, local-path, and no-secret properties;
- no shell invocation, symlink requirement, password, or platform branch outside adapters;
- fixture scheduler lifecycle and invalid-transition rejection;
- activation failure and recovery at every boundary;
- registry disabled before scheduler teardown during deactivation;
- Phase 3B rollback/uninstall refusal while enabled;
- extracted-wheel fixture activation/deactivation and identifier scans;
- no live native scheduler, Google, GAS, Looker, shared-root, or production SQLite mutation.

### 12.2 macOS evidence

Phase 3C local evidence renders and parses the launchd definition and exercises the fixture runner only. Real per-user `launchctl` installation, two-hour execution, contention, disablement, and removal remain Phase 3D clean-account acceptance.

### 12.3 Windows evidence

macOS tests parse and validate the Windows XML and simulate scheduler transitions without symlinks. The Windows handoff must repeat fixture activation under a standard account. Real Task Scheduler installation, two-hour execution, contention, disablement, and removal remain Phase 3D and cannot be inferred from simulation.

## 13. Implementation sequence

Phase 3C is implemented as bounded candidates:

1. canonical skill contract and installed-inventory verifier;
2. configured runtime-sync command and bounded lock contention;
3. scheduler model plus macOS and Windows render/verify adapters;
4. fixture scheduler runner and local scheduler persistence;
5. fixture runtime-activation, discovery, deactivation, rollback, and recovery;
6. CLI, deterministic packaging, operations, Windows handoff, and candidate evidence.

Each candidate uses test-driven development and focused tests. The complete ProjectOS regression suite remains deferred until the full Phase 3 release candidate. No Phase 3D native activation begins automatically.
