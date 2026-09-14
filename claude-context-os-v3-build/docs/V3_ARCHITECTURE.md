# Context OS V3 Architecture

## Principle

**AI may reason about Context OS, but deterministic components control Context OS.**

The authoritative system remains understandable and recoverable without a particular model, embedding engine, MCP server, or cloud service.

## Planes

### Control plane

- `contextctl.py`
- migrations and upgrades
- deterministic policy evaluation
- integrity manifest
- health/doctor/maintenance
- snapshots and rollback
- event ingestion
- schema/index rebuilds

### Knowledge plane

Authoritative JSON/Markdown plus rebuildable SQLite/FTS5 indexes.

Knowledge records support:

- type/title/summary
- project/domain/tags
- status (`candidate`, `active`, `superseded`, archived by future migration)
- verified flag and confidence
- created/verified/last-used/last-verified dates
- validity range and `superseded_by`
- provenance and evidence
- applicability metadata

### Project plane

- project registry
- resource relationships
- project dependencies
- task ledger
- project brain compilation
- impact analysis

### Runtime plane

High-frequency mutable state lives in a configured local runtime directory:

- SQLite database
- FTS5 index
- hook event queue
- offsets/checkpoints
- locks/transient logs

This is particularly important when the Claude root is NAS-mounted.

### Interface plane

- Claude Code global/project instructions
- Skills
- hook events
- CLI
- custom Executive Assistant subagent
- future optional local MCP gateway

## Context flow

```text
User task
   |
   v
project identity --> task state --> policy --> knowledge retrieval
                                      |
                                      v
                              bounded compiler
                                      |
                                      v
                             worker context pack
```

The archive is never intended to be loaded wholesale.

## Self-management

V3 self-management is deterministic by default:

1. hooks append minimal local events
2. maintenance ingests events
3. doctor checks managed integrity/runtime/security hints
4. missing derived indexes can be rebuilt from authoritative files
5. snapshots are created deliberately or by an approved local scheduler
6. failures retain original/source state and expose rollback paths

The EA can explain and investigate this state but is not the process that keeps it alive.

## Executive Assistant separation

```text
User -> /ea -> forked EA subagent -> V3 read/query APIs
User -> coding request -> Claude worker -> V3 context/query APIs
```

Both consult the same OS. Neither owns the OS.
