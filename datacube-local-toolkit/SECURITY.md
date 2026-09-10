# Security policy

## Local-only execution

The included runtime scripts read only paths passed by the operator, use Node.js built-ins, and do not contain network clients. The skills prohibit web access, APIs, MCP, package installation, and credentials during offline work.

## Data handling

- Use redacted or synthetic fixtures. Do not commit customer records, personal data, credentials, tokens, service-account JSON, private keys, or Apps Script property values.
- Preserve source sensitivity classifications in the DataCube contract.
- Keep authorization checks in the GAS server layer and include caller scope in cache keys.
- Allowlist query dimensions, measures, filters, sorts, and groupings. Parameterize every user-controlled value.
- Grant the production service identity only the minimum Drive, Sheets, BigQuery, and deployment permissions needed.

## Before connected execution

Run a secret scan, review generated SQL and GAS changes, verify the intended GCP project and datasets, set query byte and row limits, and confirm the rollback target. Store resulting evidence without embedding credentials. A locally passing test does not prove IAM, deployment, quota, latency, or production-data behavior.

## Reporting a problem

Stop the release and mark the affected gate `BLOCKED`. Record the affected artifact and remediation without copying sensitive contents into logs or issue text.
