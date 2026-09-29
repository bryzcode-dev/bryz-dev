# ProjectOS Phase 3 — Cross-Platform ContextOS Adoption Design

**Date:** 2026-09-27  
**Status:** Approved conversational design; written specification awaiting user review  
**Program:** ProjectOS  
**Supported host families:** macOS and Windows  
**Controlling platform:** ContextOS

## 1. Purpose

Phase 3 turns ProjectOS from a separately verified application into an optional, distributable ContextOS enhancement. The same ProjectOS release must be installable by the Owner on independent macOS and Windows ContextOS installations without embedding the developer's machine name, username, home directory, NAS path, drive letter, Google identifiers, or credentials.

ContextOS remains the controller. ProjectOS remains separately buildable and owns its SQLite database, synchronization engine, domain rules, and Google interface. Adoption gives ContextOS a versioned ProjectOS extension manifest, a conditionally available skill, health and maintenance entrypoints, and a native two-hour scheduler.

The machine used to build or verify a release is not part of the product contract. Verification-host details are evidence metadata only; they are never required hosts or encoded installation targets.

## 2. Phase boundary

Phase 3 delivers:

- a platform-neutral extension and adoption contract;
- macOS and Windows host adapters;
- runtime discovery and generated installation profiles;
- staged adoption, verification, activation, rollback, upgrade, and uninstall commands;
- a conditionally installed ContextOS skill;
- native two-hour scheduler definitions for both operating systems;
- immediate synchronization when the skill is invoked;
- portable packaging and clean-install documentation;
- automated platform-contract tests;
- a Windows implementation and troubleshooting handoff for execution on a Windows machine;
- real macOS and Windows acceptance gates before the corresponding platform is declared supported.

Phase 3 does not authenticate Google, create or modify a live Sheet, deploy GAS, migrate Looker, load a scheduler, or alter a live ContextOS installation merely because the code or staged bundle passes local tests. Each live activation remains a separate, explicit transaction against resolved installation identifiers.

## 3. Controlling decisions

### 3.1 Product support

Windows and macOS are first-class product requirements. Neither is implemented as an afterthought or by substituting one platform's path and scheduler conventions into the other.

The shared Python domain package remains the same on both platforms. Platform variation is isolated behind typed host interfaces. Business services, SQLite migrations, authorization, synchronization, extension-manifest semantics, structured CLI results, and skill command semantics cannot branch on the host platform.

### 3.2 System of record

The local `projectos.db` remains the single source of truth. Each adopted installation has one configured canonical database. The Google Sheet remains a projection and change-request surface.

No database, WAL/SHM sidecar, lock, credential, token, cache, queue, or transient log may be placed in a shared ContextOS tree or network share. Shared definitions may contain only portable code, schemas, templates, manifests, and non-secret configuration references.

### 3.3 Distribution boundary

ProjectOS is distributed as a versioned Python package and a deterministic extension bundle. The bundle contains no host-specific resolved path. Onboarding generates the machine profile, scheduler definition, and local configuration for the target host.

The installer does not vendor or silently fork ContextOS. A small versioned extension contract is the only integration surface. If the installed ContextOS version does not implement a compatible contract, preflight stops without modifying the installation.

### 3.4 Existing ContextOS compatibility

The currently inspected ContextOS V3 source contains macOS-specific defaults and installation-specific path checks. Phase 3 must not copy those assumptions into ProjectOS. The required ContextOS compatibility work is limited to the smallest general extension contract and host-path abstractions necessary for ProjectOS adoption.

Those ContextOS changes are staged and verified in a copied installation. They do not authorize modification of a live ContextOS root. ProjectOS must continue to fail closed when the compatibility contract is absent or incompatible.

## 4. Component architecture

### 4.1 Platform-neutral core

The existing ProjectOS package remains responsible for:

- SQLite schema and migrations;
- project, location, resource, deployment, connection, and credential-reference services;
- Owner/Admin/User authorization and PUBLIC/PRIVATE visibility;
- Google projection, request reconciliation, and conflict handling;
- structured JSON CLI envelopes;
- backup, restore, doctor, diagnostics, and audit;
- versioned adapter commands consumed by ContextOS.

### 4.2 Host services interface

Platform-specific behavior is available only through these interfaces:

- `PlatformPaths` — resolves local data, configuration, cache, log, and temporary locations;
- `ContextOSLocator` — discovers and validates a ContextOS installation and machine profile;
- `SchedulerAdapter` — renders, inspects, installs, disables, and removes a native scheduled task;
- `ProcessLock` — provides an exclusive cross-process synchronization lock;
- `AtomicInstaller` — stages and atomically adopts versioned definitions without requiring symlink privileges;
- `HostIdentity` — produces or loads a non-secret installation ID and normalized platform metadata;
- `PathPolicy` — determines local versus shared storage and compares paths using host-appropriate semantics.

