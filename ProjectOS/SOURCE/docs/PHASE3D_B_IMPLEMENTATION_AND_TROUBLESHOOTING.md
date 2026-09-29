# ProjectOS Phase 3D-B Implementation and Troubleshooting Handoff

Status: `SIMULATED`. This is the implementation handoff for Claude or another operator. It does not authorize a native host run.

## Architecture to preserve

The schema-2 acceptance ZIP binds the wheel and `projectos-extension.zip`. `prepare` creates one local authority, stages that verified bundle, and persists the acceptance profile and preparation record. The host factory reopens those facts, verifies structural equivalence and the disposable database, and only then constructs a native executor. Definition adoption and runtime activation delegate to the existing Phase 3B/3C transactions. Native proof accepts only events bound to the current receipt, release, definition, run, case, and trigger-window sequence. The collector seals only allowlisted typed facts.

SQLite remains the ProjectOS SSOT. The acceptance database and Google configuration must be disposable and use invented identifiers. The fake gateway is used for fixture activation proof; no real Google, GAS, Looker, or credential operation belongs in acceptance.

## Durable local state

Inspect, but do not hand-edit or delete:

- `acceptance/state/preparation.json` and `acceptance-profile.json`;
- `acceptance/state/runs/<run-id>/journal.json`;
- `acceptance/staging/projectos-extension.zip`;
- `acceptance/trigger-windows/*.json` and `evidence-spool/probe-events.jsonl`;
- `adoption/transactions/<definition-id>` and `adoption/activations/<activation-id>`;
- fixture registry and version inventory;
- platform-specific ownership records below `acceptance/native`.

All records are canonical and hash-bound. A copied receipt, changed package, changed registry inventory, mismatched definition, foreign task, noncanonical event, or reused identifier must stop recovery without deletion.

## Command flow

Use the exact roots and acknowledgements documented in `PHASE3D_HOST_OPERATIONS.md`: `prepare` once, `preflight` as often as needed, `run` only after separate authorization for that host, and `recover --run-id` for the exact emitted run ID. The ordinary `projectos` CLI intentionally has no host-run command.

The JSON exit contract is: `0` sealed, `3` incomplete or recovered, `2` validation failure, and `1` unexpected internal failure. Messages are redacted. Troubleshoot from the bounded code plus durable local state; never add force, purge, arbitrary task, production-root, shell, or live-Google options.

## Platform differences

- macOS uses a per-user LaunchAgent service in `gui/<uid>`, rejects root/elevation, and triggers with one fixed `launchctl kickstart` array.
- Windows uses an interactive, least-privilege current-user task with `IgnoreNew`, rejects elevation, and triggers with one fixed `schtasks.exe /Run /TN` array.
- Both stage disabled, verify hash ownership before every trigger or cleanup, disable discovery before scheduler teardown, and retain the database and diagnostics.

## Failure handling

- Before a run ID exists: correct only the supplied input that failed validation and rerun preflight.
- After a run ID exists: run recovery with the unchanged inputs. Recovery reconstructs ownership from journals; it does not trust process memory.
- Foreign task, registry change, extension inventory change, release drift, or definition hash mismatch: preserve everything and stop. Do not retry with force.
- Probe timeout, duplicate, stale, foreign, or reordered event: recover. Keep trigger windows and the failed spool local for diagnosis.
- Evidence verification failure: retain the local sealed archive and inputs; rebuild nothing until the exact manifest, bundle, preparation, or attachment mismatch is understood.

## Update rule

Future changes must keep the repository and packaged host-operation documents byte-identical, keep `SIMULATED` until separately authorized native evidence is accepted, add a failing test before implementation, and verify installed-wheel behavior without the source checkout. A new schema or native effect requires a new reviewed spec; do not silently make old evidence executable.
