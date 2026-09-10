# Contract fields

Use this reference when creating or reviewing a DataCube contract.

## Required top-level fields

| Field | Requirement |
|---|---|
| `contractVersion` | Semantic version for the contract shape and meaning. |
| `cube` | Stable cube name and one-sentence fact grain. |
| `sources` | Logical sources with kind and local representative sample. |
| `fields` | Unique canonical names, BigQuery-compatible types, and nullability. |
| `keys` | Primary and deduplication field lists referencing canonical fields. |
| `dimensions` | Named filtering/grouping interfaces referencing canonical fields. |
| `measures` | Named metrics with field and supported aggregation. |
| `qualityRules` | Stable rule IDs, expressions, and severities. |
| `freshness` | Positive maximum source-to-publish age in minutes. |

## Decisions that must be explicit

- Grain: what a single fact row represents.
- Source aliases: how raw headers map to canonical fields.
- Time: source timezone, business timezone, timestamp conversion, fiscal dates.
- Keys: collision, missing-key, correction, deletion, and replay behavior.
- Measures: unit, sign, precision, aggregation, null behavior, and tolerance.
- Dimensions: unknown-member behavior and slowly changing attributes.
- Quality: reject, quarantine, warn, or block thresholds.
- Privacy: classification, allowed consumers, retention, and masking.

## Supported validator aggregations

`SUM`, `COUNT`, `COUNT_DISTINCT`, `AVG`, `MIN`, and `MAX`.

More complex formulas belong in a separately versioned metric definition and
must name their required base measures.

## Evidence states

| State | Meaning |
|---|---|
| `PASS` | Local evidence satisfied the defined check. |
| `FAIL` | Local evidence contradicted the contract. |
| `NOT RUN` | The check requires a connected or unavailable environment. |
| `BLOCKED` | A required decision or artifact is missing. |
