const test = require('node:test');
const assert = require('node:assert/strict');
const {loadGas} = require('./helpers/load-gas');

const users = [
  {email: 'owner@example.com', role: 'OWNER', active: true, protected_owner: true},
  {email: 'admin@example.com', role: 'ADMIN', active: true},
  {email: 'user@example.com', role: 'USER', active: true},
  {email: 'inactive@example.com', role: 'USER', active: false},
];

test('blank, malformed, unlisted, and inactive callers are denied before project query', () => {
  for (const email of ['', 'malformed', 'missing@example.com', 'inactive@example.com']) {
    const {context, state} = loadGas({activeEmail: email, users});
    const result = context.listProjects();
    assert.equal(result.ok, false);
    assert.equal(result.error.code, 'ACCESS_DENIED');
    assert.equal(state.queryCount, 0);
  }
});

test('caller role is canonical and never accepted from client input', () => {
  const {ProjectOS} = loadGas({activeEmail: 'user@example.com', users});
  const context = ProjectOS.Auth.resolve({role: 'OWNER'});
  assert.equal(context.role, 'USER');
  assert.equal(context.adminMenu, false);
  assert.equal(context.canEdit, false);
});

test('session bootstrap exposes only canonical presentation capabilities', () => {
  for (const expected of [
    {email: 'owner@example.com', role: 'OWNER', canEdit: true, adminMenu: true},
    {email: 'admin@example.com', role: 'ADMIN', canEdit: true, adminMenu: false},
    {email: 'user@example.com', role: 'USER', canEdit: false, adminMenu: false},
  ]) {
    const {context} = loadGas({activeEmail: expected.email, users});
    assert.deepEqual(
      JSON.parse(JSON.stringify(context.getSession({role: 'OWNER'}))),
      {ok: true, data: {role: expected.role, canEdit: expected.canEdit, adminMenu: expected.adminMenu, looker: {
        view: true,
        edit: expected.role !== 'USER',
        import: expected.role === 'OWNER',
        reconcile: expected.role === 'OWNER',
        cutover: expected.role === 'OWNER',
      }}},
    );
  }
});
