#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === ',' && !quoted) {
      row.push(field);
      field = '';
    } else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && text[index + 1] === '\n') index += 1;
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else {
      field += char;
    }
  }

  if (quoted) throw new Error('CSV has an unterminated quoted field');
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

function inferValueType(value) {
  if (/^(true|false)$/i.test(value)) return 'BOOLEAN';
  if (/^[+-]?\d+$/.test(value)) return 'INTEGER';
  if (/^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(value)) return 'NUMERIC';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`))) return 'DATE';
  if (/^\d{4}-\d{2}-\d{2}T/.test(value) && !Number.isNaN(Date.parse(value))) return 'TIMESTAMP';
  return 'STRING';
}

function combineTypes(types) {
  if (types.size === 0) return 'EMPTY';
  if (types.size === 1) return [...types][0];
  if ([...types].every((type) => type === 'INTEGER' || type === 'NUMERIC')) return 'NUMERIC';
  return 'STRING';
}

export function profileCsv(text, keyFields = []) {
  const rows = parseCsv(text);
  const errors = [];
  if (rows.length === 0) return { status: 'FAIL', errors: ['CSV is empty'] };

  const headers = rows[0].map((value) => value.trim());
  if (headers.some((value) => value.length === 0)) errors.push('CSV contains a blank header');
  if (new Set(headers).size !== headers.length) errors.push('CSV contains duplicate headers');

  const dataRows = rows.slice(1).filter((candidate) => !(candidate.length === 1 && candidate[0] === ''));
  dataRows.forEach((candidate, index) => {
    if (candidate.length !== headers.length) {
      errors.push(`ragged row ${index + 2}: expected ${headers.length} fields, found ${candidate.length}`);
    }
  });

  const missingKeys = keyFields.filter((fieldName) => !headers.includes(fieldName));
  if (missingKeys.length > 0) errors.push(`key columns not found: ${missingKeys.join(', ')}`);

  const columns = Object.fromEntries(headers.map((header, columnIndex) => {
    const values = dataRows.filter((candidate) => candidate.length === headers.length)
      .map((candidate) => candidate[columnIndex]);
    const nonBlank = values.filter((value) => value.trim() !== '');
    return [header, {
      blankCount: values.length - nonBlank.length,
      nonBlankCount: nonBlank.length,
      inferredType: combineTypes(new Set(nonBlank.map(inferValueType))),
    }];
  }));

  const keyIndexes = keyFields.map((fieldName) => headers.indexOf(fieldName));
  const seen = new Map();
  if (missingKeys.length === 0 && keyIndexes.length > 0) {
    for (const candidate of dataRows.filter((item) => item.length === headers.length)) {
      const key = JSON.stringify(keyIndexes.map((index) => candidate[index]));
      seen.set(key, (seen.get(key) ?? 0) + 1);
    }
  }
  const duplicateKeys = [...seen.entries()]
    .filter(([, count]) => count > 1)
    .map(([key, count]) => ({ values: JSON.parse(key), count }));

  return {
    status: errors.length === 0 ? 'PASS' : 'FAIL',
    headers,
    rowCount: dataRows.length,
    columnCount: headers.length,
    columns,
    keyFields,
    duplicateKeyCount: duplicateKeys.reduce((total, item) => total + item.count - 1, 0),
    duplicateKeys,
    errors,
  };
}

function main() {
  const file = process.argv[2];
  if (!file) {
    console.error('Usage: node scripts/profile-csv.mjs <file.csv> [--key field[,field]]');
    process.exitCode = 1;
    return;
  }
  const keyPosition = process.argv.indexOf('--key');
  const keyFields = keyPosition >= 0 && process.argv[keyPosition + 1]
    ? process.argv[keyPosition + 1].split(',').map((value) => value.trim()).filter(Boolean)
    : [];
  try {
    const absolute = resolve(file);
    const report = { file: absolute, ...profileCsv(readFileSync(absolute, 'utf8'), keyFields) };
    console.log(JSON.stringify(report, null, 2));
    process.exitCode = report.status === 'PASS' ? 0 : 2;
  } catch (error) {
    console.error(JSON.stringify({ status: 'FAIL', errors: [error.message] }, null, 2));
    process.exitCode = 1;
  }
}

if (import.meta.url === `file://${process.argv[1]}`) main();
