import assert from 'node:assert/strict';
import { existsSync, lstatSync, readFileSync, realpathSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';

const root = new URL('../', import.meta.url).pathname;
const skillNames = [
  'datacube-design-contract',
  'datacube-ingestion-build',
  'datacube-gas-query-api',
  'datacube-release-operations',
];

test('ships four focused, distinctly triggered skills', () => {
  const descriptions = [];
  for (const name of skillNames) {
    const file = join(root, 'skills', name, 'SKILL.md');
    const content = readFileSync(file, 'utf8');
    assert.match(content, new RegExp(`^name: ${name}$`, 'm'));
    const description = content.match(/^description: (.+)$/m)?.[1];
    assert.ok(description?.startsWith('Use when'), `${name} needs a Use when description`);
    descriptions.push(description);
    assert.doesNotMatch(content, /\b(?:TODO|TBD)\b/);
    assert.match(content, /inspect/i, `${name} must inspect existing project artifacts before proposing changes`);
  }
  assert.equal(new Set(descriptions).size, skillNames.length);
});

test('all relative Markdown references in skills resolve', () => {
  for (const name of skillNames) {
    const file = join(root, 'skills', name, 'SKILL.md');
    const content = readFileSync(file, 'utf8');
    const links = [...content.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)].map((match) => match[1]);
    for (const link of links) {
      assert.ok(existsSync(resolve(dirname(file), link)), `${name} has broken link ${link}`);
    }
  }
});

test('Codex and Claude Code discover the same canonical skills', () => {
  for (const host of ['.agents/skills', '.claude/skills']) {
    for (const name of skillNames) {
      const link = join(root, host, name);
      assert.ok(lstatSync(link).isSymbolicLink(), `${link} must be a symlink`);
      assert.equal(realpathSync(link), realpathSync(join(root, 'skills', name)));
    }
  }
});

test('host routing files preserve the offline boundary', () => {
  for (const file of ['AGENTS.md', 'CLAUDE.md']) {
    const content = readFileSync(join(root, file), 'utf8');
    assert.match(content, /local-only/i);
    assert.match(content, /NOT RUN/);
    for (const name of skillNames) assert.match(content, new RegExp(name));
  }
});

test('shared policy and operator guide are present', () => {
  for (const file of [
    'shared/references/offline-environment-policy.md',
    'shared/references/architecture-principles.md',
    'shared/templates/environment-policy.example.json',
    'USAGE.md',
    'SECURITY.md',
  ]) assert.ok(existsSync(join(root, file)), `missing ${file}`);
});
