const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {GAS_ROOT} = require('./helpers/load-gas');

test('source order is explicit and build output is byte deterministic', () => {
  const order = JSON.parse(fs.readFileSync(path.join(GAS_ROOT, 'source-order.json'), 'utf8'));
  assert.deepEqual(order.server, [
    'src/server/00_Namespace.js', 'src/server/10_Config.js', 'src/server/20_Contract.js',
    'src/server/30_Auth.js', 'src/server/40_DataService.js', 'src/server/50_RequestService.js',
    'src/server/60_AdminService.js', 'src/server/70_Menu.js', 'src/server/90_Entry.js',
  ]);
  const first = fs.mkdtempSync(path.join(os.tmpdir(), 'projectos-gas-first-'));
  const second = fs.mkdtempSync(path.join(os.tmpdir(), 'projectos-gas-second-'));
  for (const output of [first, second]) {
    const result = spawnSync(process.execPath, [path.join(GAS_ROOT, 'scripts/build.mjs'), '--out', output], {encoding: 'utf8'});
    assert.equal(result.status, 0, result.stderr);
  }
  const one = fs.readFileSync(path.join(first, 'Code.gs'));
  const two = fs.readFileSync(path.join(second, 'Code.gs'));
  assert.deepEqual(one, two);
  assert.match(one.toString(), /source: src\/server\/00_Namespace\.js/);
  assert.doesNotMatch(one.toString(), /[A-Za-z0-9_-]{30,}/);
  for (const asset of ['index.html', 'styles.html', 'app.html']) {
    assert.ok(fs.existsSync(path.join(first, asset)), asset);
    assert.deepEqual(fs.readFileSync(path.join(first, asset)), fs.readFileSync(path.join(second, asset)));
  }
});
