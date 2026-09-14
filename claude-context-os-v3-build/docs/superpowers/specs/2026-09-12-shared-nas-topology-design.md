# Claude Context OS Shared NAS Topology Design

## Purpose

Extend Claude Context OS V3.0.1 so the existing three-Mac NAS topology can be adopted without flattening, relocating, or silently preserving active configuration outside its live namespace. The Mac Mini M4 is the primary machine and must retain all existing shared and machine-specific behavior. The other two Macs may be reset and enrolled later from recoverable archives.

## Existing topology

The topology container is `/Volumes/BryzConfig/Claude`:

```text
/Volumes/BryzConfig/Claude/
├── shared/
│   ├── CLAUDE.md
│   ├── settings.json
│   ├── agents/
│   ├── plugins/
│   ├── reference/
│   └── skills/
└── machines/
    ├── mac-mini-m4/
    ├── bryans-macbook-pro/
    └── bryan-mac-neo/
```

Each machine exposes a native `~/.claude` facade. Shared entries link to `shared/`; volatile and machine-private entries link to the matching `machines/<machine-id>/` directory. The Mac Mini also contains local-only, non-symlink files and directories that must be preserved.

## Selected approach

Use a two-level transaction:

1. Migrate and atomically replace only the NAS `shared/` directory.
2. Enroll each machine's local `~/.claude` facade independently.

The whole NAS container is never replaced. Existing `machines/*` directories are never moved during shared adoption. This avoids snapshotting active machine histories, sessions, caches, and other volatile state as part of the shared transaction.

## Path roles

- Topology container: `/Volumes/BryzConfig/Claude`
- Authoritative V3 Claude root: `/Volumes/BryzConfig/Claude/shared`
- Primary machine store: `/Volumes/BryzConfig/Claude/machines/mac-mini-m4`
- Primary facade: `~/.claude` on the Mac Mini
- Local runtime template: `~/Library/Application Support/ClaudeContextOS/home`
- Secondary machine stores:
  - `/Volumes/BryzConfig/Claude/machines/bryans-macbook-pro`
  - `/Volumes/BryzConfig/Claude/machines/bryan-mac-neo`

The runtime template remains unexpanded in shared configuration and is expanded independently on each machine. SQLite, WAL files, hook events, offsets, locks, and transient logs must never be placed on the NAS.

## Topology model

The staged shared root contains `context-os/config/topology.json` with:

- layout identifier `shared-nas-v1`;
- container and shared-root paths;
- primary machine ID;
- known secondary machine IDs;
- the local facade path template;
- the local runtime path template; and
- expected shared and machine-specific facade link classes.

The general Context OS configuration identifies the logical Claude root as `shared/`, records network/removable authoritative storage, and uses the unexpanded local runtime template. Machine identity and runtime state are not stored in the shared SQLite database configuration.

Each enrolled Mac receives a local, non-symlink machine profile under its `~/.claude` facade. The profile records the machine ID, topology container, shared root, matching machine root, facade root, and resolved local runtime. Shared hook code reads this profile when present and otherwise uses safe local defaults.

## Shared migration

`adopt-shared` accepts the topology container, workspace, runtime template, primary machine ID, and primary facade. It performs no activation.

The operation:

1. Validates that `shared/` and all three known machine directories exist.
2. Validates the primary facade's current link targets against the container.
3. Inventories and snapshots only `shared/` using the V3.0.1 stable-boundary and symlink-preserving copy logic.
4. Records a read-only topology guard manifest for the container, machine directory names, and primary facade links.
5. Builds the V3 stage from the shared snapshot.
6. Merges the real shared `CLAUDE.md`, `settings.json`, agents, skills, plugins, reference material, and other supported content.
7. Places uncertain or colliding content in explicit review or preserved namespaces.
8. Scans for secret-like content and prevents promotion into rules, knowledge, reports, or indexes.
9. Produces a staged primary-machine enrollment plan without changing `~/.claude`.
10. Runs structural stage verification.

