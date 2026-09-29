# ProjectOS Phase 3B Verification

Phase 3C now consumes this completed disabled-definition candidate. See `PHASE3C_VERIFICATION.md` for scheduler rendering, skill discovery, runtime activation, and the newer wheel evidence. Phase 3B remains the authority for definition transaction and recovery behavior.

This record covers the fixture-only transaction engine. macOS and Windows transaction semantics are portable code and simulation evidence only. No real ContextOS installation, native scheduler, skill discovery path, external service, or production database was activated.

## Candidate gates

| Gate | Evidence required |
|---|---|
| Fixture authority | new/empty root, canonical marker, local receipt, explicit acknowledgement, no overlap or symlink bypass |
| Registry | unrelated semantic values preserved, disabled ProjectOS entry only, exact-byte rollback |
| Persistence | canonical local profile/journal, verified snapshot hashes, exclusive transaction IDs |
| Staging | exact verified ZIP bytes, compatibility checks, portable regular files, immutable version copy |
| Transactions | ordered adoption, upgrade, rollback, uninstall, seven injected crash boundaries, idempotent recovery |
| CLI | fixture-only namespace, database-free dispatch, one redacted JSON envelope, no live or force route |
| Wheel | all Phase 3B modules, byte-identical builds, extracted-wheel adopt/rollback, identifier and secret scan |

## Results — 2026-09-27

- Code/artifact source revision: `72bb1ac` (the following evidence documentation commit does not alter the wheel payload).
- Host evidence: macOS local fixture verification; Windows path/host behavior simulated only.
- Python/platform: Python 3.14.7 on macOS 27.2 arm64.
- Candidate tests: `92/92` focused and affected-regression tests passed.
- Compilation: `python -m compileall -q src build_backend.py` exited `0`.
- Wheel: `projectos-0.1.0-py3-none-any.whl`, 97,904 bytes, 53 members, SHA-256 `2ead021e118679f2b9511f7635718b370903f65cdf4df6ae3ddd128aac53c88a`.
- Determinism and clean room: repeated direct backend builds were byte-identical; the extracted wheel completed a fixture adopt and exact rollback.
- Failure injection: all seven named adoption boundaries recovered to `ROLLED_BACK`; repeated recovery remained idempotent. An interrupted multi-version uninstall also restored every hash-verified archived version before restoring the exact registry snapshot.
- Scans: `0` build/target identifier, private-key, high-confidence token, or symlink findings across the wheel and selected fixture journals, snapshots, staged files, and archives.
- External state: no live ContextOS, scheduler, skill discovery, Google, GAS, Looker, shared-root, or production SQLite state changed.

## Implementation rulings

1. A pure host-path separation helper makes drive-letter and UNC containment testable without granting live-target access.
2. Registry v1 reserves the case-insensitive `projectos` namespace and requires `enabled:false`.
3. One managed-path inventory primitive drives snapshots, archives, rollback, uninstall, and recovery ownership checks.
4. Bundle verification and extraction use the same in-memory ZIP bytes to close the path time-of-check/time-of-use gap.
5. Persisted journal, snapshot, and staged-manifest loaders revalidate every reconstructed recovery input.
6. Transaction directories are exclusively reserved before the first journal write; identifiers cannot replace existing recovery state.
7. Recovery is idempotent after rollback. Adopt cannot replace an existing entry, and upgrade cannot run without one.
8. The CLI generates transaction UUIDs and accepts identifiers only for rollback and recovery.
9. Unexpected execution failures use the existing redacted operational envelope and exit `3`; validation remains exit `2`.
10. The wheel backend already includes every regular `.py` adoption module by deterministic source traversal, so no backend inclusion rule required expansion.
11. The single correction round added archive-backed uninstall recovery after controller review proved that a crash between multi-version removals could otherwise restore a registry entry before all referenced versions were present.

## Deferred boundaries

- Phase 3C delivers conditional skill discovery, the common locked sync command, deterministic `launchd` and Task Scheduler definitions, two-hour scheduling contracts, and fixture activation behavior.
- Phase 3D owns deterministic release handoff, clean macOS acceptance, returned real-Windows evidence, and final cross-platform reconciliation.
- Real Google/Sheets/GAS work, Looker Git migration, and production SQLite migration remain separately authorized later phases.
- No live adoption is authorized by this candidate.
