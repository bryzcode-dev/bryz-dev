import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const preflight = new URL('../scripts/release-preflight.mjs', import.meta.url);
const skill = new URL('../skills/datacube-release-operations/SKILL.md', import.meta.url);

const localIds = [
  'contract-validation',
  'fixture-reconciliation',
  'idempotency-simulation',
  'api-contract',
  'secret-scan',
  'rollback-manifest',
];

function completeManifest() {
  return {
    releaseVersion: '1.0.0',
    cubeVersion: 'sales-20260910-001',
    contractVersion: '1.0.0',
    rollback: {
      cubeVersion: 'sales-20260909-001',
      target: 'analytics.sales_cube_v20260909_001',
      testedLocally: true,
    },
    checks: [
      ...localIds.map((id) => ({
        id,
        required: true,
        environment: 'local',
        status: 'PASS',
        evidence: { origin: 'local-test', artifact: `evidence/${id}.json` },
      })),
      {
        id: 'bigquery-dry-run',
        required: true,
        environment: 'connected',
        status: 'NOT RUN',
        evidence: { origin: 'offline-environment' },
      },
      {
        id: 'gas-deployment-smoke-test',
        required: true,
        environment: 'connected',
        status: 'NOT RUN',
        evidence: { origin: 'offline-environment' },
      },
    ],
  };
}

function runManifest(manifest) {
  const dir = mkdtempSync(join(tmpdir(), 'datacube-release-'));
  const file = join(dir, 'release.json');
  writeFileSync(file, JSON.stringify(manifest));
  const result = spawnSync(process.execPath, [preflight.pathname, file], {
    cwd: root.pathname,
    encoding: 'utf8',
  });
  rmSync(dir, { recursive: true, force: true });
  return result;
}

test('accepts complete local evidence and requests connected validation', () => {
  const result = runManifest(completeManifest());
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const report = JSON.parse(result.stdout);
  assert.equal(report.status, 'READY_FOR_CONNECTED_VALIDATION');
  assert.deepEqual(report.pendingConnected.sort(), ['bigquery-dry-run', 'gas-deployment-smoke-test']);
});

test('blocks a missing required local check', () => {
  const manifest = completeManifest();
  manifest.checks = manifest.checks.filter((check) => check.id !== 'secret-scan');
  const result = runManifest(manifest);
  assert.notEqual(result.status, 0);
  assert.match(result.stdout, /secret-scan/);
});

test('blocks a failed local check', () => {
  const manifest = completeManifest();
  manifest.checks.find((check) => check.id === 'fixture-reconciliation').status = 'FAIL';
  const result = runManifest(manifest);
  assert.notEqual(result.status, 0);
  assert.match(result.stdout, /fixture-reconciliation/);
});

test('blocks a connected pass falsely attributed to local evidence', () => {
  const manifest = completeManifest();
  const check = manifest.checks.find((item) => item.id === 'bigquery-dry-run');
  check.status = 'PASS';
  check.evidence.origin = 'local-test';
  const result = runManifest(manifest);
  assert.notEqual(result.status, 0);
  assert.match(result.stdout, /connected-environment/);
});

test('blocks missing connected gates and mutable cube identity', () => {
  const manifest = completeManifest();
  manifest.cubeVersion = 'latest';
  manifest.checks = manifest.checks.filter((check) => check.id !== 'gas-deployment-smoke-test');
  const result = runManifest(manifest);
  assert.equal(result.status, 2);
  assert.match(result.stdout, /immutable/i);
  assert.match(result.stdout, /gas-deployment-smoke-test/);
});

test('requires an evidence artifact for a connected pass', () => {
  const manifest = completeManifest();
  for (const check of manifest.checks.filter((item) => item.environment === 'connected')) {
    check.status = 'PASS';
    check.evidence = { origin: 'connected-environment' };
  }
  const result = runManifest(manifest);
  assert.equal(result.status, 2);
  assert.match(result.stdout, /evidence artifact/);
});

test('skill requires release evidence, atomic promotion, and rollback', () => {
  const content = readFileSync(skill, 'utf8');
  assert.match(content, /^---\nname: datacube-release-operations\n/m);
  assert.match(content, /description: Use when/i);
  assert.match(content, /Offline boundary/);
  for (const term of ['reconciliation', 'atomic', 'last-known-good', 'rollback', 'BLOCKED']) {
    assert.match(content, new RegExp(term, 'i'));
  }
});