Unlike the current container-level attempt, `machines/` and `shared/` must never appear as wholesale `context-os/legacy-preserved` mappings.

## Semantic adoption

The source for global semantic review is `shared/CLAUDE.md`. Its sections are classified and reviewed using the existing governed adoption flow. The stage cannot report semantic review as `not_required` when the shared source contains a non-empty `CLAUDE.md`.

Existing instructions remain authoritative until deliberately merged. Uncertain content remains in review storage. The migration does not reinterpret machine histories, session logs, caches, or tool outputs as durable knowledge.

## Shared settings and hooks

Existing shared settings and non-V3 hooks are preserved. V3-managed hook entries are idempotently replaced by marker, without removing unrelated entries.

Shared hook commands use the portable facade path `$HOME/.claude/context-os/runtime/hooks/<hook>.py`. A hook must safely no-op with a diagnostic when a machine has not yet been enrolled or the facade link is unavailable. It must not fall back to a NAS runtime database.

The shared configuration stores `~/Library/Application Support/ClaudeContextOS/home` rather than an absolute `/Users/<name>/...` path. Hook and CLI runtime resolution expands this path on the executing machine.

## Primary Mac Mini enrollment

`enroll-machine` is dry-run by default. For `mac-mini-m4`, it inventories the local facade, classifies existing entries as shared links, machine links, or local-only paths, and creates a staged enrollment plan.

Apply mode may:

- add the `context-os` link to the shared V3 root;
- add other new V3 shared links that do not collide;
- create the local machine profile;
- create the local runtime directory; and
- update only V3-owned facade entries.

Apply mode must not replace an unexpected path. Existing local-only files, existing shared links, existing machine links, settings overrides, hooks, IDE state, telemetry, and MCP state remain in place unless a reviewed plan explicitly identifies a V3-owned change.

Before apply, the enrollment operation writes a local backup manifest and recoverable copies of every path it will modify. It also writes a rollback plan. No unrelated facade path is copied or removed.

## Secondary machine reset and enrollment

`reset-machine` applies only to `bryans-macbook-pro` or `bryan-mac-neo`; it refuses the primary machine ID.

The command is dry-run by default and requires an explicit apply flag. Apply mode:

1. Requires the matching Mac to run the command locally.
2. Verifies that its facade links point to the expected shared and machine roots.
3. Moves the existing machine directory to a timestamped archive on the NAS.
4. Moves only the facade entries selected by the reviewed reset plan to a local timestamped archive.
5. Creates a fresh machine directory and required native subdirectories.
6. Recreates shared and machine-specific facade links.
7. Creates a local machine profile and runtime.
8. Runs enrollment health checks.

The command never permanently deletes its archives. Permanent purge is outside this design and requires a separate explicit user action.

## Activation

`activate-shared` operates only on the shared root. It requires Claude Code to be closed on all three Macs.

Before activation it re-runs shared verification and confirms:

- stable verified backup;
- completed semantic review;
- valid merged settings;
- required V3 files and managed integrity manifest;
- preserved symlink types and targets;
- presence of all three machine directories;
- unchanged approved topology mapping;
- verified primary enrollment plan; and
- successful shared and primary-machine rollback probes.

Activation copies the shared stage to a sibling directory on `/Volumes/BryzConfig/Claude`, renames the current `shared/` to a timestamped rollback root, and renames the prepared stage to `shared/`. If the second rename fails, the old shared root is immediately restored. The topology container and all `machines/*` paths remain in place.

Mac Mini enrollment is applied immediately after shared activation. If enrollment or post-activation health fails, the machine enrollment is rolled back first and the shared root is then restored.

## Verification gates

`verify-shared` must prove:

- source and backup fingerprints match a frozen snapshot boundary;
- backup symlinks remain symlinks with identical targets;
- every shared top-level item is merged, preserved, or queued for review;
- no shared source item is mapped as though the container itself were a native Claude root;
- settings JSON parses and unrelated settings/hooks remain present;
- semantic review is complete when shared `CLAUDE.md` contains content;
- required V3 files exist;
- managed integrity verification passes;
- topology and machine-directory guards pass;
- primary facade link targets are recognized and preserved; and
- runtime configuration resolves outside the NAS.

