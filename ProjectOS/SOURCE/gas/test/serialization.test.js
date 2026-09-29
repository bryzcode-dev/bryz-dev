const test = require('node:test');
const assert = require('node:assert/strict');
const {loadGas} = require('./helpers/load-gas');

const users = [
  {email: 'owner@example.com', role: 'OWNER', active: true, protected_owner: true},
  {email: 'admin@example.com', role: 'ADMIN', active: true},
  {email: 'user@example.com', role: 'USER', active: true},
];
const projects = [
  {project_id: 'public-id', name: 'Public', description: 'safe', project_type: 'GAS', status: 'ACTIVE', visibility: 'PUBLIC', tags: '[]', version: 1, owner_notes: 'owner-only-note', machine_path: '/private/path'},
  {project_id: 'private-id', name: 'Private Codename', description: 'hidden', project_type: 'LOCAL', status: 'ACTIVE', visibility: 'PRIVATE', tags: '[]', version: 1, owner_notes: 'private-note'},
];

test('User and Admin receive PUBLIC safe DTOs while Owner receives authorized private fields', () => {
  for (const role of ['user', 'admin']) {
    const {context} = loadGas({activeEmail: `${role}@example.com`, users, projects});
    const result = context.listProjects();
    assert.equal(result.ok, true);
    assert.equal(result.data.length, 1);
    assert.equal(result.data[0].name, 'Public');
    const rendered = JSON.stringify(result);
    assert.doesNotMatch(rendered, /Private Codename|private-note|owner-only-note|private\/path/);
  }
  const {context} = loadGas({activeEmail: 'owner@example.com', users, projects});
  const result = context.listProjects();
  assert.equal(result.data.length, 2);
  assert.equal(result.data.find((item) => item.project_id === 'private-id').owner.owner_notes, 'private-note');
});

test('search, counts, and connections cannot reveal a hidden endpoint', () => {
  const connections = [
    {connection_id: 'safe-edge', source_project_id: 'public-id', target_project_id: 'public-id', connection_type: 'READS'},
    {connection_id: 'hidden-edge', source_project_id: 'public-id', target_project_id: 'private-id', connection_type: 'READS'},
  ];
  const {context} = loadGas({activeEmail: 'admin@example.com', users, projects, connections});
  assert.equal(context.searchProjects('Private Codename').data.length, 0);
  assert.equal(context.getProjectCounts().data.total, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(context.listConnections().data)).map((item) => item.connection_id), ['safe-edge']);
});

test('only the verified active projection revision is serialized', () => {
  const revisioned = [
    {...projects[0], project_id: 'active-project', name: 'Active Project', projection_revision: 'active-v1'},
    {...projects[0], project_id: 'staged-project', name: 'Staged Project', projection_revision: 'staged-v2'},
  ];
  const {context} = loadGas({
    activeEmail: 'admin@example.com', users, projects: revisioned, activeRevision: 'active-v1'
  });
  const result = context.listProjects();
  assert.deepEqual(JSON.parse(JSON.stringify(result.data)).map((item) => item.project_id), ['active-project']);
  assert.doesNotMatch(JSON.stringify(result), /Staged Project|staged-project/);
});

test('project details expose child records through role-safe field sets', () => {
  const options = {
    users,
    projects: [{project_id: 'public', name: 'Public', project_type: 'GAS', status: 'ACTIVE', visibility: 'PUBLIC', version: 1}],
    locations: [{location_id: 'loc', project_id: 'public', location_type: 'LOCAL', path: '/sensitive/path', drive_folder_url: 'https://drive.invalid/folder', environment: 'DEV', status: 'ACTIVE'}],
    resources: [{resource_id: 'res', project_id: 'public', resource_type: 'SHEET', provider: 'GOOGLE', external_id: 'sensitive-id', name: 'Master', url: 'https://sheets.invalid', environment: 'DEV', role: 'USES', status: 'ACTIVE'}],
    deployments: [{deployment_id: 'dep', project_id: 'public', environment: 'PRODUCTION', script_id: 'sensitive-script', external_deployment_id: 'sensitive-deploy', deployment_url: 'https://app.invalid', active_version: '7', status: 'ACTIVE'}],
  };
  const admin = loadGas({...options, activeEmail: 'admin@example.com'}).context.getProjectDetails('public');
  const owner = loadGas({...options, activeEmail: 'owner@example.com'}).context.getProjectDetails('public');
  const adminJson = JSON.stringify(admin);
  assert.equal(admin.ok, true);
  assert.doesNotMatch(adminJson, /sensitive-path|sensitive-id|sensitive-script|sensitive-deploy/);
  assert.match(JSON.stringify(owner), /sensitive-script/);
});

test('serialized project detail includes only role-safe Looker fields', () => {
  const lookerAssets = [{looker_asset_id: 'a', project_id: 'public', asset_type: 'view', name: 'orders', file_path: 'orders.view.lkml'}];
  const lookerRelationships = [{relationship_id: 'r', project_id: 'public', relationship_type: 'explore_view', source_type: 'explore', source_name: 'orders', target_type: 'view', target_name: 'orders'}];
  const lookerFindings = [{finding_id: 'f', project_id: 'public', severity: 'WARNING', code: 'UNRESOLVED_REFERENCE', subject: 'view:missing', status: 'OPEN'}];
  const lookerAnalytics = [{analytic_id: 's', project_id: 'public', analytic_type: 'LOOKER_SUMMARY', value_json: JSON.stringify({version: 1, data: {asset_counts: {view: 1}}}), source_run_id: 'run'}];
  const base = {users, projects: [{project_id: 'public', name: 'Public', project_type: 'LOOKER', status: 'ACTIVE', visibility: 'PUBLIC', version: 1}], lookerAssets, lookerRelationships, lookerFindings, lookerAnalytics};
  const result = loadGas({...base, activeEmail: 'admin@example.com'}).context.getProjectDetails('public');
  const rendered = JSON.stringify(result);
  assert.match(rendered, /"looker"/);
  assert.doesNotMatch(rendered, /provenance_json|credential_refs_json|legacy_json|archive_sha256/);
});
