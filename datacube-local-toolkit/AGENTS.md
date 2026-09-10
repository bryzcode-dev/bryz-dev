# DataCube local-only instructions

Apply only the smallest matching skill for the current phase:

- `datacube-design-contract` for grain, source mappings, schemas, measures, quality, freshness, and privacy decisions.
- `datacube-ingestion-build` for Drive CSV or Sheets adapters, fingerprints, state, staging, BigQuery models, idempotency, and publication.
- `datacube-gas-query-api` for Apps Script endpoints, query allowlists, parameters, caching, limits, and response contracts.
- `datacube-release-operations` for reconciliation, evidence gates, connected handoff, atomic promotion, observation, and rollback.

This repository is local-only. Read and write project files and run local deterministic tools; do not use network access, web browsing, MCP, package downloads, or credentials. Connected Google checks remain `NOT RUN` unless genuine connected-environment evidence was supplied as a file. Never infer production success from mocks or local fixtures.

Treat `shared/references/offline-environment-policy.md` as the evidence authority and `shared/references/architecture-principles.md` as the architecture baseline. Stop with `BLOCKED` when a required contract decision or artifact is absent.