The remainder of ProjectOS depends on these protocols rather than `sys.platform`, `os.name`, macOS directories, Windows environment variables, or shell commands directly.

### 4.3 macOS adapter

The macOS implementation uses:

- `$HOME/Library/Application Support/ProjectOS` as the default local runtime root;
- `$HOME/Library/Logs/ProjectOS` for logs when a separate log path is needed;
- `launchd` with a generated per-user property list;
- POSIX path and ownership checks;
- a macOS-compatible advisory file lock;
- atomic same-volume directory replacement for managed definition activation.

An explicit `PROJECTOS_HOME`, `PROJECTOS_DB`, CLI path, or installation profile overrides defaults. Generated property lists contain fully resolved target-host paths, but templates and packages do not.

### 4.4 Windows adapter

The Windows implementation uses:

- `%LOCALAPPDATA%\ProjectOS` as the default local runtime root;
- a per-user Windows Task Scheduler task;
- Windows path, drive, UNC, and case-insensitive comparison rules;
- a Windows-compatible advisory file lock;
- atomic same-volume directory replacement for managed definition activation;
- managed directory copies rather than any requirement for symlink permission or Developer Mode.

If `%LOCALAPPDATA%` is unavailable or invalid, onboarding fails with a diagnostic unless the Owner supplies an explicit local runtime path. It does not silently place SQLite or credentials beside shared definitions.

Scheduler activation uses a generated task definition and the native Task Scheduler interface. The secure default runs only while the enrolled user is logged on, stores no password, starts a missed run when the user next logs on, and invokes the exact Python environment recorded during onboarding. An unattended service-account mode is a separate, explicit configuration that relies on Windows credential handling; ProjectOS never stores that account's password.

## 5. Portable path and host rules

Configuration resolution follows this order:

1. explicit CLI argument;
2. ProjectOS environment variable;
3. adopted machine profile;
4. platform default.

The resulting profile records resolved local values for one installation. It is not copied into a shared skill or distributable package.

Every machine profile includes:

- profile schema version;
- installation ID and machine ID;
- operating-system family;
- ProjectOS version;
- compatible ContextOS version and extension-contract version;
- resolved ContextOS root and extension registry;
- resolved ProjectOS runtime, database, configuration, lock, and log paths;
- Python executable and ProjectOS entrypoint;
- scheduler kind and task identifier;
- adoption state and last verified manifest hash.

Paths on Windows are normalized without losing UNC semantics and compared case-insensitively where appropriate. Paths on macOS are normalized through the host filesystem. String-prefix checks are prohibited for determining whether a runtime is inside a shared root; the path policy performs component-aware containment checks.

## 6. ContextOS extension contract

### 6.1 Extension registry

ContextOS exposes a versioned extension registry within its managed definitions. ProjectOS receives a namespaced entry, `projectos`, and must not modify unrelated ContextOS files or another extension's entry.

The registry entry points to a versioned ProjectOS extension manifest. Registry and skill changes are adopted atomically as one definition transaction. Runtime state is referenced through the local machine profile and is never copied into the registry.

### 6.2 Extension manifest

The manifest declares:

- extension ID, product version, and manifest schema version;
- supported operating-system families;
- compatible ContextOS and extension-contract versions;
- adapter and CLI entrypoints;
- skill identifier, version, path, and capability allowlist;
- database schema compatibility and migration status;
- health, maintenance, upgrade, rollback, and uninstall commands;
- scheduler requirement and common sync command;
- safe optional Sheet and GAS reference identifiers;
- machine-profile reference;
- bundle file inventory and hashes;
- adoption state and timestamps.

It never includes secrets or absolute paths copied from the build machine.

### 6.3 Skill lifecycle

The `projectos` skill is discoverable only when all of these are true:

- the extension registry entry is enabled;
- the manifest and bundle hashes verify;
- ContextOS and ProjectOS versions are compatible;
- the local machine profile resolves;
- `projectos doctor` reports a usable database and runtime;
- the adapter contract check passes.

A failed condition produces a bounded diagnostic and exposes no state-changing ProjectOS capability. Disabling or rolling back the extension removes skill discovery before changing runtime state.

The skill invokes synchronization before answering ProjectOS questions or executing ProjectOS commands. Both skill-triggered and scheduled synchronization call the same structured CLI entrypoint and use the same exclusive lock. If another run owns the lock, the skill reports that run and waits only for a configured bounded interval.

