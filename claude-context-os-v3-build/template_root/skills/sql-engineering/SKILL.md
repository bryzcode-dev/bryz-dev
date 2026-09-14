---
description: Use for SQL design, BigQuery, Teradata, warehouse queries, data models, joins, aggregations, DataCube sources, or query debugging.
---
# SQL Engineering

Establish intended output grain before writing or changing SQL. Verify actual source schemas and key data types; never invent columns. For every join, identify expected cardinality and how duplicates/nulls affect output grain. Prefer explicit columns over `SELECT *` in production logic.

For transformations, separate source normalization, business logic, aggregation, and presentation where practical. Before completion, validate representative row counts, uniqueness expectations, null behavior, date/time semantics, and any cast used to reconcile keys.
