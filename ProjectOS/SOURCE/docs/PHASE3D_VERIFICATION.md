# ProjectOS Phase 3D Verification

Status: `SIMULATED`. Phase 3D-B now implements the guarded host runner, recovery, and evidence sealing. Automated verification executes no native scheduler or external service. See `PHASE3D_B_VERIFICATION.md` for the current candidate.

## Gates

| Gate | Required evidence |
|---|---|
| Package | deterministic seven-member schema-2 archive, canonical manifest, wheel/extension/source hashes, no links or private data |
| Authority | new empty root, same-host receipt, standard-user session, separated local runtime |
| Probe | receipt-bound fake gateway, common coordinator and lock, bounded events and barrier |
| Equivalence | only task identifier and entrypoint module differ from production definition |
| Native runners | fixed argument arrays through recording executors, ownership hash, strict inspection parsing |
| Transaction | exact journal order, reverse recovery, discovery disabled before scheduler teardown |
| Evidence | native-only required cases, canonical allowlist, deterministic archive, release-bound verification |
| Reconciliation | zero, one, or two matching host records map to the exact support state |
| Installed wheel | package, simulated lifecycle, evidence, and reconciliation work without the source checkout |

## Authorization still required

- One explicit authorization for a clean standard-user macOS Phase 3D-B run.
- A separate explicit authorization for a clean standard-user Windows Phase 3D-B run.

No platform is verified by this document.

## Release-candidate evidence

- Source revision: `0e2172038699d9212e58cd46dba1486569b74531`
- Build host: macOS arm64; Python `3.14.7`
- Complete Python regression: `427` passed
- GAS regression: `20` passed
- Python compilation: exit `0`
- Affected Phase 3D-B regression: `192` passed
- Focused Task 1-7 gates: `47`, `34`, `36`, `44`, `47`, `28`, and `19` passed
- Failure-injection boundaries: `16`
- Recording-executor lifecycle actions: `15` (`8` macOS and `7` Windows)
- Candidate/full-suite executions: `3`; the first output was truncated, the second exposed a self-review evidence-provenance finding, and the third verified the corrected candidate
- Automatic correction rounds: `1`
- Agent runs: `0`

## Deterministic artifacts

| Artifact | Size | Members | SHA-256 |
|---|---:|---:|---|
| `projectos-0.1.0-py3-none-any.whl` | 175265 bytes | 88 | `5c3618088148518bba149aa20b99055c68b579d41c2c59af3e393e19601a3e02` |
| `projectos-extension.zip` | 169790 bytes | 3 | `a674d53a0fd859c7b7c42cdd46763ce24b15b91bb14e2d30396ba4f36787d79a` |
| `projectos-phase3d-b-acceptance.zip` | 342994 bytes | 7 | `fd13703082474891e4495f1f49da00c5103be1e334bc4db3dbac1eebb06bce85` |
| `projectos-simulated-native-shaped-evidence.zip` | 1534 bytes | 2 | `70eb637459095e00d49bcb7cabcf84ced361410b5fc52bbe65ca210937833c58` |
| `projectos-reconciliation.json` | 386 bytes | 1 | `d8350a45bbbf064c26ac53ca646c2b5c90d1600facaf9507e839d94d5e1e94ed` |

All archives passed canonical inventory, member hash, case-insensitive duplicate, traversal, regular-file, and symlink checks. All contain zero symlinks. The simulated evidence verified structurally but was not accepted into reconciliation.

## Safety and implementation rulings

- Package, authority, probe, structural equivalence, native recording, transaction recovery, evidence, reconciliation, and installed-wheel gates passed.
- Portable artifacts and invented acceptance state passed identifier, secret, absolute-path, external-identifier, command-output, and credential-material rejection tests.
- Native runners use fixed argument arrays and `shell=False`; no shell-based scheduler execution path exists.
- All lifecycle tests used recording executors. No `launchctl` or `schtasks.exe` command was executed.
- The acceptance probe uses the in-memory fake gateway. No network or real Google call was made.
- `acceptance_host preflight` is read-only. `run` and `recover` are implemented but must not be invoked without separate authorization for the exact host.
- No live ContextOS, shared root, native scheduler, Google, GAS, Looker, or production SQLite state changed.

Reconciliation remains `SIMULATED`. macOS Phase 3D-B and Windows Phase 3D-B each require a separate explicit Owner authorization and clean standard-user host run.
