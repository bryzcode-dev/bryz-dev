# ProjectOS Phase 2 Operations

Phase 2 operates ProjectOS locally with SQLite as the single source of truth and Google Sheets/GAS as replaceable collaboration surfaces. This runbook stops at local Level A verification. It does not authorize or perform live Google, Context OS, scheduler, or Looker changes.

## 1. Runtime locations

The CLI database path is explicit through `--db` or `PROJECTOS_DB`; its default is `~/.projectos/projectos.db`. Google configuration resolves in this order:

1. `--config /absolute/path/projectos.toml`;
2. `$PROJECTOS_HOME/projectos.toml`;
3. `~/Library/Application Support/ProjectOS/projectos.toml` on macOS.

Copy `config/projectos.example.toml` to the machine-local ProjectOS home only when preparing an authorized Google stage. Never commit the populated file. Keep credentials outside ProjectOS and store only a safe credential-reference locator in SQLite.

Every CLI invocation prints exactly one JSON document. Exit `0` is success, `2` is validation/version failure, `3` is a health, lock, preflight, or controlled operational failure, and `1` is a redacted internal error.

## 2. Level A onboarding

Use Python 3.11 or newer:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
export PROJECTOS_HOME="$(pwd)/.local-projectos"
export PROJECTOS_DB="$PROJECTOS_HOME/projectos.db"
mkdir -p "$PROJECTOS_HOME"
.venv/bin/projectos --db "$PROJECTOS_DB" init
.venv/bin/projectos --db "$PROJECTOS_DB" doctor
```

Seed the one protected Owner first. A second active Owner is rejected, and the protected Owner cannot be disabled, demoted, or replaced.

```bash
.venv/bin/projectos --db "$PROJECTOS_DB" user seed-owner \
  --owner-email owner@example.invalid --display-name "Owner"
.venv/bin/projectos --db "$PROJECTOS_DB" user create \
  --owner-email owner@example.invalid --email admin@example.invalid \
  --display-name "Admin" --role ADMIN --actor owner@example.invalid
.venv/bin/projectos --db "$PROJECTOS_DB" user create \
  --owner-email owner@example.invalid --email user@example.invalid \
  --display-name "User" --role USER --actor owner@example.invalid
```

Use real email addresses only in the machine-local database. The examples use reserved `.invalid` addresses deliberately.

## 3. Disabled Google binding and contract planning

Create a credential reference, never a credential value:

```bash
.venv/bin/projectos --db "$PROJECTOS_DB" credential create \
  --provider GOOGLE --label "ProjectOS sync" --credential-type ADC \
  --purpose "Workbook synchronization" --storage-system KEYCHAIN \
  --storage-reference "projectos/google" --actor owner@example.invalid
```

Use the returned `credential_id` to create a binding. Omit `--enabled` and `--write-enabled` in Level A:

```bash
.venv/bin/projectos --db "$PROJECTOS_DB" google binding create \
  --environment DEVELOPMENT --spreadsheet-id PLACEHOLDER_NOT_LIVE \
  --display-name "ProjectOS local fixture" --contract-version 1 \
  --credential-id CREDENTIAL_UUID --actor owner@example.invalid
```

Show the canonical contract or plan an invented snapshot without mutation:

```bash
.venv/bin/projectos --db "$PROJECTOS_DB" google contract show
.venv/bin/projectos --db "$PROJECTOS_DB" google contract plan \
  --snapshot tests/fixtures/google/empty-contract-v1.json
```

The planner may propose create/protect/format actions. Unknown populated tabs, missing required data, reordered headers, or incompatible contract versions block mutation. It never edits a workbook.

## 4. Fake synchronization

The fake gateway performs no network access. A sync run still requires the local binding write gate, so enable a fixture-only binding deliberately in a disposable database:

```bash
.venv/bin/projectos --db "$PROJECTOS_DB" google binding update BINDING_UUID \
  --expected-version 1 --enabled true --write-enabled true \
  --actor owner@example.invalid
.venv/bin/projectos --db "$PROJECTOS_DB" sync plan BINDING_UUID \
  --owner-email owner@example.invalid --gateway fake \
  --fixture tests/fixtures/google/populated-contract-v1.json
.venv/bin/projectos --db "$PROJECTOS_DB" sync run BINDING_UUID \
  --owner-email owner@example.invalid --gateway fake \
  --fixture LOCAL_FAKE_SYNC_FIXTURE.json --trigger manual
