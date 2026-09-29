# ProjectOS Portable Handover

ProjectOS is a local-first project catalog, deployment registry, connection map, and database-management enhancement for ContextOS. It gives ContextOS a structured way to locate projects, understand their dependencies, track where credentials are referenced, and coordinate editable project information through Google Sheets and a Google Apps Script (GAS) web application.

This folder is a portable, verified handover package for installation and staged rollout on another macOS or Windows computer. Start with this file, then give `CLAUDE_HANDOVER.md` to Claude on the destination machine.

## Core authority model

SQLite is the single source of truth (SSOT). Google Sheets and the GAS web application are controlled collaboration surfaces:

```text
ContextOS / local tools
          |
          v
  ProjectOS SQLite SSOT
          |
     guarded sync
          |
          v
Google Sheet contract <-> GAS web application
```

Sheet edits become immutable requests. ProjectOS validates identity, role, entity, operation, allowed fields, and base version before applying a transaction to SQLite. It then publishes a verified projection back to Sheets. Failed publication can be retried without applying the SQLite mutation twice.

## What ProjectOS manages

- Project identity, type, lifecycle status, visibility, tags, and notes.
- ContextOS registration and discovery provenance.
- macOS and Windows project-folder locations.
- Google Drive folder IDs and URLs.
- Google master Sheet and supporting Sheet IDs/URLs.
- GAS script IDs plus development and production deployment IDs/URLs.
- External connections such as direct GCP, GAS-mediated loads, Sheet integrations, Looker, APIs, databases, and automation.
- Credential references and usage maps without storing secret values.
- Deployment environments and connection impact queries.
- Looker Git repository intake, model/view relationships, code and Git status, findings, legacy-tracker reconciliation, refresh evidence, and reversible cutover preparation.
- ContextOS extension adoption, ProjectOS skill activation, and a two-hour scheduler definition through staged, reversible workflows.

## Authorization and visibility

| Role | Project visibility | Editing | Administration |
|---|---|---|---|
| Owner | PUBLIC and PRIVATE | Full approved project fields | Only role that can change users, view the admin menu, resolve conflicts, and perform protected operations |
| Admin | PUBLIC only | Allowlisted PUBLIC project fields | No admin menu and no user management |
| User | PUBLIC only | View only | No admin menu |

`PRIVATE` projects are visible only to the protected Owner. Authorization is enforced in Python and GAS before serialization. The browser UI cannot elevate a role.

## Package contents

```text
ProjectOS/
  README.md                 This overview and operator entry point
  CLAUDE_HANDOVER.md        Destination-machine instructions for Claude
  PACKAGE_MANIFEST.json     Source revision, build, scope, and verification metadata
  MANIFEST_SHA256.txt       SHA-256 integrity manifest for every other file
  SOURCE/                   Portable source, tests, GAS app, schemas, and technical docs
  ARTIFACTS/
    python/                 Fresh universal Python wheel
    gas/                    Deterministic GAS deployment files
```

The package intentionally excludes Git metadata, virtual environments, build caches, `.DS_Store`, populated configuration, credentials, secrets, live SQLite databases, locks, journals, receipts, backups, and machine-specific runtime state.

## Requirements

- macOS or Windows.
- Python 3.11 or newer. Do not use Apple Command Line Tools Python 3.9.
- Node.js only when rebuilding or testing the GAS application.
- A compatible ContextOS installation for adoption. Its extension contract must be version `1`, ContextOS must be `>=3.0.1,<4.0.0`, and the target host must be declared supported.
- Google authentication and a target Sheet only for a separately approved live Google stage.

ProjectOS itself has no required third-party Python runtime dependencies. Live Google support uses the optional `google` dependency set.

## Verify this package first

On macOS or Linux:

```bash
cd /path/to/ProjectOS
shasum -a 256 -c MANIFEST_SHA256.txt
```

On Windows PowerShell:

```powershell
Set-Location 'C:\path\to\ProjectOS'
Get-Content .\MANIFEST_SHA256.txt | ForEach-Object {
  $hash, $relative = $_ -split '  ', 2
  $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $relative).Hash.ToLowerInvariant()
  if ($actual -ne $hash) { throw "Hash mismatch: $relative" }
}
```

Stop if any hash fails. Do not repair a transferred artifact in place; copy the package again from the trusted source.

## Safe local installation

Create an isolated virtual environment outside any ContextOS shared root and install the supplied wheel.

macOS:

```bash
PROJECTOS_PYTHON=/absolute/path/to/python3.11-or-newer
"$PROJECTOS_PYTHON" --version
"$PROJECTOS_PYTHON" -m venv "$HOME/.projectos-venv"
"$HOME/.projectos-venv/bin/python" -m pip install ARTIFACTS/python/projectos-0.1.0-py3-none-any.whl
"$HOME/.projectos-venv/bin/projectos" --help
```