The skill may synchronize, report status, register or inspect projects, locate assets, list deployments, trace connections and safe credential usage, and report conflicts or health. Looker capabilities remain unavailable until the later Looker phase is adopted.

## 7. Scheduler contract

The common scheduled command is a platform-neutral ProjectOS CLI invocation with explicit machine-profile and database references. It is idempotent and safe to retry.

The schedule interval is two hours. The scheduler definition also specifies:

- a stable namespaced task identifier;
- the enrolled user context;
- the exact Python executable and ProjectOS entrypoint;
- local working, lock, and log paths;
- a non-overlap policy;
- bounded execution time;
- no embedded secret values;
- a disabled-by-default staged state.

`SchedulerAdapter.render()` and `SchedulerAdapter.verify()` are read-only. Installation and enablement occur only during the activation transaction. Uninstall first disables the task, verifies it is inactive, and then removes its definition.

macOS uses `launchd`; Windows uses Task Scheduler. Shell-specific wrappers are avoided. If a wrapper is required for reliable environment setup, each platform receives its own generated, hashed file and test coverage.

## 8. Adoption transaction

Adoption is resumable and manifest-driven.

1. **Discover:** resolve the platform, ContextOS root, extension-contract version, local runtime, Python executable, and existing ProjectOS state.
2. **Preflight:** validate compatibility, path locality, write permissions, available disk space, SQLite support, scheduler availability, and absence of unsafe identifiers or secrets.
3. **Snapshot:** inventory and hash every ContextOS definition that may change; preserve the previous ProjectOS registry entry, skill, manifest, scheduler state, and local profile.
4. **Stage:** build a versioned bundle and machine profile outside live activation paths; render but do not enable the native scheduler definition.
5. **Verify:** validate file hashes, imports, migrations, doctor output, adapter calls, skill contract, scheduler rendering, path policy, role visibility, backup restoration, and rollback rehearsal.
6. **Adopt definitions:** atomically install the namespaced manifest and skill, then update the ContextOS extension registry.
7. **Activate runtime:** initialize or migrate the local database, install and enable the native scheduler, and mark the local profile adopted.
8. **Prove:** invoke the skill and common sync command, verify health and task state, and retain the transaction and rollback manifests.

Any failure before definition adoption leaves live ContextOS unchanged. Any later failure runs the recorded rollback in reverse order. A failed rollback stops and reports exact preserved recovery artifacts; it never attempts unrelated cleanup.

Phase 3 implementation may build and test every command while remaining detached. Running steps 6 through 8 against a real installation requires separate activation authorization.

## 9. Upgrade, rollback, and removal

Upgrades stage the new bundle beside the active version, verify database migration against a copied database, snapshot active definitions and scheduler state, and then atomically switch the registry entry. The previous bundle and database backup remain available until the new version proves healthy.

Rollback restores the prior registry entry, skill, scheduler definition/state, local profile, and compatible database backup. It never rolls the database backward without an explicit migration-compatible restore plan.

Removal:

1. disables skill discovery;
2. disables and removes the scheduler task;
3. removes only the namespaced ProjectOS registry entry and managed definitions;
4. restores any ContextOS configuration explicitly recorded in the adoption snapshot;
5. archives local ProjectOS runtime state.

The SQLite database, backups, audit history, and adoption manifests remain recoverable. Permanent purge is a separate Owner-only operation and is outside automatic uninstall.

## 10. Security and privacy

- The Owner remains the only role permitted to manage the User Manifest and adoption settings.
- Admin remains PUBLIC-project edit only and cannot access administration capabilities.
- User remains PUBLIC-project view only.
- PRIVATE projects remain Owner-only.
- Credential records contain safe references, never usable secret material.
- Machine profiles and scheduler definitions are scanned for tokens, passwords, private keys, and build-machine identifiers.
- Diagnostic bundles redact email addresses, external IDs, paths marked sensitive, and credential-reference metadata where required.
- Scheduler commands never contain OAuth tokens or Google credentials.
- ContextOS exposes only allowlisted adapter commands.
- Bundle inventories and adoption snapshots use cryptographic hashes.

## 11. Verification strategy

### 11.1 Platform-independent automated gates

The normal test suite proves:

- identical domain and adapter behavior on both host abstractions;
- no absolute build-machine path, username, machine name, NAS name, or real external identifier in the wheel or extension bundle;
- deterministic manifest and bundle generation;
- safe configuration precedence;
- component-aware path containment for POSIX, drive-letter, and UNC paths;
- no symlink requirement on Windows;
- scheduler rendering without activation;
- lock acquisition, contention, timeout, stale-owner diagnostics, and release;
- adoption failure at every transaction boundary with successful rollback;
- upgrade and uninstall preserve unrelated ContextOS files and the ProjectOS database;
- skill discovery is impossible before successful adoption and after disablement;
- scheduled and skill-triggered synchronization use one command and one lock.

