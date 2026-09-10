#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const requiredLocal = [
  'contract-validation',
  'fixture-reconciliation',
  'idempotency-simulation',
  'api-contract',
  'secret-scan',
  'rollback-manifest',
];
const requiredConnected = ['bigquery-dry-run', 'gas-deployment-smoke-test'];

function failUsage(message) {
  process.stderr.write(`${message}\nUsage: node scripts/release-preflight.mjs <release-manifest.json>\n`);
  process.exit(1);
}

if (process.argv.length !== 3) failUsage('Expected one release manifest.');

let manifest;
try {
  manifest = JSON.parse(readFileSync(resolve(process.argv[2]), 'utf8'));
} catch (error) {
  failUsage(`Cannot read release manifest: ${error.message}`);
}

const errors = [];
const pendingConnected = [];
const checks = Array.isArray(manifest.checks) ? manifest.checks : [];

for (const field of ['releaseVersion', 'cubeVersion', 'contractVersion']) {
  if (typeof manifest[field] !== 'string' || manifest[field].trim() === '') {
    errors.push(`${field} must be a non-empty string`);
  }
}
if (typeof manifest.cubeVersion === 'string' && /^latest$/i.test(manifest.cubeVersion.trim())) {
  errors.push('cubeVersion must be an immutable identity, not latest');
}

if (!manifest.rollback || typeof manifest.rollback !== 'object') {
  errors.push('rollback must identify a tested last-known-good target');
} else {
  for (const field of ['cubeVersion', 'target']) {
    if (typeof manifest.rollback[field] !== 'string' || manifest.rollback[field].trim() === '') {
      errors.push(`rollback.${field} must be a non-empty string`);
    }
  }
  if (manifest.rollback.testedLocally !== true) {
    errors.push('rollback.testedLocally must be true');
  }
}

if (!Array.isArray(manifest.checks)) errors.push('checks must be an array');

for (const id of requiredLocal) {
  const check = checks.find((item) => item && item.id === id);
  if (!check) {
    errors.push(`Missing required local check: ${id}`);
    continue;
  }
  if (check.environment !== 'local') errors.push(`${id} must use environment local`);
  if (check.required !== true) errors.push(`${id} must be required`);
  if (check.status !== 'PASS') errors.push(`${id} must PASS locally; found ${check.status ?? 'missing status'}`);
  if (check.evidence?.origin !== 'local-test') errors.push(`${id} PASS must use evidence.origin local-test`);
  if (typeof check.evidence?.artifact !== 'string' || check.evidence.artifact.trim() === '') {
    errors.push(`${id} PASS must name an evidence artifact`);
  }
}

for (const id of requiredConnected) {
  const check = checks.find((item) => item && item.id === id);
  if (!check) {
    errors.push(`Missing required connected check: ${id}`);
    continue;
  }
  if (check.environment !== 'connected') errors.push(`${id} must use environment connected`);
  if (check.required !== true) errors.push(`${id} must be required`);
  if (check.status === 'PASS') {
    if (check.evidence?.origin !== 'connected-environment') {
      errors.push(`${check.id} connected PASS requires evidence.origin connected-environment`);
    }
    if (typeof check.evidence?.artifact !== 'string' || check.evidence.artifact.trim() === '') {
      errors.push(`${check.id} connected PASS must name an evidence artifact`);
    }
  } else if (check.status === 'NOT RUN' || check.status === 'BLOCKED') {
    pendingConnected.push(check.id);
  } else {
    errors.push(`${check.id} connected check has non-passing status ${check.status ?? 'missing status'}`);
  }
}

const report = {
  status: errors.length > 0
    ? 'BLOCKED'
    : pendingConnected.length > 0
      ? 'READY_FOR_CONNECTED_VALIDATION'
      : 'READY_FOR_RELEASE',
  releaseVersion: manifest.releaseVersion ?? null,
  cubeVersion: manifest.cubeVersion ?? null,
  contractVersion: manifest.contractVersion ?? null,
  rollbackTarget: manifest.rollback?.target ?? null,
  errors,
  pendingConnected: [...new Set(pendingConnected)].sort(),
};

process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
if (errors.length > 0) process.exitCode = 2;