Replace `PROJECTOS_PYTHON` with the verified interpreter on that Mac; the placeholder is intentionally not executable as written.

Windows PowerShell:

```powershell
py -3 --version
py -3 -m venv "$env:LOCALAPPDATA\ProjectOS\venv"
& "$env:LOCALAPPDATA\ProjectOS\venv\Scripts\python.exe" -m pip install .\ARTIFACTS\python\projectos-0.1.0-py3-none-any.whl
& "$env:LOCALAPPDATA\ProjectOS\venv\Scripts\projectos.exe" --help
```

This only installs the CLI. It does not create a live database, modify ContextOS, authenticate Google, deploy GAS, or install a scheduler.

## Safe local verification from source

macOS:

```bash
cd SOURCE
"$PROJECTOS_PYTHON" -m unittest discover -s tests -p 'test_*.py'
node --test gas/test/*.test.js
node gas/scripts/build.mjs --out /tmp/projectos-gas-dist
```

Windows PowerShell:

```powershell
Set-Location .\SOURCE
py -3 -m unittest discover -s tests -p 'test_*.py'
node --test gas/test/*.test.js
node gas/scripts/build.mjs --out "$env:TEMP\projectos-gas-dist"
```

Expected test totals for this package are recorded in `PACKAGE_MANIFEST.json`.

## Staged onboarding sequence

1. Verify `MANIFEST_SHA256.txt` and read `CLAUDE_HANDOVER.md`.
2. Confirm Python, Node, operating system, and the exact ContextOS root.
3. Run the complete local tests from `SOURCE/`.
4. Install the wheel into an isolated target-local virtual environment.
5. Run database-free ContextOS adoption inspection and profile planning.
6. Create a new local ProjectOS runtime location outside ContextOS and shared storage.
7. Initialize a new SQLite database and seed the one protected Owner.
8. Import or create project records using non-secret identifiers and references.
9. Exercise Google behavior with the fake gateway and fixture workbook only.
10. Stage and verify the ContextOS extension bundle, skill, and disabled scheduler definitions.
11. Obtain separate Owner approval before each live boundary: ContextOS adoption, native scheduler activation, Google read access, Google writes, GAS deployment, Looker source collection, legacy reconciliation, or cutover.

The detailed phase runbooks are under `SOURCE/docs/`. Begin with:

- `PHASE1_OPERATIONS.md` and `PHASE1_SCHEMA.md` for the local catalog.
- `PHASE2_OPERATIONS.md` and `PHASE2_SCHEMA.md` for Sheets/GAS and synchronization.
- `PHASE3_CONTEXTOS_EXTENSION_CONTRACT.md` plus the Phase 3 operations guides for ContextOS adoption and schedulers.
- `PHASE4A_SOURCE_COLLECTION.md` through `PHASE4D_CUTOVER_AND_ROLLBACK.md` for Looker migration.

## GAS web application

`ARTIFACTS/gas/` contains deterministic `Code.gs`, `index.html`, `styles.html`, and `app.html` build output plus the reviewed `appsscript.json` project manifest. The source remains under `SOURCE/gas/`.

The package does not contain a Google Sheet, Apps Script project, script ID, deployment ID, OAuth token, or credentials. Claude must inventory the destination environment and request the exact target identifiers before preparing a live deployment. Fixture preview role parameters are test-only; a deployed GAS application resolves identity server-side.

## ContextOS relationship

ProjectOS is developed as a separate project but adopted as a ContextOS enhancement. ContextOS remains the orchestrator. A valid adoption installs a versioned extension manifest and the ProjectOS skill, while ProjectOS retains its own local runtime and SQLite SSOT. The skill may request an immediate sync; the scheduler is designed for a two-hour cadence. Both routes use the same guarded runtime entry point and lock.

Do not place the SQLite database, lock, logs, configuration, staging directory, or credentials inside a ContextOS shared root. Machine-local data stays machine-local.

## Safety boundaries

This handover is a local package, not authorization for external changes. It does not authorize:

- modifying a live ContextOS installation;
- installing or enabling `launchd` or Windows Task Scheduler entries;
- authenticating Google or creating/modifying a Sheet;
- deploying GAS;
- inspecting undeclared folders or credential stores;
- running a real Looker migration or disabling a legacy tracker;
- pushing or merging Git changes.

Use staged, fail-closed workflows. Preserve backups and rollback evidence. Never store secret values in SQLite or Sheets; store only non-secret credential references.

## Current release status

Version: `0.1.0`  
Database schema: `3`  
Supported hosts: macOS and Windows  
Release posture: local release candidate; automated host evidence is `SIMULATED` until separately authorized runs occur on the destination host.
