import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const root = new URL('../', import.meta.url).pathname;

test('runtime scripts use only approved local Node modules', () => {
  const allowed = new Set(['node:fs', 'node:path']);
  for (const entry of readdirSync(join(root, 'scripts'), { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith('.mjs')) continue;
    const content = readFileSync(join(root, 'scripts', entry.name), 'utf8');
    const imports = [...content.matchAll(/from\s+['"]([^'"]+)['"]/g)].map((match) => match[1]);
    for (const imported of imports) {
      assert.ok(allowed.has(imported), `${entry.name} imports disallowed module ${imported}`);
    }
    assert.doesNotMatch(content, /\bfetch\s*\(/, `${entry.name} must not call fetch`);
    assert.doesNotMatch(content, /\b(?:curl|wget|npm|pnpm|yarn)\b/, `${entry.name} must not invoke network or installers`);
  }
});

test('skills contain no remote links or executable network instructions', () => {
  const skills = join(root, 'skills');
  for (const name of readdirSync(skills)) {
    const content = readFileSync(join(skills, name, 'SKILL.md'), 'utf8');
    assert.doesNotMatch(content, /https?:\/\//);
    assert.doesNotMatch(content, /`(?:curl|wget|npm|pnpm|yarn)\b/);
  }
});
