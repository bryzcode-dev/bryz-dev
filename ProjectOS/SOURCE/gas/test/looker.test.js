const test = require('node:test');
const assert = require('node:assert/strict');
const {loadGas} = require('./helpers/load-gas');

const users = [
  {email: 'owner@example.com', role: 'OWNER', active: true, protected_owner: true},
  {email: 'admin@example.com', role: 'ADMIN', active: true},
  {email: 'user@example.com', role: 'USER', active: true},
];
const projects = [
  {project_id: 'public-id', name: 'Public Looker', project_type: 'LOOKER', status: 'ACTIVE', visibility: 'PUBLIC', version: 1, projection_revision: 'active'},
  {project_id: 'private-id', name: 'Private Payroll', project_type: 'LOOKER', status: 'ACTIVE', visibility: 'PRIVATE', version: 1, projection_revision: 'active'},
];
const options = {
  users, projects, activeRevision: 'active',
  lookerAssets: [
    {looker_asset_id: 'public-view', project_id: 'public-id', asset_type: 'view', name: 'orders', file_path: 'orders.view.lkml', projection_revision: 'active'},
    {looker_asset_id: 'private-view', project_id: 'private-id', asset_type: 'view', name: 'payroll', file_path: 'payroll.view.lkml', projection_revision: 'active'},
  ],
  lookerRelationships: [
    {relationship_id: 'public-edge', project_id: 'public-id', relationship_type: 'explore_view', source_type: 'explore', source_name: 'orders', target_type: 'view', target_name: 'orders', projection_revision: 'active'},
    {relationship_id: 'private-edge', project_id: 'private-id', relationship_type: 'explore_view', source_type: 'explore', source_name: 'payroll', target_type: 'view', target_name: 'payroll', projection_revision: 'active'},
  ],
  lookerFindings: [
    {finding_id: 'public-finding', project_id: 'public-id', severity: 'WARNING', code: 'UNRESOLVED_REFERENCE', subject: 'view:missing', status: 'OPEN', projection_revision: 'active'},
    {finding_id: 'private-finding', project_id: 'private-id', severity: 'IMPORTANT', code: 'PRIVATE_CODE', subject: 'Private Payroll', status: 'OPEN', projection_revision: 'active'},
  ],
  lookerAnalytics: [
    {analytic_id: 'public-summary', project_id: 'public-id', analytic_type: 'LOOKER_SUMMARY', value_json: JSON.stringify({version: 1, data: {asset_counts: {view: 1}, git: {branch: 'main', dirty: false}, code_status: 'PASS', refresh_status: 'UNAVAILABLE', migration_version: 3}}), source_run_id: 'public-run', created_at: '2026-09-27T12:00:00Z', projection_revision: 'active'},
    {analytic_id: 'public-graph', project_id: 'public-id', analytic_type: 'LOOKER_GRAPH', value_json: JSON.stringify({version: 1, data: {forward: {'explore:orders': ['view:orders']}, reverse: {'view:orders': ['explore:orders']}}}), source_run_id: 'public-run', created_at: '2026-09-27T12:00:00Z', projection_revision: 'active'},
    {analytic_id: 'private-summary', project_id: 'private-id', analytic_type: 'LOOKER_SUMMARY', value_json: JSON.stringify({version: 1, data: {asset_counts: {view: 99}, git: {branch: 'private-payroll'}}}), source_run_id: 'private-run', created_at: '2026-09-27T12:00:00Z', projection_revision: 'active'},
  ],
};

test('server-issued Looker capabilities follow Owner Admin User matrix', () => {
  const owner = loadGas({...options, activeEmail: 'owner@example.com'}).context.getSession().data;
  const admin = loadGas({...options, activeEmail: 'admin@example.com'}).context.getSession().data;
  const user = loadGas({...options, activeEmail: 'user@example.com'}).context.getSession().data;
  assert.deepEqual(JSON.parse(JSON.stringify(owner.looker)), {view: true, edit: true, import: true, reconcile: true, cutover: true});
  assert.deepEqual(JSON.parse(JSON.stringify(admin.looker)), {view: true, edit: true, import: false, reconcile: false, cutover: false});
  assert.deepEqual(JSON.parse(JSON.stringify(user.looker)), {view: true, edit: false, import: false, reconcile: false, cutover: false});
});

test('Looker DTOs expose role-safe PUBLIC analytics and PRIVATE only to Owner', () => {
  const adminContext = loadGas({...options, activeEmail: 'admin@example.com'}).context;
  const admin = adminContext.getProjectDetails('public-id');
  assert.equal(admin.ok, true);
  assert.equal(admin.data.looker.assets[0].name, 'orders');
  assert.deepEqual(JSON.parse(JSON.stringify(admin.data.looker.graph.forward)), {'explore:orders': ['view:orders']});
  const userContext = loadGas({...options, activeEmail: 'user@example.com'}).context;
  const user = userContext.getProjectDetails('public-id');
  assert.equal(user.data.looker.summary.asset_counts.view, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(user.data.looker.assets)), []);
  assert.deepEqual(JSON.parse(JSON.stringify(user.data.looker.findings)), []);
  assert.deepEqual(JSON.parse(JSON.stringify(user.data.looker.graph)), {forward: {}, reverse: {}});
  for (const context of [adminContext, userContext]) {
    const rendered = JSON.stringify(context.getProjectDetails('public-id'));
    assert.doesNotMatch(rendered, /Private Payroll|payroll|private-run|99/);
    const denied = context.getProjectDetails('private-id');
    assert.deepEqual(JSON.parse(JSON.stringify(denied)), {ok: false, error: {code: 'NOT_FOUND', message: 'Record not found'}});
  }
  const owner = loadGas({...options, activeEmail: 'owner@example.com'}).context.getProjectDetails('private-id');
  assert.equal(owner.ok, true);
  assert.equal(owner.data.looker.assets[0].name, 'payroll');
});

test('Looker detail ignores staged rows and malformed analytics without disclosing errors', () => {
  const staged = {...options, activeEmail: 'admin@example.com', lookerAnalytics: [
    ...options.lookerAnalytics,
    {analytic_id: 'staged', project_id: 'public-id', analytic_type: 'LOOKER_SUMMARY', value_json: '{not-json', source_run_id: 'staged-secret', projection_revision: 'staged'},
  ]};
  const result = loadGas(staged).context.getProjectDetails('public-id');
  assert.equal(result.ok, true);
  assert.equal(result.data.looker.state, 'READY');
  assert.doesNotMatch(JSON.stringify(result), /staged-secret|not-json/);
});

test('empty Looker project has explicit safe state and Owner actions never reach non-Owners', () => {
  const empty = {...options, lookerAssets: [], lookerRelationships: [], lookerFindings: [], lookerAnalytics: []};
  const admin = loadGas({...empty, activeEmail: 'admin@example.com'}).context.getProjectDetails('public-id').data.looker;
  const owner = loadGas({...empty, activeEmail: 'owner@example.com'}).context.getProjectDetails('public-id').data.looker;
  assert.equal(admin.state, 'EMPTY');
  assert.equal(Object.hasOwn(admin, 'owner_actions'), false);
  assert.deepEqual(JSON.parse(JSON.stringify(owner.owner_actions)), {can_import: true, can_reconcile: true, can_cutover: true});
});
