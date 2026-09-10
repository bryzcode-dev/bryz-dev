import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const validator = new URL('../scripts/validate-contract.mjs', import.meta.url);
const skill = new URL('../skills/datacube-design-contract/SKILL.md', import.meta.url);

const validContract = {
  contractVersion: '1.0.0',
  cube: { name: 'sales-cube', grain: 'one row per order line' },
  sources: [
    { id: 'sales-csv', kind: 'drive-csv', localSample: 'sales.csv' },
  ],
  fields: [
    { name: 'order_id', type: 'STRING', nullable: false },
    { name: 'region', type: 'STRING', nullable: false },
    { name: 'sales', type: 'NUMERIC', nullable: false },
  ],
  keys: { primary: ['order_id'], deduplication: ['order_id'] },
  dimensions: [{ name: 'region', field: 'region' }],
  measures: [{ name: 'total_sales', field: 'sales', aggregation: 'SUM' }],
  qualityRules: [{ id: 'sales-nonnegative', expression: 'sales >= 0', severity: 'ERROR' }],
  freshness: { maximumAgeMinutes: 60 },
};

function runContract(contract) {
  const dir = mkdtempSync(join(tmpdir(), 'datacube-contract-'));
  const file = join(dir, 'contract.json');
  writeFileSync(file, JSON.stringify(contract));
  const result = spawnSync(process.execPath, [validator.pathname, file], {
    cwd: root.pathname,
    encoding: 'utf8',
  });
  rmSync(dir, { recursive: true, force: true });
  return result;
}

test('accepts a complete contract', () => {
  const result = runContract(validContract);
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const report = JSON.parse(result.stdout);
  assert.equal(report.status, 'PASS');
  assert.equal(report.errors.length, 0);
});

test('rejects a missing grain', () => {
  const contract = structuredClone(validContract);
  delete contract.cube.grain;
  const result = runContract(contract);
  assert.notEqual(result.status, 0);
  assert.match(result.stdout, /cube\.grain/);
});

test('rejects key references to undefined fields', () => {
  const contract = structuredClone(validContract);
  contract.keys.primary = ['missing_id'];
  const result = runContract(contract);
  assert.notEqual(result.status, 0);
  assert.match(result.stdout, /missing_id/);
});

test('rejects duplicate canonical field names', () => {
  const contract = structuredClone(validContract);
  contract.fields.push({ name: 'region', type: 'STRING', nullable: true });
  const result = runContract(contract);
  assert.notEqual(result.status, 0);
  assert.match(result.stdout, /duplicate field/i);
});

test('rejects unsupported aggregations', () => {
  const contract = structuredClone(validContract);
  contract.measures[0].aggregation = 'MAGIC';
  const result = runContract(contract);
  assert.notEqual(result.status, 0);
  assert.match(result.stdout, /aggregation/i);
});

test('skill declares the contract gate and offline boundary', () => {
  const content = readFileSync(skill, 'utf8');
  assert.match(content, /^---\nname: datacube-design-contract\n/m);
  assert.match(content, /description: Use when/i);
  assert.match(content, /Offline boundary/);
  assert.match(content, /No pipeline implementation/i);
  assert.match(content, /PASS.*FAIL.*BLOCKED/s);
});
