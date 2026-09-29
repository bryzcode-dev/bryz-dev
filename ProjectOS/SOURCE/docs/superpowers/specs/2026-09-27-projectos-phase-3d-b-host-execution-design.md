# ProjectOS Phase 3D-B — Prepared Clean-Host Execution Design

**Date:** 2026-09-27
**Status:** Approved design; implementation pending
**Program:** ProjectOS
**Parent specification:** `docs/superpowers/specs/2026-09-27-projectos-phase-3d-clean-host-acceptance-design.md`
**Prerequisite:** Phase 3D-A candidate at `3222770`

## 1. Purpose

Phase 3D-B makes the Phase 3D-A host module operational on a clean standard-user macOS or Windows host without executing either platform in the build workspace. It adds a guarded preparation step, binds the ContextOS extension bundle into the release package, connects the existing adoption and activation transactions to the host acceptance transaction, proves that acceptance probes were launched by the native scheduler, and seals deterministic evidence.

Implementation remains local and recording-only. Running the completed package with `launchctl` or `schtasks.exe` is a later, separately authorized operation for each host.

## 2. Selected operator flow

The separate host module exposes four commands:

```text
python -m projectos.acceptance_host prepare ...
python -m projectos.acceptance_host preflight ...
python -m projectos.acceptance_host run ...
python -m projectos.acceptance_host recover --run-id ACCEPTANCE_RUN_ID ...
```

`prepare` is the only new public command. It replaces manual assembly of acceptance authority and profile files. The ordinary `projectos` CLI remains unable to prepare or execute native acceptance.

The operator still creates a new Phase 3 fixture and its machine profile through the existing fixture commands. `prepare` then consumes that clean fixture, a verified acceptance package, a new empty acceptance root, a separate local runtime, and an evidence directory below that runtime.

## 3. Release package correction

The deterministic acceptance ZIP expands from six to seven members:

```text
acceptance-manifest.json
projectos-0.1.0-py3-none-any.whl
projectos-extension.zip
macos/run-projectos-acceptance.sh
windows/Run-ProjectOSAcceptance.ps1
docs/PHASE3D_HOST_OPERATIONS.md
SHA256SUMS.txt
```

The package builder requires a verified extension bundle input. The manifest adds one exact `extension_bundle` object containing filename, size, member count, SHA-256, extension identifier, product version, and manifest SHA-256. The outer checksum inventory binds the complete nested archive. Verification reopens the nested bundle, applies the existing `ArtifactPolicy`, and rejects a release, skill, compatibility, inventory, or hash mismatch.

The extension bundle is not generated on the target host and is never accepted as an unbound sidecar. This preserves the single-package operator workflow and ensures the definition transaction installs the same reviewed extension payload on both platforms.

## 4. Preparation authority

`prepare` requires:

- exact acknowledgements `CLEAN_HOST_NATIVE_ACCEPTANCE` and `FIXTURE_ONLY`;
- a new empty non-symlink acceptance root;
- an existing local runtime outside the fixture, ContextOS, and shared roots;
- an issued Phase 3 fixture marker and same-host receipt;
- the fixture machine profile;
- the verified acceptance package;
- an existing empty evidence directory below the acceptance runtime;
- a non-elevated standard-user session matching the package host family.

Preparation performs no native scheduler action and does not change the fixture registry. It:

1. issues the acceptance authority and same-host receipt;
2. atomically extracts only the verified embedded extension bundle below the acceptance staging root;
3. allocates safe random definition-transaction and activation identifiers;
4. derives the acceptance profile from the fixture machine profile;
5. binds package, wheel, extension-bundle, source, receipt, and host hashes;
6. creates the local acceptance store and evidence spool;
7. writes one canonical preparation record containing only bounded identifiers and hashes.

Preparation is one-shot. Reusing a root, identifier, profile, staged bundle, or evidence spool fails closed. Failure removes only temporary files created before the canonical preparation record; it never removes an issued fixture or alters its registry.

## 5. Transaction adapters

Two narrow controllers connect the existing transactions to `HostAcceptanceTransaction`:

- `DefinitionAcceptanceController` begins the existing `AdoptionTransaction` with the prepared definition transaction ID and embedded bundle, runs preflight, snapshot, stage, verify, and disabled adoption, and rolls back only its hash-owned transaction.
- `ActivationAcceptanceController` begins the existing `RuntimeActivation` with the prepared activation ID, verifies `PROVED`, deactivates to `DEACTIVATED`, and delegates failed-state recovery to the existing activation journal.

`LocalActivationStore.create_journal` and `RuntimeActivation.begin` gain an optional caller-supplied activation ID. Existing callers omit it and retain generated UUID behavior. A supplied identifier is accepted only when it is canonical, unused, and bound to the same prepared definition transaction.

The controllers expose their active state from persisted journals rather than process memory. Recovery after a new process starts therefore follows durable ownership.

## 6. Native trigger proof

