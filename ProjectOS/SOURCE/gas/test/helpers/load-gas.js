const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');

const GAS_ROOT = path.resolve(__dirname, '../..');

function loadGas(options = {}) {
  const order = JSON.parse(fs.readFileSync(path.join(GAS_ROOT, 'source-order.json'), 'utf8'));
  const state = {
    activeEmail: options.activeEmail || '',
    users: options.users || [],
    projects: options.projects || [],
    connections: options.connections || [],
    locations: options.locations || [],
    resources: options.resources || [],
    deployments: options.deployments || [],
    lookerAssets: options.lookerAssets || [],
    lookerRelationships: options.lookerRelationships || [],
    lookerFindings: options.lookerFindings || [],
    lookerAnalytics: options.lookerAnalytics || [],
    requests: [],
    drafts: [],
    accessEvents: [],
    queryCount: 0,
    lockCount: 0,
    menus: [],
  };
  const runtime = {
    activeEmail: () => state.activeEmail,
    findUserByEmail: (email) => state.users.find((user) => user.email === email) || null,
    queryProjects: () => { state.queryCount += 1; return structuredClone(state.projects); },
    queryConnections: () => { state.queryCount += 1; return structuredClone(state.connections); },
    queryLocations: () => { state.queryCount += 1; return structuredClone(state.locations); },
    queryResources: () => { state.queryCount += 1; return structuredClone(state.resources); },
    queryDeployments: () => { state.queryCount += 1; return structuredClone(state.deployments); },
    queryLookerAssets: () => { state.queryCount += 1; return structuredClone(state.lookerAssets); },
    queryLookerRelationships: () => { state.queryCount += 1; return structuredClone(state.lookerRelationships); },
    queryLookerFindings: () => { state.queryCount += 1; return structuredClone(state.lookerFindings); },
    queryLookerAnalytics: () => { state.queryCount += 1; return structuredClone(state.lookerAnalytics); },
    appendChangeRequest: (row) => state.requests.push(structuredClone(row)),
    appendOwnerDraft: (row) => state.drafts.push(structuredClone(row)),
    appendAccessEvent: (row) => state.accessEvents.push(structuredClone(row)),
    listConflicts: () => [],
    listUsers: () => structuredClone(state.users),
    auditSummary: () => [],
    settings: () => ({environment: 'TEST'}),
    activeRevision: () => options.activeRevision || null,
    uuid: () => `uuid-${state.requests.length + state.drafts.length + 1}`,
    now: () => '2026-09-26T12:00:00Z',
    sha256: (text) => crypto.createHash('sha256').update(text, 'utf8').digest('hex'),
    withLock: (callback) => { state.lockCount += 1; return callback(); },
    render: (name, model) => ({name, model}),
    addMenu: (items) => state.menus.push(items),
  };
  const context = vm.createContext({
    console,
    structuredClone,
    Session: {getActiveUser: () => ({getEmail: () => state.activeEmail})},
    PropertiesService: {getScriptProperties: () => ({getProperties: () => ({})})},
    Utilities: {
      getUuid: runtime.uuid,
      computeDigest: (_algorithm, text) => [...crypto.createHash('sha256').update(text).digest()],
      DigestAlgorithm: {SHA_256: 'SHA_256'},
    },
    LockService: {getScriptLock: () => ({tryLock: () => true, releaseLock: () => {}})},
    HtmlService: {createTemplateFromFile: () => ({evaluate: () => ({})})},
    SpreadsheetApp: {},
  });
  for (const source of order.server) {
    vm.runInContext(fs.readFileSync(path.join(GAS_ROOT, source), 'utf8'), context, {filename: source});
  }
  context.ProjectOS.runtime = runtime;
  return {context, state, ProjectOS: context.ProjectOS};
}

module.exports = {GAS_ROOT, loadGas};