.venv/bin/projectos --db "$PROJECTOS_DB" sync status BINDING_UUID \
  --owner-email owner@example.invalid
```

The fixture must set `write_ready:true` for publication. Tests cover accepted and rejected requests, stale-version conflicts, access events, publication failures, idempotent retry, and verified revision activation.

## 5. Request, conflict, and projection lifecycle

1. GAS appends an immutable request under a script lock.
2. Sync validates the UUID, canonical hash, actor, role, entity, operation, base version, and field allowlist.
3. The SQLite mutation, receipt, and audit event commit atomically.
4. A stale base version creates a durable conflict without changing canonical data.
5. Results are published with safe messages; no canonical value is echoed.
6. A new projection revision is staged and read-back verified.
7. The active pointer and checkpoint advance only after successful verification.

If SQLite committed but publication failed, rerun sync. The durable receipt returns the previous result, preventing a second mutation. Owner conflict resolution creates a new transaction and never rewrites history:

```bash
.venv/bin/projectos --db "$PROJECTOS_DB" conflict list \
  --owner-email owner@example.invalid --status OPEN
.venv/bin/projectos --db "$PROJECTOS_DB" conflict resolve CONFLICT_UUID \
  --binding-id BINDING_UUID --owner-email owner@example.invalid \
  --actor-email owner@example.invalid --strategy KEEP_CANONICAL
```

## 6. Authorization model

| Role | Visible projects | Editing | Administration |
|---|---|---|---|
| Owner | PUBLIC and PRIVATE | Full approved domain fields | Users, conflicts, audit, settings |
| Admin | PUBLIC only | Allowlisted PUBLIC fields | None |
| User | PUBLIC only | None | None |

Identity comes from the protected SQLite manifest in Python and `Session.getActiveUser().getEmail()` in GAS. Blank, malformed, inactive, and unlisted identities receive no data. Query parameters, form fields, browser storage, and client-supplied roles are never authorization inputs.

## 7. Lock recovery

The default lock is next to the database with suffix `.sync.lock`; `--lock-path` can set an explicit local path. If sync returns `LOCKED`:

1. inspect the safe JSON lock metadata;
2. verify the recorded PID belongs to ProjectOS and whether it is alive;
3. do not start a second sync while the PID is alive;
4. allow ProjectOS to recover only a valid ProjectOS lock owned by a dead PID.

Age alone does not make a lock stale. Do not manually delete an ambiguous lock.

## 8. Backups, restore, and diagnostics

Before any future Level B/C operation:

```bash
.venv/bin/projectos --db "$PROJECTOS_DB" backup create /safe/backup/directory
.venv/bin/projectos --db "$PROJECTOS_DB" backup verify /safe/backup/manifest.json
```

Restore to a separate target first. ProjectOS refuses active targets, SQLite sidecars, newer schemas, checksum failures, and overwrite without `--replace`:

```bash
.venv/bin/projectos --db "$PROJECTOS_DB" backup restore \
  /safe/backup/manifest.json /safe/staged/projectos.db
```

Create a redacted diagnostic bundle:

```bash
.venv/bin/projectos --db "$PROJECTOS_DB" diagnostics create /safe/diagnostics
```

The bundle contains health, schema, safe binding flags, and recent error codes. It excludes emails, private project rows/names/counts, credentials, request contents, and raw Sheet data. Scan it before sharing.

## 9. GAS build and local preview

```bash
node --test gas/test/*.test.js
node gas/scripts/build.mjs --out gas/dist
node gas/scripts/preview.mjs --fixture gas/test/fixtures/ui-roles.json --port 4173
```

The build emits deterministic `Code.gs`, `index.html`, `styles.html`, and `app.html`. The preview is local fixture mode and accepts `?role=owner`, `?role=admin`, or `?role=user`. Deployed GAS does not use that parameter; it calls the canonical `getSession` endpoint.

## 10. Activation boundary

- **Level A:** fake gateway, invented fixtures, no Google packages required, no network work.
- **Level B:** separately authorized read-only preflight for an exact test workbook/account; writes remain disabled.
- **Level C:** separately authorized test-workbook writes after verified backups and a reviewed repair plan; both binding/config and CLI write gates are required.

Phase 2 does not authorize Level B or C, GAS deployment, the two-hour scheduler, skill installation, Context OS adoption, Looker migration, or production cutover. Write a new staged plan and obtain explicit authorization before any of them.
