# ProjectOS Phase 2 Verification

This file records the local release-candidate gates for the implementation ending at Phase 2. All examples and fixtures are invented. No Google account, Sheet, GAS deployment, Context OS installation, scheduler, Looker tracker, or other external system is contacted or changed.

## Acceptance gates

| Gate | Required evidence |
|---|---|
| Schema | Fresh schema 2, schema 1 migration without data loss, rollback on migration failure, newer-schema refusal |
| Identity | Single protected Owner; Admin/User versioning; inactive/unlisted/blank callers denied before query |
| Privacy | User/Admin receive PUBLIC safe DTOs only; PRIVATE absence is indistinguishable; searches/counts/graphs/connections do not leak |
| Requests | Field allowlists, secret rejection, UUID/hash tamper detection, immutable receipts, stale-version conflict, atomic mutation/audit |
| Sync | Local lock, preflight, failure at every gateway boundary, no double mutation, verified revision before checkpoint |
| Packaging | Python compile, offline dependency-free wheel, deterministic GAS output, clean diff |
| UI | Owner/Admin/User controls, fixture normalization, accessible landmarks/forms/focus/targets, desktop and narrow visual inspection |
| Diagnostics | Health and safe codes only; no emails, PRIVATE names/IDs/counts, rows, or secrets |

## Release commands

Run from the repository root with Python 3.11+:

```bash
/opt/homebrew/bin/python3 -m unittest discover -s tests -v
node --test gas/test/*.test.js
/opt/homebrew/bin/python3 -m compileall -q build_backend.py src tests
/opt/homebrew/bin/python3 -m pip wheel . --no-deps --no-build-isolation -w build/wheel-check
node gas/scripts/build.mjs --out build/gas-first
node gas/scripts/build.mjs --out build/gas-second
shasum -a 256 build/gas-first/* build/gas-second/*
git diff --check
```

The clean-room gate installs the newly built wheel into a temporary virtual environment, uses an isolated `PROJECTOS_HOME`, migrates a copied schema-1 database, creates the protected Owner/Admin/User and a disabled binding, plans the workbook, runs fake accepted/rejected/conflict/access and retry workflows, verifies revision/checkpoint behavior, creates and scans diagnostics, builds GAS twice, and renders every role fixture. The real gateway is patched to fail if instantiated.

## Results — 2026-09-26

- Python: `126` tests passed in the final release run; no failures, skips, or warnings.
- GAS/Node: `20` tests passed in the final release run; no failures or skips.
- Compilation: `compileall` exited `0` for `build_backend.py`, `src`, and `tests`.
- Wheel: offline, no-dependency, no-build-isolation build passed; `projectos-0.1.0-py3-none-any.whl` is `65,467` bytes with SHA-256 `5d04ac2f8875a55f737760c8100185a13c50e45a2b3b6591614bb82a9aa095f2`.
- GAS determinism: two independent builds were byte-identical. SHA-256 values were `f200e454...b5531` (`Code.gs`), `4312765e...ad94e` (`index.html`), `da04b2b9...70192` (`styles.html`), and `4c660eaa...e8f51` (`app.html`).
- Static checks: `git diff --check` and directory comparison exited `0`.
- UI visual gate: Owner/Admin/User at desktop width, Owner at `390×844`, and the modal edit/focus state were inspected. Owner had administration and PRIVATE data; Admin had PUBLIC edit without administration; User had PUBLIC read-only. The correction review added executable Owner Users/Conflicts/Audit/Settings panels and role-safe locations/resources/deployments, then visually verified the populated Users route. Non-Owners do not receive the Owner-only visibility option.
- Clean room: the built wheel was installed into a new temporary virtual environment; a copied schema-1 database migrated to schema `2`; `13` CLI responses each remained one JSON envelope; Owner/Admin/User plus a disabled binding were created; a 14-action empty-workbook plan remained non-blocking; one accepted, one authorization-rejected, one conflict, and one access event were processed; an injected post-commit publication failure retried with no duplicate mutation; checkpoint `4` and a verified active revision were reached; diagnostics scanned clean; GAS built twice identically; all three fixture role pages rendered; final doctor was healthy; the real gateway was not instantiated.
- Coordination: `0` implementation subagents were used. One UI correction round closed the final review findings. The complete Python and GAS suites ran once for the initial release candidate and once after that correction; Task 12 also ran its regression gate before commit.
- External state: no Google authentication, network gateway, Sheet, GAS deployment, Context OS installation, scheduler, Looker tracker, or production database was read or changed.

Implementation commits, in order: `335d6a3`, `45e7ac4`, `5293e11`, `2030c04`, `56f7117`, `85caad8`, `40d10cf`, `19ca399`, `585a3ad`, `7b5349c`, `3533394`, and `b639b80`; the final documentation commit closes the phase.

## Known activation limitations

- The real Google gateway performs no network work on construction and enforces configuration/CLI gates, but live read/publication mapping is deliberately unavailable until a separately authorized staging implementation.
- GAS source and deterministic build output are complete; no Apps Script project or deployment has been created.
- The two-hour sync schedule and skill-triggered immediate sync are specified but not installed.
- ProjectOS adoption into Context OS and the ProjectOS-only Context OS skill are not installed.
- Existing Looker Git/Sheet migration and analytics are not inspected or cut over.
