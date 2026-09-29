# ProjectOS Phase 3C Operations

Phase 3C proves scheduler definitions, conditional skill discovery, the common locked synchronization entrypoint, and reversible runtime activation in an isolated fixture. It does not install a native scheduler or modify a live ContextOS installation.

## Safety boundary

All `adoption fixture` commands require all three fixture authorities:

- a root created by `adoption fixture init`;
- the matching receipt below the separate local runtime root;
- `--fixture-ack FIXTURE_ONLY` on every command.

The ContextOS root and runtime root must remain separate. Do not point these commands at an existing ContextOS installation, a shared root, or a production database. The CLI exposes no live activation alias, native runner selector, scheduler-enable shortcut, or force option.

Phase 3C renders macOS `launchd` and Windows Task Scheduler definitions but exercises lifecycle operations only through `FixtureSchedulerRunner`. Running `launchctl`, `schtasks`, Task Scheduler COM, PowerShell wrappers, or an elevated console is outside this phase.

## Prerequisites

Activation requires:

1. A completed Phase 3B fixture definition transaction in state `ADOPTED`.
2. A canonical ProjectOS skill inside the installed immutable extension version.
3. The registry entry still set to `enabled:false`.
4. The canonical machine profile at `<runtime>/adoption/machine-profile.json`.
5. A pre-existing, current-schema fixture SQLite database at the profile path.
6. Exactly one active protected Owner, an enabled/write-enabled Google binding, a credential reference, and a matching local `projectos.toml` with both Google flags enabled.

Activation never creates or migrates the database. Prepare the isolated fixture database through the Phase 2 catalog commands, then write the local configuration with these fields:

```toml
contract_version = 1
machine_id = "fixture-machine-id"
environment = "DEV"
binding_id = "FIXTURE_BINDING_UUID"
spreadsheet_id = "fixture-sheet-id"
expected_owner_email = "fixture-owner@example.invalid"
credential_reference_id = "FIXTURE_CREDENTIAL_UUID"
google_enabled = true
google_write_enabled = true
```

Use invented fixture identifiers only. This file is local runtime state and must not be copied into the extension bundle, skill, evidence archive, or shared ContextOS root.

## Render the scheduler definition

Rendering is pure and leaves the fixture scheduler absent:

```bash
projectos adoption fixture scheduler render \
  --fixture-ack FIXTURE_ONLY \
  --contextos-root "$FIXTURE" \
  --machine-profile "$RUNTIME/adoption/machine-profile.json"
```

The JSON data must show `enabled:false`, `interval_seconds:7200`, `execution_limit_seconds:1800`, the profile scheduler kind, and an argument vector ending in `--trigger scheduler`. On macOS the content is a deterministic plist. On Windows it is deterministic Task Scheduler XML using an interactive token, `IgnoreNew`, `StartWhenAvailable`, and no stored password.

## Activate the fixture runtime

Use the transaction ID returned by the completed Phase 3B adoption:

```bash
projectos adoption fixture activate DEFINITION_TRANSACTION_ID \
  --fixture-ack FIXTURE_ONLY \
  --contextos-root "$FIXTURE" \
  --machine-profile "$RUNTIME/adoption/machine-profile.json"
```

Successful activation returns `state:"PROVED"` and an `activation_id`. The transaction performs these ordered operations:

1. verify the disabled installed definition and canonical skill;
2. validate the existing database and local configuration without migration;
3. persist and install a disabled definition through the fixture runner;
4. recheck runtime health;
5. enable the fixture scheduler;
6. atomically change only the ProjectOS registry entry to `enabled:true`;
7. resolve the skill and prove both `scheduler` and `skill` triggers with a fake gateway.

The proof never authenticates Google or touches a real spreadsheet. If activation fails after scheduler staging, automatic rollback restores the exact disabled registry bytes before removing fixture scheduler state.

## Inspect discovery

