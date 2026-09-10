# Pipeline invariants

## Source identity

| Source | Stable identity | Local substitute |
|---|---|---|
| Drive CSV | File ID plus approved revision signals | Contract source ID plus sample hash |
| Google Sheet | Spreadsheet ID, tab ID/name, and bounded range | Contract source ID plus exported fixture hash |

Do not discover production sources by filename. Record which fingerprint inputs
are unavailable offline instead of inventing them.

## Layers

| Layer | Purpose | Mutation rule |
|---|---|---|
| Raw staging | Preserve source values and provenance | Append or replace per run ID |
| Typed staging | Parse and quarantine invalid values | Never silently coerce failures |
| Canonical facts/dimensions | Enforce grain, keys, and history policy | Idempotent merge or versioned rebuild |
| Quality results | Store counts, thresholds, and evidence | Immutable per run |
| Aggregate mart | Serve approved dimensions and measures | Build beside live version |
| Stable interface | Point readers to one approved version | Atomic promotion only |

## Required run manifest

- run ID and status;
- contract version;
- source IDs and fingerprints;
- detected, accepted, rejected, inserted, updated, and deleted counts;
- duplicate counts and key policy;
- every quality result and threshold;
- staged, canonical, mart, live, and rollback identities;
- start, finish, publication, and failure timestamps;
- error category and resumability decision.

## Failure behavior

- Lock unavailable: exit without mutation.
- Source changed during read: fail and retry as a new run.
- Schema drift: quarantine or block according to the contract.
- Quality failure: retain evidence, do not promote.
- Publication failure: keep the prior stable pointer.
- Retry: resume only when completed steps are proven idempotent.

## Offline evidence limit

Local fixtures can prove parser, mapping, aggregation, and state-transition
behavior. They cannot prove Drive permissions, Sheet export behavior, BigQuery
SQL validity, quotas, IAM, scanned bytes, GAS triggers, or production latency.
