#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const allowedTypes = new Set([
  'STRING', 'BYTES', 'INTEGER', 'INT64', 'FLOAT', 'FLOAT64', 'NUMERIC',
  'BIGNUMERIC', 'BOOLEAN', 'BOOL', 'DATE', 'DATETIME', 'TIME', 'TIMESTAMP',
  'GEOGRAPHY', 'JSON',
]);
const allowedAggregations = new Set([
  'SUM', 'COUNT', 'COUNT_DISTINCT', 'AVG', 'MIN', 'MAX',
]);

function isNonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

export function validateContract(contract) {
  const errors = [];
  const warnings = [];

  if (!isNonEmptyString(contract?.contractVersion)) errors.push('contractVersion is required');
  if (!isNonEmptyString(contract?.cube?.name)) errors.push('cube.name is required');
  if (!isNonEmptyString(contract?.cube?.grain)) errors.push('cube.grain is required');

  if (!Array.isArray(contract?.sources) || contract.sources.length === 0) {
    errors.push('sources must contain at least one source');
  } else {
    const sourceIds = new Set();
    for (const source of contract.sources) {
      if (!isNonEmptyString(source?.id)) errors.push('every source requires an id');
      else if (sourceIds.has(source.id)) errors.push(`duplicate source id: ${source.id}`);
      else sourceIds.add(source.id);
      if (!['drive-csv', 'google-sheet'].includes(source?.kind)) {
        errors.push(`source ${source?.id ?? '<unknown>'} has unsupported kind`);
      }
      if (!isNonEmptyString(source?.localSample)) {
        warnings.push(`source ${source?.id ?? '<unknown>'} has no localSample`);
      }
    }
  }

  const fieldNames = new Set();
  if (!Array.isArray(contract?.fields) || contract.fields.length === 0) {
    errors.push('fields must contain at least one field');
  } else {
    for (const field of contract.fields) {
      if (!isNonEmptyString(field?.name)) {
        errors.push('every field requires a name');
        continue;
      }
      if (fieldNames.has(field.name)) errors.push(`duplicate field: ${field.name}`);
      fieldNames.add(field.name);
      if (!allowedTypes.has(field?.type)) errors.push(`field ${field.name} has unsupported type`);
      if (typeof field?.nullable !== 'boolean') errors.push(`field ${field.name} requires nullable boolean`);
    }
  }

  for (const keyName of ['primary', 'deduplication']) {
    const fields = contract?.keys?.[keyName];
    if (!Array.isArray(fields) || fields.length === 0) {
      errors.push(`keys.${keyName} must contain at least one field`);
      continue;
    }
    for (const field of fields) {
      if (!fieldNames.has(field)) errors.push(`keys.${keyName} references undefined field: ${field}`);
    }
  }

  if (!Array.isArray(contract?.dimensions) || contract.dimensions.length === 0) {
    errors.push('dimensions must contain at least one dimension');
  } else {
    for (const dimension of contract.dimensions) {
      if (!isNonEmptyString(dimension?.name)) errors.push('every dimension requires a name');
      if (!fieldNames.has(dimension?.field)) {
        errors.push(`dimension ${dimension?.name ?? '<unknown>'} references undefined field: ${dimension?.field}`);
      }
    }
  }

  if (!Array.isArray(contract?.measures) || contract.measures.length === 0) {
    errors.push('measures must contain at least one measure');
  } else {
    for (const measure of contract.measures) {
      if (!isNonEmptyString(measure?.name)) errors.push('every measure requires a name');
      if (!fieldNames.has(measure?.field)) {
        errors.push(`measure ${measure?.name ?? '<unknown>'} references undefined field: ${measure?.field}`);
      }
      if (!allowedAggregations.has(measure?.aggregation)) {
        errors.push(`measure ${measure?.name ?? '<unknown>'} has unsupported aggregation: ${measure?.aggregation}`);
      }
    }
  }

  if (!Array.isArray(contract?.qualityRules) || contract.qualityRules.length === 0) {
    errors.push('qualityRules must contain at least one rule');
  }
  if (!Number.isFinite(contract?.freshness?.maximumAgeMinutes)
      || contract.freshness.maximumAgeMinutes <= 0) {
    errors.push('freshness.maximumAgeMinutes must be a positive number');
  }

  return {
    status: errors.length === 0 ? 'PASS' : 'FAIL',
    errors,
    warnings,
    summary: {
      sources: contract?.sources?.length ?? 0,
      fields: contract?.fields?.length ?? 0,
      dimensions: contract?.dimensions?.length ?? 0,
      measures: contract?.measures?.length ?? 0,
    },
  };
}

function main() {
  const file = process.argv[2];
  if (!file) {
    console.error('Usage: node scripts/validate-contract.mjs <contract.json>');
    process.exitCode = 1;
    return;
  }
  try {
    const absolute = resolve(file);
    const contract = JSON.parse(readFileSync(absolute, 'utf8'));
    const report = { file: absolute, ...validateContract(contract) };
    console.log(JSON.stringify(report, null, 2));
    process.exitCode = report.status === 'PASS' ? 0 : 2;
  } catch (error) {
    console.error(JSON.stringify({ status: 'FAIL', errors: [error.message] }, null, 2));
    process.exitCode = 1;
  }
}

if (import.meta.url === `file://${process.argv[1]}`) main();
