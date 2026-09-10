# DataCube local-only instructions

Choose the narrowest applicable skill:

- `datacube-design-contract`: source contract, grain, mappings, keys, dimensions, measures, quality, freshness, and privacy.
- `datacube-ingestion-build`: Drive CSV and Sheet ingestion, source fingerprints, watchdog state, BigQuery layers, idempotency, and publication.
- `datacube-gas-query-api`: GAS endpoint, query and filter allowlists, parameters, cache scope, limits, and response envelope.
- `datacube-release-operations`: reconciliation, release evidence, connected handoff, atomic promotion, observation, and rollback.

Operate local-only: use repository files and deterministic local commands. Do not browse, call APIs or MCP, install packages, use credentials, or access Google services. Label connected Google checks `NOT RUN` unless an artifact contains genuine connected-environment evidence. A mock or fixture can prove local logic, not production behavior.

Follow `shared/references/offline-environment-policy.md`. Follow the ordered architecture in `shared/references/architecture-principles.md`. Return `BLOCKED` rather than silently inventing a required decision.
