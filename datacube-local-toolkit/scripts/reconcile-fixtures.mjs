#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

function usage(message) {
  process.stderr.write(`${message}\nUsage: node scripts/reconcile-fixtures.mjs <expected.json> <actual.json>\n`);
  process.exit(1);
}

if (process.argv.length !== 4) usage('Expected an expectation file and an actual-results file.');

function readJson(file) {
  return JSON.parse(readFileSync(resolve(file), 'utf8'));
}

let expected;
let actual;
try {
  expected = readJson(process.argv[2]);
  actual = readJson(process.argv[3]);
} catch (error) {
  usage(`Cannot read reconciliation input: ${error.message}`);
}

const errors = [];
const results = [];

if (!expected || typeof expected !== 'object' || Array.isArray(expected)) {
  errors.push('Expected document must be an object');
}
if (!actual || typeof actual !== 'object' || Array.isArray(actual)) {
  errors.push('Actual document must be an object');
}
if (typeof expected?.cubeVersion !== 'string' || expected.cubeVersion.trim() === '') {
  errors.push('Expected cubeVersion must be a non-empty string');
}
if (expected?.cubeVersion !== actual?.cubeVersion) {
  errors.push(`cubeVersion mismatch: expected ${expected?.cubeVersion ?? 'missing'}, actual ${actual?.cubeVersion ?? 'missing'}`);
}
if (!expected?.metrics || typeof expected.metrics !== 'object' || Array.isArray(expected.metrics)) {
  errors.push('Expected metrics must be an object');
}
if (!actual?.metrics || typeof actual.metrics !== 'object' || Array.isArray(actual.metrics)) {
  errors.push('Actual metrics must be an object');
}

for (const [name, rule] of Object.entries(expected?.metrics ?? {})) {
  const expectedValue = rule?.value;
  const absoluteTolerance = rule?.absoluteTolerance ?? 0;
  const relativeTolerance = rule?.relativeTolerance ?? 0;
  const actualValue = actual?.metrics?.[name];

  if (!Number.isFinite(expectedValue)) {
    errors.push(`${name}.value must be a finite number`);
    results.push({ name, status: 'FAIL', reason: 'expected value is not a finite number' });
    continue;
  }
  if (!Number.isFinite(absoluteTolerance) || absoluteTolerance < 0) {
    errors.push(`${name}.absoluteTolerance must be a non-negative finite number`);
    results.push({ name, status: 'FAIL', reason: 'absolute tolerance is invalid' });
    continue;
  }
  if (!Number.isFinite(relativeTolerance) || relativeTolerance < 0) {
    errors.push(`${name}.relativeTolerance must be a non-negative finite number`);
    results.push({ name, status: 'FAIL', reason: 'relative tolerance is invalid' });
    continue;
  }
  if (!Number.isFinite(actualValue)) {
    results.push({ name, expected: expectedValue, actual: actualValue ?? null, status: 'FAIL', reason: 'actual metric is missing or not a finite number' });
    continue;
  }

  const difference = Math.abs(actualValue - expectedValue);
  const allowedTolerance = Math.max(absoluteTolerance, Math.abs(expectedValue) * relativeTolerance);
  results.push({
    name,
    expected: expectedValue,
    actual: actualValue,
    difference,
    allowedTolerance,
    status: difference <= allowedTolerance ? 'PASS' : 'FAIL',
  });
}

const passed = errors.length === 0 && results.every((metric) => metric.status === 'PASS');
const report = {
  status: passed ? 'PASS' : 'FAIL',
  cubeVersion: actual?.cubeVersion ?? null,
  errors,
  metrics: results,
};

process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
if (!passed) process.exitCode = 2;
