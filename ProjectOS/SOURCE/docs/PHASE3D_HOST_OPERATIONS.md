# ProjectOS Phase 3D Host Operations

Status: `SIMULATED`. The Phase 3D-B host runner is implemented, but this handoff does not authorize or perform native execution.

## Safety boundary

Use a new standard-user account, a new ContextOS fixture, a disposable current-schema SQLite database, and an acceptance runtime that is local and separate from every ContextOS or shared root. Do not use an existing ContextOS installation, production database, real Google configuration, GAS deployment, Looker repository, stored account password, elevated terminal, or system-wide scheduler location.

macOS and Windows require separate Owner authorization. Authorization for one host does not authorize the other. The ordinary `projectos` command can only build or verify packages and evidence and reconcile returned records. Preparation, native lifecycle, and recovery exist only in `python -m projectos.acceptance_host`. Do not invoke `run` until the Owner authorizes that exact host.

## Package verification

1. Receive the acceptance ZIP and its SHA-256 through separate channels.
2. Compare the received hash before extraction.
3. Install the bundled wheel into a new offline virtual environment.
4. Run `projectos acceptance package verify PACKAGE`.
5. Stop on any unexpected member, hash mismatch, link, path error, noncanonical manifest, or release mismatch.

The schema-2 package contains exactly seven members: the manifest, wheel, embedded ContextOS extension bundle, macOS wrapper, Windows wrapper, this document, and checksum inventory.

## Fixture preparation

Create the ContextOS fixture through the existing `adoption fixture init` command with acknowledgement `FIXTURE_ONLY`. Initialize only the disposable database and configuration, with invented identifiers, through the existing ProjectOS fixture workflow. Create a new empty evidence destination below the acceptance runtime, then run:

```text
python -m projectos.acceptance_host prepare \
  --acceptance-root ACCEPTANCE_ROOT --runtime-root RUNTIME_ROOT \
  --fixture-root FIXTURE_ROOT --machine-profile MACHINE_PROFILE \
  --package PACKAGE --evidence-root EVIDENCE_ROOT \
  --acceptance-ack CLEAN_HOST_NATIVE_ACCEPTANCE --fixture-ack FIXTURE_ONLY
```

`prepare` is one-shot. It issues the local authority, verifies the schema-2 package, stages only the verified extension bundle, and persists random preparation, definition-transaction, and activation identifiers. It performs no native action.

Do not copy a marker or receipt, hand-edit a profile, reuse a failed run identifier, or move runtime state to a shared location.

## Read-only preflight

Run the same command line with `preflight` instead of `prepare`.

Preflight verifies authority, release binding, fixture locality, profile binding, evidence locality, standard-user state, and structural equivalence. It returns the exact planned native argument arrays without invoking them. Stop if a task with the dedicated acceptance identifier already exists.

Dedicated identifiers:

- macOS: `com.contextos.projectos.acceptance.sync`
- Windows: `ContextOS\ProjectOS\Acceptance\Sync`

## Separately authorized 3D-B run

After explicit authorization for the specific host, rerun preflight and review the planned actions. Replace `preflight` with `run`; do not change any root, package, profile, acknowledgement, or identifier. The authorized lifecycle stages disabled, enables, triggers immediately, proves common-lock contention and native non-overlap, confirms the two-hour and eligible-resume configuration, disables discovery before scheduler teardown, removes only a hash-matching owned task, rolls back the fixture definition, retains the database, and seals sanitized evidence.

On macOS the only trigger effect is fixed `launchctl kickstart` against the per-user `gui/<uid>` service. On Windows it is fixed `schtasks.exe /Run /TN` against the dedicated current-user task. No shell, PowerShell, password, `/RU`, `/RP`, system LaunchDaemon, or arbitrary task identifier is accepted.

A foreign task, definition mismatch, registry mismatch, inventory mismatch, elevation, path escape, or uncertain native output stops the run. There is no force or overwrite option.

## Recovery

Recovery uses the same command line with `recover --run-id RUN_ID`. It requires the same roots, receipts, package, profile, acknowledgements, and evidence destination. It restores disabled discovery first, releases an owned barrier, disables and removes only a hash-matching task, deactivates runtime state, and rolls back definition state. Recovery is idempotent. Preserve and review uncertain state; do not delete it manually.

Exit `0` means sealed evidence. Exit `3` means incomplete or recovered acceptance. Exit `2` means validation failed; recheck the exact durable inputs and never force the operation. Exit `1` is an unexpected redacted internal error; preserve local state and stop. Each invocation emits one JSON envelope. Do not paste raw native output or local paths into returned evidence.

## Evidence return

Return only the sanitized evidence ZIP and communicate its SHA-256 separately. Keep the disposable database, configuration, local profiles, journals, trigger windows, probe spool, raw native diagnostics, and task history on the host. The controller verifies schema-2 manifest, wheel, extension-bundle, preparation, and definition bindings before reconciliation. One accepted host advances only that platform; both are required for `CROSS_PLATFORM_VERIFIED`. Until separately authorized evidence is accepted, support remains `SIMULATED`.
