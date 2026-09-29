# ProjectOS Phase 1 Operations

## Runtime and data locations

Use Python 3.11 or newer. The CLI uses `--db PATH`; if omitted, it reads `PROJECTOS_DB` and otherwise defaults to `~/.projectos/projectos.db`. The database, its WAL/SHM sidecars, backup snapshots, manifests, and debug logs are local runtime state and must not be committed.

SQLite is the sole source of truth. Phase 1 does not read or write Google Sheets and does not modify a live Context OS installation.

## JSON contract and exit codes

Every invocation writes one JSON document to stdout with these keys:

```text
ok, command, data, errors, meta.schema_version
```

Exit codes are stable:

| Code | Meaning |
|---:|---|
| 0 | Command completed successfully |
| 1 | Unexpected internal error; response details are redacted |
| 2 | Validation, identifier, or optimistic-version conflict |
| 3 | Health, backup, restore, or doctor failure |

Parser errors never echo supplied argument values. Set `PROJECTOS_DEBUG_LOG` only to an explicitly chosen local file when safe stack-location diagnostics are needed; it does not receive exception messages or command values.

## Initialize and check health

```bash
projectos --db /path/to/projectos.db init
projectos --db /path/to/projectos.db doctor
```

`doctor` checks SQLite integrity, foreign-key consistency, and the supported schema version. Treat exit code 3 as fail-closed.

## Projects and assets

```bash
projectos --db DB project create --slug fleet-tools --name "Fleet Tools" \
  --type GAS --visibility PUBLIC --context-os-registered \
  --context-os-project-id fleet-tools --actor owner@example.com

projectos --db DB location upsert PROJECT_UUID --machine-id work-mac \
  --location-type LOCAL_PROJECT --path /path/to/project --actor owner@example.com

projectos --db DB resource upsert PROJECT_UUID --resource-type GOOGLE_SHEET \
  --provider GOOGLE --external-id SHEET_ID --name "Master Sheet" \
  --url https://docs.google.com/spreadsheets/d/SHEET_ID --actor owner@example.com

projectos --db DB deployment upsert PROJECT_UUID --environment DEVELOPMENT \
  --external-deployment-id DEPLOYMENT_ID --script-id SCRIPT_ID \
  --deployment-url https://script.google.com/macros/s/DEPLOYMENT_ID/exec \
  --actor owner@example.com
```

Project updates require the current version:

```bash
projectos --db DB project update PROJECT_UUID --expected-version 1 \
  --name "Fleet Tools Renamed" --actor owner@example.com
projectos --db DB project archive PROJECT_UUID --expected-version 2 \
  --actor owner@example.com
```

Connections may use project or resource endpoints. A connection cannot bridge PUBLIC and PRIVATE projects because doing so could broaden private visibility.

```bash
projectos --db DB connection upsert --connection-type DATA_FLOW \
  --implementation-method GAS --source-project-id SOURCE_UUID \
  --target-project-id TARGET_UUID --purpose "Refresh reporting data" \
  --actor owner@example.com
projectos --db DB connection impact RESOURCE_UUID
```

## Credential references

Store only a locator for a credential, never the credential value:

```bash
projectos --db DB credential create --provider GOOGLE --label gas-deployer \
  --credential-type OAUTH --purpose "GAS deployment" --storage-system KEYCHAIN \
  --storage-reference service/projectos/gas-deployer --owner-project-id PROJECT_UUID \
  --actor owner@example.com

projectos --db DB credential link CREDENTIAL_UUID PROJECT_UUID \
  --resource-id RESOURCE_UUID --purpose "Deploy production GAS" \
  --actor owner@example.com
projectos --db DB credential impact CREDENTIAL_UUID
```

Secret-like keys and recognized private-key/token patterns are rejected before persistence. Audit payloads and manifest serialization use the same redaction rules. ProjectOS does not store passwords, API tokens, private keys, refresh tokens, or recovery codes.

## Context OS discovery review

The Phase 1 adapter scans immediate child directories under `--projects-dir`. Each managed child has a `project.json` manifest. Minimal shape:

```json
{
  "project_id": "fleet-tools",
  "name": "Fleet Tools",
  "slug": "fleet-tools",
  "path": "/local/path/to/fleet-tools",
  "project_type": "GAS",
  "visibility": "PUBLIC",
  "types": ["gas"],
  "resources": []
}
```

```bash
projectos --db DB discover contextos --projects-dir /path/to/projects \
  --machine-id work-mac --source-run-id scan-unique-id
projectos --db DB discover list --status CANDIDATE
projectos --db DB discover apply FINDING_UUID --actor owner@example.com
```

Scanning is non-mutating. Identical normalized findings deduplicate; changed content creates a new candidate version. Missing or malformed manifests become ERROR findings without aborting unrelated projects. Only `discover apply` writes canonical project, location, and resource records, in one transaction.

## Backup, verification, and restore

Create and verify a consistent SQLite snapshot:

```bash
projectos --db DB backup create /secure/local/backups
projectos --db DB backup verify /secure/local/backups/projectos-ID.manifest.json
```

The manifest records SHA-256, byte size, schema version, timestamp, and non-secret source identity. Creation uses SQLite's online backup API.

Restore is staged and fail-closed:

```bash
projectos --db DB backup restore MANIFEST_JSON /path/to/restored.db
projectos --db DB backup restore MANIFEST_JSON /path/to/existing.db --replace
```

Without `--replace`, an existing target is never changed. With `--replace`, ProjectOS verifies checksum, SQLite integrity, foreign keys, and schema in a temporary sibling before replacement. The previous target is moved to `TARGET.rollback-UUID`. Keep that rollback until the restored database passes `doctor` in its actual runtime location.

Restore refuses the currently open ProjectOS database and any target with `-wal` or `-shm` sidecars. Stop the process using that target and resolve its SQLite state before retrying; never delete active sidecars merely to bypass this gate.

## Phase 1 boundaries

Phase 1 intentionally excludes:

- Google Sheet schema, User Manifest enforcement, and GAS web UI;
- two-way conflict-aware Google synchronization;
- the two-hour `launchd` job;
- Context OS adoption, conditional skill installation, or live project scanning;
- Looker Git analysis and migration of the existing Sheet-based tracker.

These require separately reviewed plans and live-environment preflight. Do not point Phase 1 discovery at a live Context OS root as part of installation.
