# ProjectOS Phase 4-D Cutover and Rollback

Status: `SIMULATED`. Preparation is implemented and recording-executor recovery is verified. No legacy script, Sheet trigger, `launchd` job, Windows scheduled task, GAS deployment, or Google resource has been disabled, removed, or changed.

## Authorization boundaries

Treat these as separate approvals:

1. Read-only collection on one named macOS or Windows source machine.
2. Transfer and import of its verified evidence archive.
3. A real Google refresh through the existing authenticated ProjectOS boundary.
4. Cutover preparation for the exact source machine and automation targets.
5. Native cutover execution for those exact targets.
6. Rollback or later permanent retirement.

Approval for one step never authorizes the next. The ordinary `projectos` CLI exposes local `looker cutover prepare` and database-free `looker cutover verify`; it has no disable, remove, execute, force, purge, or delete command. Native effects exist only in the separate `projectos.looker_cutover_host` module for a specifically authorized host workflow.

## Preparation

Prerequisites are schema 3, a verified intake, a healthy SQLite backup, at least one explicit legacy mapping with every mapping `MATCHED`, one immutable ready reconciliation, a verified real refresh receipt, passing validation, a preserved legacy tree, no open Critical or Important finding, one protected active Owner, and exact automation targets with expected ownership and fixed inspect/disable/remove/restore argument arrays. An empty mapping set is incomplete and blocks preparation.

Create canonical target JSON as a list. Arguments are arrays, never shell strings:

```json
[
  {
    "target_id": "legacy-sync",
    "target_type": "LAUNCHD_OR_WINDOWS_TASK",
    "expected_owner": "owner-fingerprint-from-approved-inspection",
    "inspect_owner_argv": ["approved-inspector", "legacy-sync"],
    "disable_argv": ["approved-controller", "disable", "legacy-sync"],
    "remove_argv": ["approved-controller", "remove", "legacy-sync"],
    "restore_argv": ["approved-controller", "restore", "legacy-sync"]
  }
]
```

Then prepare and verify locally. The ordinary CLI always creates a `SIMULATED` package; it is suitable for review and recording-executor tests but can never execute native effects:

```text
projectos --db <projectos.sqlite> looker cutover prepare <project-id> <intake-run-id> <reconciliation-id> --refresh-receipt <real-refresh.json> --backup-manifest <backup.manifest.json> --legacy-root <preserved-legacy-root> --targets <targets.json> --prepared-at <UTC-timestamp> --output <cutover.zip> --owner-email <protected-owner-email> --actor <protected-owner-email>
projectos looker cutover verify <cutover.zip>
```

The deterministic ZIP contains `manifest.json`, a complete checklist, an ordered effect plan, a rollback plan, and the retained legacy files. Every member is hashed and canonical. The package rejects traversal, duplicate case-folded paths, links, unexpected members, changed bytes, mixed ownership, failed readiness, and secret markers. It contains the protected Owner's SHA-256 identity binding but no execution token, signing key, or reusable credential.

## Separately authorized execution

Do not call the host module from ordinary automation. A separately authorized host workflow must create a `REAL` package, load a minimum 32-byte approval key from protected OS credential storage, and obtain an external `CutoverApproval` receipt after the package exists. The receipt is HMAC-authenticated and binds the exact package hash, cutover ID, target hash, protected Owner identity, approval timestamp, and nonce. Never put the approval key in the package, repository, command line, journal, or Google Sheet.

At the execution boundary, reverify the package hash, exact target list, signed Owner receipt, current process identity, and target ownership. `CutoverHostTransaction` rejects `SIMULATED` packages before inspection. The transaction writes each intent durably before inspection or effect, checks ownership before every change, disables all triggering before removing any automation, and stops on uncertainty. If ownership changes on a later target after an earlier effect completed, it immediately rolls back every completed target.

Automated tests use only a recording executor. The verified order is:

```text
inspect-owner, disable, inspect-owner, remove
```

On a simulated remove failure, the verified recovery path is:

```text
inspect-owner, restore
```

An interrupted transaction with an unknown pending effect fails closed with `process reconstruction is uncertain`; a human must establish the exact external state before a newly authorized recovery. Never guess whether an effect ran.

## Rollback

Rollback restores the exact captured scheduler or trigger definition and script configuration for every target that was changed. It does not purge SQLite: imported evidence, reconciliation reports, audit events, backup records, and cutover preparation records remain. The legacy archive has permanent retention and is never deleted by execution or rollback.

If rollback fails:

1. stop all further effects;
2. preserve the cutover ZIP, journal, SQLite database, backup, and native diagnostic output locally;
3. do not rerun or edit the journal;
4. compare the exact current owner and target state with `effect-plan.json` and `rollback.json`;
5. request a new exact-target Owner recovery approval.

Successful recording simulation is not proof that native macOS or Windows commands work. Each platform requires its own separately authorized execution and returned evidence.