Post-activation Mac Mini verification includes:

- `doctor` and managed integrity checks;
- local runtime and SQLite FTS5 initialization;
- knowledge add/search/rebuild;
- local hook-event write and ingestion;
- existing and V3 hook fixtures;
- existing skill, agent, plugin, project, and settings preservation checks;
- `/ea` context and investigation;
- governed task creation; and
- both shared and primary-machine rollback readiness.

## Rollback

Shared and machine rollback are independent transactions.

`rollback-shared` moves the active shared V3 root aside, restores the timestamped pre-V3 shared root, and verifies it against the frozen shared manifest. It never deletes the displaced V3 root.

`rollback-machine` restores only paths named by the machine enrollment manifest and verifies their type, target, and content. It does not replace the whole facade. Secondary reset rollback restores the archived machine directory and selected facade entries after moving the failed fresh state aside.

Rollback probes run against uniquely named temporary siblings on the same filesystem as their eventual targets. Probes are removed only after their expected restored and displaced contents are verified.

## Failure behavior

Every operation fails closed. Activation or enrollment is blocked when:

- a snapshot cannot stabilize;
- a required source, machine directory, or facade is absent;
- a facade link has an unknown target;
- a symlink becomes a regular file;
- settings or topology JSON is invalid;
- semantic review is pending;
- a runtime path resolves onto the NAS;
- a destination or rollback path already exists unexpectedly;
- a rollback probe fails; or
- verification evidence is missing or stale.

Errors identify the failing path and evidence file. Failed preparation leaves diagnostic artifacts in the migration workspace but does not modify the source. Failed activation restores the prior shared root before returning an error.

## Testing strategy

Automated tests use standard-library `unittest` and temporary directories. Required coverage includes:

- topology detection and rejection of ambiguous layouts;
- shared-root snapshot and mapping behavior;
- preservation of shared symlinks across filesystem semantics;
- non-modification of all `machines/*` paths during shared migration;
- semantic review of nested shared `CLAUDE.md`;
- portable per-machine runtime expansion;
- idempotent shared settings and V3 hook merge;
- primary facade inventory and enrollment planning;
- refusal to overwrite unexpected facade paths;
- primary machine apply and path-scoped rollback;
- refusal to reset the primary machine;
- secondary archival reset and rollback;
- activation failure restoration at both rename boundaries;
- post-activation doctor, FTS5, event ingestion, and EA behavior;
- local-only runtime audit; and
- an end-to-end synthetic three-machine NAS topology.

Focused tests run during implementation. The complete regression suite, compilation gate, JSON validation, local-only audit, same-filesystem NAS probes, and read-only real-topology comparison run once on the release candidate.

## Deployment sequence

1. Build and verify the topology-aware release without modifying the NAS root.
2. Run `adopt-shared` against `/Volumes/BryzConfig/Claude` without activation.
3. Review semantic migration and the Mac Mini enrollment plan.
4. Run `verify-shared` and both rollback probes.
5. Present exact activation and rollback commands with evidence.
6. Close Claude Code on all three Macs.
7. Activate the shared root.
8. Enroll the Mac Mini.
9. Run complete Mac Mini post-activation validation.
10. Retain all shared and machine rollback archives.
11. Later run the reviewed secondary reset/enrollment command locally on each secondary Mac.

## Completion criteria

The Mac Mini is complete only when the shared V3 root is active, its prior shared root and local enrollment backup remain recoverable, all existing primary-machine behavior passes verification, local runtime separation is proven, and `/ea` works through governed V3 APIs.

The multi-machine rollout is complete only when each secondary Mac has independently passed enrollment health and rollback checks. Secondary completion is not required to declare the primary Mac operational, but shared activation must remain safe for unenrolled secondary machines.