```bash
projectos adoption fixture skill inspect \
  --fixture-ack FIXTURE_ONLY \
  --contextos-root "$FIXTURE" \
  --machine-profile "$RUNTIME/adoption/machine-profile.json"
```

Success returns the verified skill, version, capabilities, and adapter descriptor. A failed gate returns no skill and one bounded diagnostic, including `REGISTRY_DISABLED`, `INVENTORY_MISMATCH`, `SKILL_CONTRACT_INVALID`, `PROFILE_UNAVAILABLE`, `DATABASE_UNHEALTHY`, or `SCHEDULER_INACTIVE`. Inspection is read-only and never repairs state or calls Google.

## Common runtime synchronization

The scheduler and ContextOS skill use the same command:

```bash
projectos --db "$RUNTIME/projectos.db" runtime sync \
  --machine-profile "$RUNTIME/adoption/machine-profile.json" \
  --trigger scheduler
```

Use `--trigger skill` for a skill invocation. Scheduler waits zero seconds for the common profile lock. Skill waits ten seconds by default and accepts `--wait-seconds` only from zero through thirty. A contended invocation returns `status:"LOCKED"`, exit `3`, and bounded metadata without a path or command line.

Unlike activation proof, the production `runtime sync` route constructs the guarded real Google gateway. Do not invoke it against an account or spreadsheet until the separate Google activation is authorized and its credentials, sharing, contract, and write gates have passed.

The explicit `--db` must exactly match the validated profile. The command opens that existing database without initialization or migration. It offers no fake gateway or fixture-file switch.

## Recover an interrupted activation

Use the activation ID from `<runtime>/adoption/activations/`:

```bash
projectos adoption fixture activation-recover ACTIVATION_ID \
  --fixture-ack FIXTURE_ONLY \
  --contextos-root "$FIXTURE" \
  --machine-profile "$RUNTIME/adoption/machine-profile.json"
```

Recovery is idempotent. It restores the exact disabled registry snapshot, disables an enabled fixture scheduler, removes the fixture definition, and ends at `ROLLED_BACK`. If ownership or hashes no longer match, preserve all state and stop; do not delete or hand-edit the journal.

## Deactivate a proved activation

```bash
projectos adoption fixture deactivate ACTIVATION_ID \
  --fixture-ack FIXTURE_ONLY \
  --contextos-root "$FIXTURE" \
  --machine-profile "$RUNTIME/adoption/machine-profile.json"
```

Deactivation first restores `enabled:false`, proves discovery returns `REGISTRY_DISABLED`, then disables and removes the fixture scheduler. It retains the activation journal, disabled registry snapshot, scheduler definition, proof result, database, configuration, logs, and Phase 3B recovery artifacts. Phase 3B rollback, uninstall, or upgrade must not proceed while the registry entry is enabled.

## Exit codes and troubleshooting

- Exit `0`: command completed. For skill inspection, also examine `diagnostic`.
- Exit `2`: invalid arguments, fixture authority, compatibility, identifier, or validation failure. Correct the input; do not force it.
- Exit `3`: runtime health, activation, preflight, lock contention, or synchronization did not complete. Recover a generated activation before retrying.
- Exit `1`: unexpected failure with a redacted envelope. Preserve the local journal and debug context, then stop.

Never solve a failure by editing registry JSON, journals, receipts, scheduler fixture state, immutable versions, or the machine profile. Recreate a disposable fixture when input preparation was wrong. Preserve a failed fixture when ownership or inventory checks fail.

## Retained evidence

Keep relative-path inventories and SHA-256 hashes for:

```text
<runtime>/adoption/machine-profile.json
<runtime>/adoption/transactions/<definition-id>/
<runtime>/adoption/activations/<activation-id>/
<runtime>/adoption/scheduler-fixtures/ (only while installed)
<contextos>/context-os/extensions/registry.json
<contextos>/context-os/extensions/projectos/versions/<version-hash>/
```

Do not archive the database, configuration, absolute paths, usernames, machine names, emails, spreadsheet identifiers, credential references, tokens, or private keys as portable evidence.
