import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const reconcile = new URL('../scripts/reconcile-fixtures.mjs', import.meta.url);

function run(expected, actual) {
  const dir = mkdtempSync(join(tmpdir(), 'datacube-reconcile-'));
  const expectedPath = join(dir, 'expected.json');
  const actualPath = join(dir, 'actual.json');
  writeFileSync(expectedPath, JSON.stringify(expected));
  writeFileSync(actualPath, JSON.stringify(actual));
  const result = spawnSync(process.execPath, [reconcile.pathname, expectedPath, actualPath], {
    cwd: root.pathname,
    encoding: 'utf8',
  });
  rmSync(dir, { recursive: true, force: true });
  return result;
}

test('passes exact and tolerant metric comparisons', () => {
  const result = run({
    cubeVersion: 'sales-001',
    metrics: {
      order_count: { value: 3 },
      total_sales: { value: 42, absoluteTolerance: 0.01 },
      conversion_rate: { value: 0.25, relativeTolerance: 0.02 },
    },
  }, {
    cubeVersion: 'sales-001',
    metrics: { order_count: 3, total_sales: 42.005, conversion_rate: 0.254 },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const report = JSON.parse(result.stdout);
  assert.equal(report.status, 'PASS');
  assert.equal(report.metrics.length, 3);
  assert.ok(report.metrics.every((metric) => metric.status === 'PASS'));
});

test('fails when a difference exceeds both tolerances', () => {
  const result = run({
    cubeVersion: 'sales-001',
    metrics: { total_sales: { value: 42, absoluteTolerance: 0.01, relativeTolerance: 0.001 } },
  }, {
    cubeVersion: 'sales-001',
    metrics: { total_sales: 42.5 },
  });
  assert.equal(result.status, 2);
  const report = JSON.parse(result.stdout);
  assert.equal(report.status, 'FAIL');
  assert.equal(report.metrics[0].status, 'FAIL');
  assert.equal(report.metrics[0].allowedTolerance, 0.042);
});

test('fails on a missing metric or cube version mismatch', () => {
  const result = run({
    cubeVersion: 'sales-001',
    metrics: { order_count: { value: 3 } },
  }, {
    cubeVersion: 'sales-002',
    metrics: {},
  });
  assert.equal(result.status, 2);
  const report = JSON.parse(result.stdout);
  assert.match(report.errors.join(' '), /cubeVersion/);
  assert.equal(report.metrics[0].status, 'FAIL');
  assert.match(report.metrics[0].reason, /missing/i);
});

test('rejects malformed expectations', () => {
  const result = run({ cubeVersion: 'sales-001', metrics: { count: { value: 'three' } } }, {
    cubeVersion: 'sales-001', metrics: { count: 3 },
  });
  assert.equal(result.status, 2);
  assert.match(result.stdout, /finite number/);
});
