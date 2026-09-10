import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const profiler = new URL('../scripts/profile-csv.mjs', import.meta.url);
const skill = new URL('../skills/datacube-ingestion-build/SKILL.md', import.meta.url);

function runProfile(csv, args = []) {
  const dir = mkdtempSync(join(tmpdir(), 'datacube-csv-'));
  const file = join(dir, 'sample.csv');
  writeFileSync(file, csv);
  const result = spawnSync(process.execPath, [profiler.pathname, file, ...args], {
    cwd: root.pathname,
    encoding: 'utf8',
  });
  rmSync(dir, { recursive: true, force: true });
  return result;
}

test('profiles headers, row count, types, blanks, and duplicate keys', () => {
  const csv = [
    'order_id,region,sales,order_date,note',
    '1,West,10.50,2026-09-01,"priority, retail"',
    '2,East,,2026-09-02,"said ""hello"""',
    '2,East,5,2026-09-02,repeat',
  ].join('\n');
  const result = runProfile(csv, ['--key', 'order_id']);
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const report = JSON.parse(result.stdout);
  assert.deepEqual(report.headers, ['order_id', 'region', 'sales', 'order_date', 'note']);
  assert.equal(report.rowCount, 3);
  assert.equal(report.duplicateKeyCount, 1);
  assert.equal(report.columns.sales.blankCount, 1);
  assert.equal(report.columns.order_date.inferredType, 'DATE');
});

test('supports quoted newlines as one field', () => {
  const result = runProfile('id,note\n1,"line one\nline two"\n');
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.equal(JSON.parse(result.stdout).rowCount, 1);
});

test('rejects ragged rows', () => {
  const result = runProfile('id,region,sales\n1,West,10\n2,East\n');
  assert.notEqual(result.status, 0);
  assert.match(result.stdout, /ragged/i);
});

test('rejects a missing key column', () => {
  const result = runProfile('id,value\n1,10\n', ['--key', 'order_id']);
  assert.notEqual(result.status, 0);
  assert.match(result.stdout, /order_id/);
});

test('skill enforces idempotency, locking, quarantine, quality, and atomic promotion', () => {
  const content = readFileSync(skill, 'utf8');
  assert.match(content, /^---\nname: datacube-ingestion-build\n/m);
  assert.match(content, /description: Use when/i);
  assert.match(content, /Offline boundary/);
  for (const term of ['idempotent', 'lock', 'quarantine', 'quality', 'atomic']) {
    assert.match(content, new RegExp(term, 'i'));
  }
  assert.match(content, /last-known-good/i);
});