Native acceptance evidence may not be produced by calling `AcceptanceProbe.run()` directly from the host process.

Each native runner gains a dedicated `trigger(definition) -> SchedulerInspection` operation restricted to an already enabled, hash-owned acceptance task. macOS uses fixed `launchctl kickstart` arguments. Windows uses fixed `schtasks.exe /Run` arguments. The shared production `SchedulerAction` contract remains unchanged.

`NativeProbeController` owns only bounded spool and barrier coordination:

1. clear and hash-bind the expected event window;
2. request a native trigger;
3. wait up to the profile limit for exactly one matching receipt-bound event;
4. prove immediate completion;
5. start the receipt-bound barrier case through the native task;
6. wait for exactly one `STARTED` event;
7. request a second native trigger while the first holds the common lock;
8. require one `LOCKED` event and no second barrier entrant;
9. release the barrier and require the first invocation to terminate safely.

Events from another receipt, release, definition, run, sequence window, or case are ignored and recorded locally as a bounded failure. Timeout, duplicate start, missing lock contention, or an unexpected successful overlap fails the transaction and begins recovery.

## 7. Host execution and recovery

Every `preflight`, `run`, and `recover` invocation reopens and validates the preparation record, authority receipt, fixture receipt, profile, package, staged bundle, evidence destination, standard-user session, definition equivalence, database locality and health, and current native ownership.

`run` constructs `SubprocessNativeExecutor` only after complete preflight and then starts `HostAcceptanceTransaction`. It emits the acceptance run ID as soon as the first journal exists. Exit `0` means evidence sealed, exit `3` means incomplete or recovered acceptance, exit `2` means validation failed before a host journal existed, and exit `1` is a redacted unexpected failure.

`recover` requires the exact run ID and reconstructs all controllers from durable state. It restores disabled discovery before scheduler teardown, releases an owned barrier, disables and removes only a matching native task, deactivates activation state, rolls back the definition transaction, and preserves the database, configuration, diagnostics, journals, and failed evidence spool. Any ownership or inventory uncertainty stops recovery without deletion.

There is no force, overwrite, purge, arbitrary task ID, runner selector, shell command, environment override, production root, or live Google option.

## 8. Evidence sealing

`HostEvidenceCollector` translates typed preparation, transaction, scheduler inspection, and probe events into the existing allowlisted evidence model. It never copies logs or native output.

The host record adds the extension-bundle SHA-256 and preparation-record SHA-256. Every required case is derived from a named durable fact. A case cannot be marked `NATIVE` unless the matching event falls inside a native-trigger window recorded by `NativeProbeController`.

Evidence sealing requires:

- terminal `EVIDENCE_SEALED` journal state;
- disabled registry and deactivated runtime;
- native task absence confirmed after removal;
- definition rollback and retained database health;
- all required cases passed exactly once;
- safe attachment inventory and identifier/secret/path scans.

The evidence archive is written atomically below the prepared evidence root. Raw native diagnostics remain excluded and local.

## 9. Installed-wheel and platform testing

Implementation tests execute no native command. They use recording executors and isolated fixture roots to prove:

- the seven-member package is deterministic and rejects a changed nested bundle;
- preparation is one-shot, local, non-elevated, release-bound, and rollback-safe;
- existing adoption and activation transactions receive the prepared IDs and recover across process reconstruction;
- native triggers use only fixed argument arrays against enabled hash-owned acceptance tasks;
- direct in-process probe calls cannot satisfy native cases;
- duplicate, foreign, stale, reordered, and timed-out events fail closed;
- run and recover return the documented envelopes and exit codes;
- installed-wheel preparation, simulated run, crash recovery, evidence sealing, verification, and reconciliation work without the source checkout;
- prior ProjectOS and GAS behavior remains unchanged.

macOS tests patch `SubprocessNativeExecutor`; Windows tests use Windows path objects and recording executors. Real platform evidence is accepted only from a separately authorized host run.

## 10. Documentation and distribution

The packaged and repository host-operation documents remain byte-identical. They provide complete macOS and Windows standard-user procedures, hash verification, offline wheel installation, fixture creation, `prepare`, read-only preflight, the explicit authorization boundary before `run`, recovery, evidence return, and troubleshooting by bounded error code.

The Claude implementation handoff explains the file architecture, durable state, package members, command envelopes, failure ownership, and how to diagnose preparation, native output, journal, cleanup, and evidence failures without bypassing a guard.

## 11. Completion boundaries

The implementation phase completes when the package, preparation, controller, trigger, recovery, evidence, installed-wheel, documentation, and complete regression gates pass with recording executors only. Its status remains `SIMULATED`.

No implementation command may execute `launchctl`, `schtasks.exe`, Google, GAS, Looker, a live ContextOS root, a shared root, or production SQLite. A real macOS run and a real Windows run remain two separate Owner-authorized operations. Cross-platform status remains unavailable until both returned evidence archives verify and the Owner accepts reconciliation.