### 11.2 macOS acceptance gate

A clean macOS account or isolated host profile must prove:

- clean package installation;
- default and overridden local paths;
- ContextOS discovery and compatible preflight;
- staged bundle verification;
- `launchd` definition validation, installation, two-hour schedule, and removal;
- skill discovery and immediate synchronization through the configured fake gateway;
- upgrade, rollback, uninstall, and retained database recovery;
- absence of developer-machine identifiers.

### 11.3 Windows acceptance gate

A real Windows machine must prove:

- clean Python/package installation under a non-developer account;
- `%LOCALAPPDATA%` and explicitly overridden local paths;
- drive-letter and UNC ContextOS locations;
- staged bundle verification without Developer Mode or symlink privileges;
- Task Scheduler definition validation, installation, two-hour schedule, non-overlap, and removal;
- skill discovery and immediate synchronization through the configured fake gateway;
- lock contention across independent processes;
- upgrade, rollback, uninstall, and retained database recovery;
- absence of developer-machine identifiers.

Simulated Windows tests run on macOS during development, but they cannot satisfy the Windows release gate. Windows support is reported as unverified until the real Windows acceptance record is returned and reconciled.

## 12. Windows implementation and troubleshooting handoff

The Phase 3 delivery includes a self-contained handoff document for Claude or another implementer operating on the Windows target. It provides:

- exact source revision and artifact hashes;
- prerequisites and supported Python/ContextOS contract versions;
- PowerShell-safe commands without embedded credentials;
- clean-room directory and environment setup;
- read-only discovery and preflight commands;
- staged adoption commands;
- Task Scheduler inspection and verification commands;
- skill discovery and sync checks;
- upgrade, rollback, and uninstall rehearsals;
- expected structured results and evidence locations;
- common failure signatures and bounded remediation;
- a prohibition on changing live state until the staged gates pass;
- a final evidence template for return to the controlling build.

The handoff cannot instruct the Windows implementer to invent paths, bypass a failed gate, disable security controls, or claim success from simulated output.

## 13. Implementation sequence

Phase 3 implementation is divided into bounded candidates:

1. **3A — Cross-platform contracts:** host protocols, platform paths, ContextOS locator, manifest schema, bundle builder, and tests.
2. **3B — Transaction engine:** discover, preflight, snapshot, stage, verify, adopt, rollback, upgrade, and uninstall against isolated fixtures.
3. **3C — Native schedulers and skill:** `launchd`, Task Scheduler, common lock/sync command, conditional skill discovery, and adapter capability tests.
4. **3D — Clean-room handoff:** deterministic artifacts, macOS acceptance, Windows handoff package, real Windows evidence intake, and final cross-platform release reconciliation.

Each candidate runs focused tests. The complete regression suite runs once when Phase 3 becomes a release candidate. Live activation and live Google work remain separate approval boundaries.

## 14. Acceptance criteria

Phase 3 is complete only when:

1. One ProjectOS release installs through supported onboarding on both macOS and Windows.
2. No packaged file contains a developer-specific machine name, username, home path, NAS path, drive letter, Google identifier, or credential.
3. SQLite and all high-frequency runtime state remain local on both platforms.
4. ContextOS discovers the ProjectOS skill only after a verified adoption transaction.
5. Skill activation and the native two-hour scheduler invoke the same idempotent locked sync command.
6. macOS uses a verified `launchd` integration and Windows uses a verified Task Scheduler integration.
7. Windows installation requires neither Developer Mode nor symlink privileges.
8. Failed adoption, upgrade, or activation leaves unrelated ContextOS state unchanged and provides a verified rollback path.
9. Uninstall removes ProjectOS integration while retaining a recoverable database and audit artifacts.
10. Automated platform-contract tests, the full ProjectOS regression suite, the macOS acceptance gate, and the real Windows acceptance gate all pass.
11. Operations and troubleshooting documentation allow another implementer to reproduce the supported installation without knowledge of the original development machine.

## 15. Deferred work

The following remain outside Phase 3:

- live Google Sheet creation and GAS deployment;
- Looker Git evaluation, migration, and analytics cutover;
- Linux scheduler support;
- mobile or browser-only ProjectOS hosting;
- automatic schema generation from discovered machine content;
- multi-writer SQLite or remote database replacement;
- permanent purge of ProjectOS runtime or historical evidence.

These items require separate designs and authorization. Their absence does not weaken the Windows and macOS requirements defined here.
