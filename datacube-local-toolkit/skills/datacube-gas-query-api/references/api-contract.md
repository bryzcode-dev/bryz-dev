# GAS query API contract

## Request

| Field | Rule |
|---|---|
| `apiVersion` | Required and explicitly supported. |
| `dimensions` | Unique values from the contract allowlist. |
| `measures` | Unique values from the metric allowlist. |
| `filters` | Typed operators and values for allowlisted fields. |
| `dateRange` | Required start/end with bounded inclusive semantics. |
| `sort` | Allowlisted output field and `ASC` or `DESC`. |
| `page` | Positive limit and opaque or validated cursor. |

Reject unknown fields, duplicate selections, invalid types, excessive ranges,
and impossible combinations before query construction.

## Query construction

- Map logical fields to fixed SQL identifiers maintained by the application.
- Represent values with named BigQuery parameters.
- Apply the partition predicate directly to the partitioning field.
- Select explicit columns and aggregations; never use `SELECT *`.
- Apply deterministic ordering before pagination.
- Set maximum bytes billed and timeout in the job configuration.
- Poll asynchronous jobs with bounded retries and condition checks, not sleeps
  that can exceed the GAS execution budget.

## Response

The envelope always contains the same top-level fields. Business-empty results
return an empty `data` array without becoming an infrastructure error. Errors
use stable codes and safe messages; internal SQL, identifiers, tokens, and stack
traces do not cross the endpoint boundary.

## Local test seam

Keep these functions independent of GAS globals:

- request validation;
- logical-to-physical field mapping;
- query-plan construction;
- normalized cache-key creation;
- response-envelope creation.

Wrap `PropertiesService`, `CacheService`, session identity, and the BigQuery
Advanced Service behind adapters. Connected adapter tests remain `NOT RUN` in
the offline environment.
