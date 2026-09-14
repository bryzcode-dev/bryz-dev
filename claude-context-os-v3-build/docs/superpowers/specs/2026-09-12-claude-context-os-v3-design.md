# Claude Context OS V3 Design

## Goal

Build a portable, local-only context operating layer for Claude Code that preserves project continuity and cross-project knowledge while keeping runtime behavior deterministic, governed, recoverable, and independent of web memory services.

## Core requirements

- Existing Claude root migration must be staged, backed up, hash verified, semantically reviewed, collision-safe, and reversible.
- Claude root path is configurable and may be on a NAS.
- Hot runtime SQLite/event state is separately configurable and local by default.
- Authoritative project/knowledge/task data remains file-readable.
- SQLite/FTS5 is derived and rebuildable.
- Knowledge is temporal, provenance-aware, confidence-bearing, and supersedable.
- Projects expose resource/dependency relationships and persistent tasks.
- Context compilation is bounded.
- Managed files have drift/integrity detection.
- Secret-bearing material is excluded from memory promotion.
- Core runtime has no network-client dependency.
- Optional local tooling is modular and never required for correctness.
- Executive Assistant is manual/on-demand, personality-driven, and read-oriented; it is not the OS controller or normal coding worker.
- Home and work deployments share the platform but keep knowledge domains isolated.

## Executive Assistant

Claude Code exposes `/ea` as a user-only skill. It forks into a custom background subagent using a read-oriented tool set. The skill first obtains an authoritative local Context OS snapshot, then answers the user's request with a distinct EA voice. Confirmed preferences may be stored via an explicit Context OS operation; engineering knowledge uses the governed knowledge system instead.

## Storage

Authoritative root may be local or mounted. Runtime database/log queue defaults to a local platform-specific runtime path. Activation copies a verified stage onto the target filesystem before root renames, avoiding reliance on cross-device atomic rename.

## Recovery

Every real migration retains the old root. Derived state is rebuilt rather than treated as canonical. Managed-file drift is detectable with SHA-256. Self-management is deterministic and can be scheduled locally after manual validation.
