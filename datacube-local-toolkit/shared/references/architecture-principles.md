# DataCube architecture principles

These principles adapt the reviewed watchdog architecture for Drive CSV and Google Sheets sources, a BigQuery processing layer, and Google Apps Script as the dashboard-facing facade.

1. **Contract before pipeline.** Define source identities, grain, mappings, keys, dimensions, measures, quality thresholds, freshness, and sensitivity before implementing ingestion.
2. **GAS orchestrates; BigQuery computes.** GAS discovers source changes, starts bounded jobs, exposes a small query API, and reports status. It does not parse the full cube during a dashboard request.
3. **Stable source identity.** Use Drive file IDs and Sheet ID plus tab or named-range identity. Names and timestamps alone are insufficient.
4. **Version every boundary.** Version source contracts, canonical schema, cube build, API envelope, and release manifest. Store those versions together in run evidence.
5. **Idempotent, locked runs.** Derive a run identity from contract version and source fingerprints. Acquire a lock before mutation and define stale-lock recovery.
6. **Layered storage.** Keep raw or externally referenced inputs, typed staging, canonical facts and dimensions, quarantine, quality results, aggregate marts, and publication metadata distinct.
7. **Quality gates publication.** Validate schema, row widths, required values, duplicates, accepted and rejected counts, and business-metric reconciliation before promotion.
8. **Atomic publish and rollback.** Build a new immutable cube beside the live one, then switch a stable view or version pointer. Preserve last-known-good.
9. **Thin, bounded query API.** Allowlist dimensions and measures, parameterize values, enforce date partitions and resource limits, scope caches by caller authorization, and return a versioned envelope.
10. **Evidence matches environment.** Local evidence never proves a connected Google operation. Use `PASS`, `FAIL`, `NOT RUN`, and `BLOCKED` literally.

The watchdog should be an event detector and state machine, not the place where analytical data is repeatedly assembled for every user interaction.
