# ProjectOS Phase 4 Claude Implementation and Troubleshooting

Status: `SIMULATED`. This is the cross-platform handoff for Claude on the source machine. It may prepare files, run approved read-only collection, verify artifacts, explain failures, and return evidence. It must not invent paths, credentials, validation commands, ownership, or approval.

## Information the Owner must supply

- operating system: `macos` or `windows`;
- a generated source-machine ID containing no username or hostname;
- absolute Looker Git repository and separate evidence-output directories;
- expected Git remote, primary branch, and ownership context;
- master Sheet ID/URL and tracked tab names;
- GAS script ID, deployment IDs, and local source folder when present;
- local synchronization scripts and scheduler definition files;
- fixed validation commands, working directories, timeouts, expected exit codes, and parsers;
- credential provider, label, storage system, and non-secret lookup reference only;
- the verified ProjectOS wheel and its separately communicated SHA-256.

If any value is unknown, stop and ask. Do not search unrelated folders or infer a credential location.

## macOS collection

Use a standard-user terminal. Confirm `python3 --version` is 3.11 or newer. Create an isolated virtual environment outside the Looker repository, install the supplied wheel, and write `intake.json` with `host_family` set to `macos`. The output directory must already exist, must not be a link, must be outside the repository, and must contain no intended archive path yet.

```text
<venv-python> -m projectos.looker_host preflight --intake <intake.json>
<venv-python> -m projectos.looker_host collect --intake <intake.json> --archive <new-output>/projectos-looker-intake-v1.zip --wheel-sha256 <verified-wheel-sha256>
<venv-python> -m projectos.looker_host verify --archive <new-output>/projectos-looker-intake-v1.zip
```

Collection may inspect declared Git state and execute only the fixed validation arrays in the intake. It does not authenticate Google or change Git, Sheets, GAS, scripts, LaunchAgents, LaunchDaemons, or cron.

## Windows collection

Use a normal, non-elevated PowerShell session. Confirm `py -3 --version` is 3.11 or newer. Create an isolated environment outside the Looker repository, install the supplied wheel, and set `host_family` to `windows`. Use JSON strings for Windows paths; do not paste a PowerShell command string into a validation argument array.

```text
<venv-python.exe> -m projectos.looker_host preflight --intake <intake.json>
<venv-python.exe> -m projectos.looker_host collect --intake <intake.json> --archive <new-output>\projectos-looker-intake-v1.zip --wheel-sha256 <verified-wheel-sha256>
<venv-python.exe> -m projectos.looker_host verify --archive <new-output>\projectos-looker-intake-v1.zip
```

Collection does not enable, disable, run, edit, or remove Task Scheduler tasks, services, startup entries, scripts, or Google resources.

## Transfer and import

Return only the verified ZIP and communicate its SHA-256 separately. Do not return raw logs, source files, credential values, home paths, usernames, hostnames, personal email addresses, or native command output.

On the ProjectOS machine, copy the archive to a local staging directory and run database-free verify and preview before opening SQLite. Then use the explicit schema-3 database and protected Owner identity:

```text
projectos looker intake verify <archive.zip>
projectos looker intake preview <archive.zip>
projectos --db <projectos.sqlite> looker intake import <archive.zip> <project-id> --owner-email <protected-owner-email> --actor <protected-owner-email>
projectos --db <projectos.sqlite> looker analytics build <project-id> <intake-run-id> --owner-email <protected-owner-email> --actor <protected-owner-email>
```

Never edit the archive, migration table, imported rows, or evidence hashes to make verification pass.

## Reconciliation and refresh

Stage reconciliation against the preserved legacy snapshot and canonical policy. Resolve discrepancies by correcting source evidence and rebuilding, or by a reasoned protected-Owner waiver that creates a child report. Admin and User cannot waive.

A real Google refresh is a separate approval and must use the existing authenticated ProjectOS runtime. The returned receipt must bind the exact project, intake, Git revision, analytic version, ready reconciliation, Google binding, completed sync, active verified projection, and passing validation set. `SIMULATED` receipts are deliberately rejected by the real receipt verifier.

ContextOS exposes Looker status, assets, dependencies, findings, impact, and reconciliation only when both extension and SQLite are schema 3. These queries are immutable/read-only and cannot import, waive, refresh, cut over, execute SQL, resolve credentials, or accept role input.

## Cutover and rollback

Follow [Phase 4-D cutover and rollback](PHASE4D_CUTOVER_AND_ROLLBACK.md). Preparation does not authorize execution. The ordinary CLI produces only a `SIMULATED` package, and the host boundary rejects it. Claude must show the exact package hash, target IDs, expected ownership, and effect order before requesting a target-specific Owner approval. A separately authorized workflow issues an HMAC-authenticated `CutoverApproval` using a key held in protected OS credential storage; the key never enters the package, repository, journal, arguments, or Sheet. Never disable or remove legacy automation in the same step as preparation.

## Troubleshooting matrix

| Symptom | Safe response |
|---|---|
| Preflight rejects elevation | Reopen a normal-user shell; do not bypass the check. |
| Repository or output is a link/overlaps | Choose real, separate directories; do not copy through the link. |
| Validation command rejected | Compare it with the Owner-declared fixed array; do not add shell syntax. |
| Repository changed during collection | Preserve the journal, let the repository stabilize, and request approval to recollect. |
| Archive verification fails | Do not repair the ZIP; recollect from stable source state. |
| Import reports source-run conflict | Keep both artifacts and compare hashes/provenance; never force-rebind. |
| Analytics unavailable or mixed | Build from one intake and use its exact immutable version. |
| Reconciliation blocked | Review required differences; do not reinterpret or edit outcomes. |
| Simulated refresh rejected | Expected; obtain separately authorized real refresh evidence. |
| ContextOS Looker capabilities absent | Verify extension manifest and actual database are both schema 3. |
| Cutover ownership changed | Stop before effects and request a new target inspection/approval. |
| Cutover ownership changed after another target was disabled | Confirm the journal reached `ROLLED_BACK`; if rollback failed, preserve all evidence and use the exact-target recovery procedure. |
| `REAL cutover package is required for native execution` | The package is a simulation artifact. Do not relabel or edit it; use the separately authorized real-package workflow. |
| `legacy mapping is incomplete` | Supply verified explicit mappings for every tracked legacy item. Zero mappings and any unmatched or ambiguous mapping remain blocked. |
| Pending effect after interruption | Treat external state as unknown; reconstruct before recovery. |
| Rollback fails | Preserve package/journal/archive, stop, and request exact-target recovery approval. |

Forbidden troubleshooting includes force, purge, manual SQLite edits, role overrides, secret resolution, arbitrary SQL, changing support state, scheduler experiments, legacy deletion, authenticated push, or merge.
