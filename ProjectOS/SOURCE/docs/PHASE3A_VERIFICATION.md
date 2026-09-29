# ProjectOS Phase 3A Verification

This record covers the cross-platform contract and portable staging candidate only. macOS execution is local evidence; Windows behavior is simulated with Windows path and host abstractions and remains unsupported as real-host evidence until the Windows handoff gate is returned.

## Candidate gates

| Gate | Evidence required |
|---|---|
| Paths | macOS defaults, Windows `%LOCALAPPDATA%`, overrides, drive/UNC normalization, component-aware containment |
| Locks | lazy native imports, POSIX contention/release, simulated Windows byte locking and error mapping |
| ContextOS | read-only discovery, exact contract compatibility, host support, safe relative roots, machine identity |
| Profile | deterministic planned identity, local runtime separation, correct scheduler kind, no persistence |
| Bundle | strict manifest, deterministic ZIP, hashes, portable names, no symlinks, secrets, or host identifiers |
| CLI | one JSON envelope, database-free adoption commands, atomic requested output only, redacted failures |
| Wheel | all adoption modules, identical repeated builds, `py3-none-any`, clean import without `fcntl` |

## Results — 2026-09-27

- Code/artifact source revision: `47d8299` (the following evidence-only documentation commit does not alter the wheel payload).
- Host evidence: macOS 27.2 (build 26B5091g) local verification; Windows simulation only.
- Python: 3.14.7; `76/76` focused and affected-regression tests passed.
- Compilation: `python -m compileall -q src build_backend.py` exited `0`.
- Wheel: dependency-free `projectos-0.1.0-py3-none-any.whl`, 79,964 bytes, 48 members, SHA-256 `64eb2d8316bf432bd4be728c1cf52331fa3c63859034d6ee044bab1fce4ade3d`.
- Determinism/import: two direct backend builds were byte-identical; the extracted wheel imported with `fcntl` blocked and attempted the import only when the POSIX backend was selected.
- Identifier and secret scan: `0` build-home, repository-root, username, hostname, configured shared-root, private-key, or high-confidence token matches across wheel members. The source also rejects wheel-source symlinks.
- External state: no live ContextOS, scheduler, Google, GAS, Looker, shared-root, or production SQLite state is permitted to change in this gate.

## Remaining evidence

The real-Windows gate in `PHASE3_WINDOWS_IMPLEMENTATION_AND_TROUBLESHOOTING.md` is mandatory before Windows can be reported as real-host verified. Phase 3B now owns the completed fixture-only disabled-definition transaction engine, including upgrade, rollback, recovery, and uninstall. Phase 3C owns conditional skill discovery, scheduler rendering/installation, and common sync activation. Phase 3D owns clean-host acceptance and real-host reconciliation. None begins automatically after its preceding candidate passes.
