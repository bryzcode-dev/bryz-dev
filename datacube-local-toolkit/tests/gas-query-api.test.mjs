import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const skillPath = new URL('../skills/datacube-gas-query-api/SKILL.md', import.meta.url);
const contractPath = new URL('../shared/templates/api-contract.example.json', import.meta.url);

test('skill defines bounded and parameterized query behavior', () => {
  const content = readFileSync(skillPath, 'utf8');
  assert.match(content, /^---\nname: datacube-gas-query-api\n/m);
  assert.match(content, /description: Use when/i);
  assert.match(content, /Offline boundary/);
  for (const term of ['parameter', 'allowlist', 'partition', 'maximum rows', 'bytes', 'cache']) {
    assert.match(content, new RegExp(term, 'i'));
  }
});

test('skill defines authorization and full-cube guardrails', () => {
  const content = readFileSync(skillPath, 'utf8');
  assert.match(content, /authoriz/i);
  assert.match(content, /full.cube/i);
  assert.match(content, /versioned/i);
  assert.match(content, /NOT RUN/);
});

test('example contract contains request limits and allowlists', () => {
  const contract = JSON.parse(readFileSync(contractPath, 'utf8'));
  assert.equal(contract.contractVersion, '1.0.0');
  assert.ok(contract.request.allowedDimensions.includes('region'));
  assert.ok(contract.request.allowedMeasures.includes('total_sales'));
  assert.ok(contract.request.limits.maximumRows > 0);
  assert.ok(contract.request.limits.maximumDateRangeDays > 0);
  assert.ok(contract.request.limits.maximumBytesBilled > 0);
});

test('example response is versioned and exposes execution metadata', () => {
  const contract = JSON.parse(readFileSync(contractPath, 'utf8'));
  assert.equal(contract.response.requiredFields.includes('apiVersion'), true);
  assert.equal(contract.response.requiredFields.includes('cubeVersion'), true);
  assert.equal(contract.response.requiredFields.includes('data'), true);
  assert.equal(contract.response.requiredFields.includes('meta'), true);
  assert.equal(contract.response.requiredFields.includes('errors'), true);
  assert.equal(contract.response.metaFields.includes('cacheHit'), true);
  assert.equal(contract.response.metaFields.includes('bytesProcessed'), true);
});
