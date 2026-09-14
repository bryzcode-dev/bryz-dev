# V3 Self-Management

## Deterministic jobs

`contextctl maintain` is the base self-management operation. It ingests hook events, evaluates health, and repairs a missing derived SQLite index when allowed.

Additional explicit operations:

```bash
contextctl doctor
contextctl reindex
contextctl snapshot
contextctl conflicts
contextctl local-only-audit
contextctl tool-status
```

## macOS scheduling

`contextctl service-plist` generates a local LaunchAgent definition. Generation does not automatically load or enable the service. This preserves a human-controlled installation boundary.

Recommended progression:

1. validate manually
2. run `maintain` manually several times
3. generate LaunchAgent
4. inspect generated plist
5. load only after the environment is stable

## Recovery model

Derived-state failures should be repaired from source rather than patched in place.

- missing/corrupt SQLite -> quarantine/delete derived DB -> `reindex`
- stale hook queue -> ingest from recorded offset
- managed-file drift -> `doctor` reports SHA mismatch
- failed adoption activation -> source root restored immediately
- bad installed version -> retained pre-migration root is available for rollback

## Future-compatible workflow engine

V3 intentionally uses simple local state and SQLite rather than requiring a workflow server. If the system eventually needs durable multi-step orchestration beyond this scope, a local workflow engine can be added behind the same control APIs without changing the authoritative file model.
