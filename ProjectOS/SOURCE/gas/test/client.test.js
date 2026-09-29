const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {GAS_ROOT} = require('./helpers/load-gas');

function loadClient() {
  const html = fs.readFileSync(path.join(GAS_ROOT, 'src/client/app.html'), 'utf8');
  const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
  const document = {readyState: 'loading', addEventListener() {}};
  const window = {};
  vm.runInNewContext(script, {window, document, console, URLSearchParams, location: {search: ''}});
  return window.ProjectOSClient;
}

test('role view models expose edit and admin controls exactly as authorized', () => {
  const client = loadClient();
  const user = client.buildViewModel({role: 'USER', canEdit: false, adminMenu: false});
  const admin = client.buildViewModel({role: 'ADMIN', canEdit: true, adminMenu: false});
  const owner = client.buildViewModel({role: 'OWNER', canEdit: true, adminMenu: true});
  assert.equal(user.showEdit, false);
  assert.deepEqual(Array.from(user.adminRoutes), []);
  assert.deepEqual(Array.from(user.visibilityOptions), ['ALL', 'PUBLIC']);
  assert.equal(admin.showEdit, true);
  assert.deepEqual(Array.from(admin.adminRoutes), []);
  assert.deepEqual(Array.from(admin.visibilityOptions), ['ALL', 'PUBLIC']);
  assert.equal(owner.showEdit, true);
  assert.deepEqual(Array.from(owner.adminRoutes), ['Users', 'Conflicts', 'Audit', 'Settings']);
  assert.deepEqual(Array.from(owner.visibilityOptions), ['ALL', 'PUBLIC', 'PRIVATE']);
  assert.equal(client.adminMethod('Users'), 'listUsers');
  assert.equal(client.adminMethod('Conflicts'), 'listConflicts');
  assert.equal(client.adminMethod('Audit'), 'getAuditSummary');
  assert.equal(client.adminMethod('Settings'), 'getSettings');
  assert.equal(client.adminMethod('Projects'), null);
});

test('safe request states have distinct non-disclosing copy', () => {
  const client = loadClient();
  const states = ['MAINTENANCE', 'ACCESS_DENIED', 'NOT_FOUND', 'PENDING', 'CONFLICT', 'REJECTED'];
  const copy = states.map((state) => client.stateCopy(state));
  assert.equal(new Set(copy.map((item) => item.title)).size, states.length);
  assert.match(copy.find((item) => item.code === 'PENDING').message, /queued/i);
  assert.doesNotMatch(JSON.stringify(copy), /owner@example|private|token|current value/i);
});

test('client server calls never send a role or authorization override', () => {
  const client = loadClient();
  const observed = [];
  const runner = {
    withSuccessHandler(callback) { this.success = callback; return this; },
    withFailureHandler(callback) { this.failure = callback; return this; },
    submitChangeRequest(payload) { observed.push(payload); this.success({ok: true}); },
  };
  client.callServer(runner, 'submitChangeRequest', [{entity_type: 'project', changes: {name: 'Safe'}}], () => {});
  assert.equal(observed.length, 1);
  assert.equal(Object.hasOwn(observed[0], 'role'), false);
  assert.equal(Object.hasOwn(observed[0], 'authorized'), false);
});

test('fixture normalization drops private projects for non-Owner roles', () => {
  const client = loadClient();
  const data = {session: {role: 'ADMIN'}, projects: [
    {project_id: 'one', name: 'Public', visibility: 'PUBLIC'},
    {project_id: 'two', name: 'Private', visibility: 'PRIVATE'},
  ]};
  const normalized = client.normalizeBootstrap(data);
  assert.deepEqual(Array.from(normalized.projects, (item) => item.project_id), ['one']);
});

test('project detail normalization keeps role-safe child collections', () => {
  const client = loadClient();
  const detail = client.normalizeProjectDetail({
    project: {project_id: 'one', name: 'Project', visibility: 'PUBLIC'},
    locations: [{location_id: 'l1', location_type: 'DRIVE', drive_folder_url: 'https://example.invalid'}],
    resources: [{resource_id: 'r1', name: 'Master Sheet', resource_type: 'SHEET'}],
    deployments: [{deployment_id: 'd1', environment: 'PRODUCTION', deployment_url: 'https://example.invalid/app'}],
    connections: [{connection_id: 'c1', connection_type: 'READS'}],
  });
  assert.equal(detail.locations.length, 1);
  assert.equal(detail.resources.length, 1);
  assert.equal(detail.deployments.length, 1);
  assert.equal(detail.connections.length, 1);
});

test('Looker normalization supports ready stale offline and empty states without privileged defaults', () => {
  const client = loadClient();
  for (const state of ['READY', 'STALE', 'OFFLINE', 'EMPTY']) {
    const normalized = client.normalizeLooker({state, summary: {asset_counts: {view: 1}}});
    assert.equal(normalized.state, state);
    assert.equal(Object.hasOwn(normalized, 'owner_actions'), false);
  }
  assert.equal(client.normalizeLooker({state: 'UNKNOWN'}).state, 'EMPTY');
  assert.match(client.stateCopy('STALE').message, /verified refresh/i);
  assert.match(client.stateCopy('OFFLINE').title, /offline/i);
  assert.match(client.stateCopy('EMPTY').title, /No Looker/i);
});

test('Looker client allowlist drops provenance credentials and unissued Owner actions', () => {
  const client = loadClient();
  const value = client.normalizeLooker({state: 'READY', assets: [{looker_asset_id: 'a', name: 'orders', provenance_json: 'secret'}], summary: {credential_refs_json: 'secret'}, owner_actions: null});
  const rendered = JSON.stringify(value);
  assert.match(rendered, /orders/);
  assert.doesNotMatch(rendered, /provenance|credential_refs|secret|owner_actions/);
});
