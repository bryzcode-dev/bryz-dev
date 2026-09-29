const test = require('node:test');
const assert = require('node:assert/strict');
const {loadGas} = require('./helpers/load-gas');

const users = [
  {email: 'owner@example.com', role: 'OWNER', active: true, protected_owner: true},
  {email: 'admin@example.com', role: 'ADMIN', active: true},
  {email: 'user@example.com', role: 'USER', active: true},
];
const projects = [
  {project_id: 'public-id', name: 'Public', description: 'safe', project_type: 'GAS', status: 'ACTIVE', visibility: 'PUBLIC', tags: '[]', version: 1},
  {project_id: 'private-id', name: 'Private', description: 'hidden', project_type: 'LOCAL', status: 'ACTIVE', visibility: 'PRIVATE', tags: '[]', version: 1},
];

test('canonical JSON and SHA-256 match the Python golden fixture', () => {
  const {ProjectOS} = loadGas();
  assert.equal(ProjectOS.Contract.canonicalJson({z: 1, a: [3, {x: 'é'}]}), '{"a":[3,{"x":"é"}],"z":1}');
  assert.equal(ProjectOS.Contract.sha256({z: 1, a: [3, {x: 'é'}]}), '02409bf80db1e51eeb7bdcf03f1d58fb3027fd9b83d8e901532b498522672dea');
});

test('request, access, and draft append paths use the shared lock', () => {
  const {context, state} = loadGas({activeEmail: 'owner@example.com', users, projects});
  assert.equal(context.submitChangeRequest({entity_type: 'project', entity_id: 'public-id', operation: 'UPDATE', base_version: 1, changes: {name: 'Renamed'}, role: 'USER'}).status, 'PENDING');
  assert.equal(context.submitOwnerDraft({entity_type: 'project', changes: {name: 'Draft'}}).status, 'DRAFTED');
  context.recordAccessEvent();
  assert.equal(state.lockCount, 3);
  assert.equal(state.requests[0].actor_role_claim, 'OWNER');
});

test('only protected Owner can submit drafts, user changes, and admin queries', () => {
  for (const email of ['admin@example.com', 'user@example.com']) {
    const {context} = loadGas({activeEmail: email, users, projects});
    for (const call of [
      () => context.submitOwnerDraft({changes: {name: 'Nope'}}),
      () => context.submitUserChangeRequest({changes: {display_name: 'Nope'}}),
      () => context.listConflicts(),
    ]) {
      assert.equal(call().error.code, 'ACCESS_DENIED');
    }
  }
});

test('Admin edits allowlisted PUBLIC fields and cannot target PRIVATE or users', () => {
  const {context, state} = loadGas({activeEmail: 'admin@example.com', users, projects});
  assert.equal(context.submitChangeRequest({entity_type: 'project', entity_id: 'public-id', operation: 'UPDATE', base_version: 1, changes: {name: 'Allowed'}}).status, 'PENDING');
  assert.equal(context.submitChangeRequest({entity_type: 'project', entity_id: 'private-id', operation: 'UPDATE', base_version: 1, changes: {name: 'Nope'}}).error.code, 'ACCESS_DENIED');
  assert.equal(context.submitChangeRequest({entity_type: 'project', entity_id: 'public-id', operation: 'UPDATE', base_version: 1, changes: {visibility: 'PRIVATE'}}).error.code, 'ACCESS_DENIED');
  assert.equal(context.submitUserChangeRequest({changes: {display_name: 'Nope'}}).error.code, 'ACCESS_DENIED');
  assert.equal(state.requests.length, 1);
});
