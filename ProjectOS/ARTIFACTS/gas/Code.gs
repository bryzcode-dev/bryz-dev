// source: src/server/00_Namespace.js
var ProjectOS = ProjectOS || {};

ProjectOS.version = '0.1.0';
ProjectOS.runtime = ProjectOS.runtime || null;
ProjectOS.denied = function () {
  return {ok: false, error: {code: 'ACCESS_DENIED', message: 'Access denied'}};
};
ProjectOS.notFound = function () {
  return {ok: false, error: {code: 'NOT_FOUND', message: 'Record not found'}};
};
ProjectOS.ok = function (data) { return {ok: true, data: data}; };
ProjectOS.fail = function (code, message) {
  return {ok: false, error: {code: code, message: message}};
};

// source: src/server/10_Config.js
ProjectOS.Config = (function () {
  'use strict';
  var REQUIRED = ['SPREADSHEET_ID', 'OWNER_EMAIL', 'CONTRACT_VERSION', 'ENVIRONMENT', 'DEPLOYMENT_ID'];

  function read() {
    var values = PropertiesService.getScriptProperties().getProperties();
    var missing = REQUIRED.filter(function (name) { return !String(values[name] || '').trim(); });
    if (missing.length) throw new Error('CONFIGURATION_REQUIRED');
    return {
      spreadsheetId: String(values.SPREADSHEET_ID),
      ownerEmail: String(values.OWNER_EMAIL).trim().toLowerCase(),
      contractVersion: Number(values.CONTRACT_VERSION),
      environment: String(values.ENVIRONMENT),
      deploymentId: String(values.DEPLOYMENT_ID)
    };
  }
  return {read: read, requiredKeys: function () { return REQUIRED.slice(); }};
}());

// source: src/server/20_Contract.js
ProjectOS.Contract = (function () {
  'use strict';
  var ADMIN_FIELDS = {
    project: ['name', 'description', 'status', 'tags'],
    location: ['drive_folder_url', 'environment', 'discovery_status'],
    resource: ['name', 'url', 'environment', 'role', 'status', 'metadata'],
    deployment: ['environment', 'deployment_url', 'active_version', 'status', 'notes'],
    connection: ['connection_type', 'implementation_method', 'purpose', 'notes', 'status']
  };

  function normalize(value) {
    if (Array.isArray(value)) return value.map(normalize);
    if (value && Object.prototype.toString.call(value) === '[object Object]') {
      var ordered = {};
      Object.keys(value).sort().forEach(function (key) { ordered[key] = normalize(value[key]); });
      return ordered;
    }
    return value;
  }
  function canonicalJson(value) { return JSON.stringify(normalize(value)); }
  function sha256(value) {
    var text = canonicalJson(value);
    if (ProjectOS.runtime && ProjectOS.runtime.sha256) return ProjectOS.runtime.sha256(text);
    return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text)
      .map(function (item) { return ((item + 256) % 256).toString(16).padStart(2, '0'); }).join('');
  }
  function adminFields(entityType) { return (ADMIN_FIELDS[entityType] || []).slice(); }
  function lookerCapabilities(context) {
    var owner = Boolean(context && context.protectedOwner && context.role === 'OWNER');
    var admin = Boolean(context && context.role === 'ADMIN');
    return {view: Boolean(context && context.authorized), edit: owner || admin, import: owner, reconcile: owner, cutover: owner};
  }
  return {version: 1, canonicalJson: canonicalJson, sha256: sha256, adminFields: adminFields, lookerCapabilities: lookerCapabilities};
}());

// source: src/server/30_Auth.js
ProjectOS.Auth = (function () {
  'use strict';
  var EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  var CAPABILITIES = {
    OWNER: {viewPrivate: true, canEdit: true, adminMenu: true, manageUsers: true},
    ADMIN: {viewPrivate: false, canEdit: true, adminMenu: false, manageUsers: false},
    USER: {viewPrivate: false, canEdit: false, adminMenu: false, manageUsers: false}
  };

  function resolve() {
    var runtime = ProjectOS.DataService.runtime();
    var email = String(runtime.activeEmail() || '').trim().toLowerCase();
    if (!EMAIL.test(email)) return {authorized: false, capabilities: {}};
    var user = runtime.findUserByEmail(email);
    if (!user || !user.active || !CAPABILITIES[user.role]) return {authorized: false, capabilities: {}};
    var capabilities = CAPABILITIES[user.role];
    return {
      authorized: true,
      email: email,
      role: user.role,
      protectedOwner: user.role === 'OWNER' && user.protected_owner === true,
      canEdit: capabilities.canEdit,
      adminMenu: capabilities.adminMenu,
      manageUsers: capabilities.manageUsers,
      viewPrivate: capabilities.viewPrivate
    };
  }
  function requireOwner(context) {
    return Boolean(context && context.authorized && context.protectedOwner && context.role === 'OWNER');
  }
  return {resolve: resolve, requireOwner: requireOwner};
}());

// source: src/server/40_DataService.js
ProjectOS.DataService = (function () {
  'use strict';

  function defaultRuntime() {
    function config() { return ProjectOS.Config.read(); }
    function sheet(name) {
      var value = SpreadsheetApp.openById(config().spreadsheetId).getSheetByName(name);
      if (!value) throw new Error('WORKBOOK_CONTRACT_INVALID');
      return value;
    }
    function rows(name) {
      var values = sheet(name).getDataRange().getValues();
      if (!values.length) return [];
      var headers = values[0].map(String);
      return values.slice(1).map(function (row) {
        var item = {};
        headers.forEach(function (header, index) { item[header] = row[index]; });
        return item;
      });
    }
    function append(name, value) {
      var target = sheet(name);
      var headers = target.getRange(1, 1, 1, target.getLastColumn()).getValues()[0].map(String);
      target.appendRow(headers.map(function (header) { return value[header] === undefined ? '' : value[header]; }));
    }
    function withLock(callback) {
      var lock = LockService.getScriptLock();
      if (!lock.tryLock(10000)) throw new Error('LOCK_UNAVAILABLE');
      try { return callback(); } finally { lock.releaseLock(); }
    }
    return {
      activeEmail: function () { return Session.getActiveUser().getEmail(); },
      findUserByEmail: function (email) {
        return rows('Users').find(function (user) { return String(user.email).toLowerCase() === email; }) || null;
      },
      queryProjects: function () { return rows('Projects'); },
      queryConnections: function () { return rows('Connections'); },
      queryLocations: function () { return rows('Locations'); },
      queryResources: function () { return rows('Resources'); },
      queryDeployments: function () { return rows('Deployments'); },
      queryLookerAssets: function () { return rows('Looker_Assets'); },
      queryLookerRelationships: function () { return rows('Looker_Relationships'); },
      queryLookerFindings: function () { return rows('Looker_Findings'); },
      queryLookerAnalytics: function () { return rows('Looker_Analytics'); },
      appendChangeRequest: function (value) { append('Change_Requests', value); },
      appendOwnerDraft: function (value) { append('Owner_Drafts', value); },
      appendAccessEvent: function (value) { append('Access_Events', value); },
      listConflicts: function () { return rows('Conflicts'); },
      listUsers: function () { return rows('Users'); },
      auditSummary: function () { return rows('Audit_Summary'); },
      settings: function () { var value = config(); return {environment: value.environment, contractVersion: value.contractVersion}; },
      activeRevision: function () {
        var schema = rows('_ProjectOS_Schema');
        return schema.length ? String(schema[0].active_projection_revision || '') : '';
      },
      uuid: function () { return Utilities.getUuid(); },
      now: function () { return new Date().toISOString(); },
      withLock: withLock,
      render: function (name, model) { var template = HtmlService.createTemplateFromFile(name); template.model = model; return template.evaluate(); },
      addMenu: function (items) {
        var menu = SpreadsheetApp.getUi().createMenu('ProjectOS');
        items.forEach(function (item) { menu.addItem(item.label, item.functionName); });
        menu.addToUi();
      }
    };
  }
  function runtime() { return ProjectOS.runtime || defaultRuntime(); }
  function visibleProjects(context) {
    if (!context.authorized) return [];
    var service = runtime();
    var activeRevision = service.activeRevision ? service.activeRevision() : null;
    return service.queryProjects().filter(function (project) {
      if (activeRevision && project.projection_revision !== activeRevision) return false;
      return project.visibility === 'PUBLIC' || (context.viewPrivate && project.visibility === 'PRIVATE');
    });
  }
  function projectDto(context, project) {
    var dto = {
      project_id: project.project_id,
      name: project.name,
      description: project.description || '',
      project_type: project.project_type,
      status: project.status,
      visibility: project.visibility,
      tags: project.tags || '[]',
      version: Number(project.version)
    };
    if (context.role === 'OWNER') {
      dto.owner = {
        owner_notes: project.owner_notes || '',
        context_os_registered: Boolean(project.context_os_registered),
        context_os_project_id: project.context_os_project_id || null
      };
    }
    return dto;
  }
  function listProjects(context) { return visibleProjects(context).map(function (item) { return projectDto(context, item); }); }
  function searchProjects(context, query) {
    var needle = String(query || '').toLowerCase();
    return listProjects(context).filter(function (project) {
      return [project.name, project.description, project.project_type, project.status, project.tags]
        .join(' ').toLowerCase().indexOf(needle) >= 0;
    });
  }
  function projectCounts(context) {
    var projects = listProjects(context);
    var byStatus = {};
    projects.forEach(function (project) { byStatus[project.status] = (byStatus[project.status] || 0) + 1; });
    return {total: projects.length, by_status: byStatus};
  }
  function connections(context) {
    var service = runtime();
    var activeRevision = service.activeRevision ? service.activeRevision() : null;
    var visible = {};
    visibleProjects(context).forEach(function (project) { visible[project.project_id] = true; });
    return service.queryConnections().filter(function (connection) {
      if (activeRevision && connection.projection_revision !== activeRevision) return false;
      return (!connection.source_project_id || visible[connection.source_project_id]) &&
        (!connection.target_project_id || visible[connection.target_project_id]);
    }).map(function (connection) {
      return {
        connection_id: connection.connection_id,
        source_project_id: connection.source_project_id || null,
        target_project_id: connection.target_project_id || null,
        connection_type: connection.connection_type,
        status: connection.status || 'ACTIVE'
      };
    });
  }
  function childRows(context, method, projectId) {
    var service = runtime();
    var activeRevision = service.activeRevision ? service.activeRevision() : null;
    var visible = visibleProjects(context).some(function (project) { return project.project_id === projectId; });
    if (!visible || typeof service[method] !== 'function') return [];
    return service[method]().filter(function (row) {
      return row.project_id === projectId && (!activeRevision || row.projection_revision === activeRevision);
    });
  }
  function locations(context, projectId) {
    return childRows(context, 'queryLocations', projectId).map(function (row) {
      var dto = {location_id: row.location_id, location_type: row.location_type, drive_folder_url: row.drive_folder_url || null, environment: row.environment || '', status: row.status || 'ACTIVE'};
      if (context.role === 'OWNER') Object.assign(dto, {machine_id: row.machine_id || '', path: row.path || null, repository_root: row.repository_root || null, drive_folder_id: row.drive_folder_id || null});
      return dto;
    });
  }
  function resources(context, projectId) {
    return childRows(context, 'queryResources', projectId).map(function (row) {
      var dto = {resource_id: row.resource_id, resource_type: row.resource_type, provider: row.provider, name: row.name, url: row.url || null, environment: row.environment || '', role: row.role || 'USES', status: row.status || 'ACTIVE'};
      if (context.role === 'OWNER') Object.assign(dto, {external_id: row.external_id || null, metadata_json: row.metadata_json || '{}'});
      return dto;
    });
  }
  function deployments(context, projectId) {
    return childRows(context, 'queryDeployments', projectId).map(function (row) {
      var dto = {deployment_id: row.deployment_id, environment: row.environment, deployment_url: row.deployment_url || null, active_version: row.active_version || null, status: row.status || 'ACTIVE'};
      if (context.role === 'OWNER') Object.assign(dto, {script_id: row.script_id || null, external_deployment_id: row.external_deployment_id || null, resource_id: row.resource_id || null});
      return dto;
    });
  }
  function safeJson(value) {
    try {
      var parsed = JSON.parse(String(value || ''));
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch (error) { return null; }
  }
  function latestAnalytic(rows, kind) {
    return rows.filter(function (row) { return row.analytic_type === kind; }).map(function (row) {
      var value = safeJson(row.value_json);
      return value && value.data && Number.isFinite(Number(value.version)) ? {version: Number(value.version), data: value.data} : null;
    }).filter(Boolean).sort(function (left, right) { return left.version - right.version; }).pop() || null;
  }
  function summaryDto(context, value) {
    var source = value || {};
    var result = {asset_counts: source.asset_counts || {}, code_status: source.code_status || 'UNKNOWN', refresh_status: source.refresh_status || 'UNAVAILABLE', migration_version: Number(source.migration_version || 0)};
    if (context.role !== 'USER') Object.assign(result, {dependency_counts: source.dependency_counts || {}, finding_counts: source.finding_counts || {}, git: source.git || {}, validation: source.validation || {}});
    if (context.protectedOwner && context.role === 'OWNER') Object.assign(result, {credential_usage: source.credential_usage || {}, import: source.import || {}, legacy: source.legacy || {}, parser_versions: source.parser_versions || []});
    return result;
  }
  function lookerDetails(context, projectId) {
    var assets = childRows(context, 'queryLookerAssets', projectId).map(function (row) {
      return {looker_asset_id: row.looker_asset_id, asset_type: row.asset_type, name: row.name, file_path: row.file_path || '', version: Number(row.version || 1)};
    });
    var relationships = childRows(context, 'queryLookerRelationships', projectId).map(function (row) {
      return {relationship_id: row.relationship_id, relationship_type: row.relationship_type, source_type: row.source_type, source_name: row.source_name, target_type: row.target_type, target_name: row.target_name};
    });
    var findings = childRows(context, 'queryLookerFindings', projectId).map(function (row) {
      return {finding_id: row.finding_id, severity: row.severity, code: row.code, subject: row.subject, status: row.status};
    });
    var analyticRows = childRows(context, 'queryLookerAnalytics', projectId);
    var summary = latestAnalytic(analyticRows, 'LOOKER_SUMMARY');
    var graph = latestAnalytic(analyticRows, 'LOOKER_GRAPH');
    var state = 'READY';
    if (!assets.length && !relationships.length && !findings.length && !summary && !graph) state = 'EMPTY';
    else if (summary && summary.data.refresh_status === 'OFFLINE') state = 'OFFLINE';
    else if (summary && summary.data.refresh_status === 'STALE') state = 'STALE';
    var detailed = context.role !== 'USER';
    var result = {state: state, assets: detailed ? assets : [], relationships: detailed ? relationships : [], findings: detailed ? findings : [], summary: summaryDto(context, summary ? summary.data : {}), graph: detailed && graph ? graph.data : {forward: {}, reverse: {}}};
    if (context.protectedOwner && context.role === 'OWNER') result.owner_actions = {can_import: true, can_reconcile: true, can_cutover: true};
    return result;
  }
  function projectDetails(context, projectId) {
    var project = listProjects(context).find(function (item) { return item.project_id === projectId; });
    if (!project) return null;
    return {
      project: project,
      locations: locations(context, projectId),
      resources: resources(context, projectId),
      deployments: deployments(context, projectId),
      connections: connections(context).filter(function (item) { return item.source_project_id === projectId || item.target_project_id === projectId; }),
      looker: lookerDetails(context, projectId)
    };
  }
  return {
    runtime: runtime,
    visibleProjects: visibleProjects,
    listProjects: listProjects,
    searchProjects: searchProjects,
    projectCounts: projectCounts,
    connections: connections,
    projectDetails: projectDetails,
    lookerDetails: lookerDetails
  };
}());

// source: src/server/50_RequestService.js
ProjectOS.RequestService = (function () {
  'use strict';
  var OPERATIONS = {CREATE: true, UPDATE: true, ARCHIVE: true};
  var SENSITIVE = /password|secret|token|private.?key|api.?key|refresh.?token|recovery.?code/i;

  function containsSecret(value) {
    if (Array.isArray(value)) return value.some(containsSecret);
    if (value && typeof value === 'object') {
      return Object.keys(value).some(function (key) { return SENSITIVE.test(key) || containsSecret(value[key]); });
    }
    return typeof value === 'string' && (/-----BEGIN .*PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9_]{20,}\b|\bAIza[0-9A-Za-z_-]{20,}\b/.test(value));
  }
  function projectById(context, entityId) {
    return ProjectOS.DataService.visibleProjects(context).find(function (project) { return project.project_id === entityId; }) || null;
  }
  function allowed(context, payload) {
    if (!context.authorized || !context.canEdit || !OPERATIONS[payload.operation]) return false;
    if (!payload.changes || typeof payload.changes !== 'object' || Array.isArray(payload.changes)) return false;
    if (containsSecret(payload.changes)) return false;
    if (context.role === 'OWNER') return true;
    if (context.role !== 'ADMIN' || payload.entity_type === 'user') return false;
    var project = payload.entity_type === 'project' ? projectById(context, payload.entity_id) : {visibility: 'PUBLIC'};
    if (!project || project.visibility !== 'PUBLIC') return false;
    var allowedFields = ProjectOS.Contract.adminFields(payload.entity_type);
    return Object.keys(payload.changes).every(function (field) { return allowedFields.indexOf(field) >= 0; });
  }
  function submit(context, payload) {
    var normalized = {
      entity_type: String(payload.entity_type || '').toLowerCase(),
      entity_id: payload.entity_id || '',
      operation: String(payload.operation || '').toUpperCase(),
      base_version: Number(payload.base_version || 0),
      changes: payload.changes || {}
    };
    if (!allowed(context, normalized)) return ProjectOS.denied();
    var runtime = ProjectOS.DataService.runtime();
    var requestId = runtime.uuid();
    var request = {
      request_id: requestId,
      request_schema_version: 1,
      actor_email: context.email,
      actor_role_claim: context.role,
      entity_type: normalized.entity_type,
      entity_id: normalized.entity_id,
      operation: normalized.operation,
      base_version: normalized.base_version,
      changes: normalized.changes,
      submitted_at: runtime.now()
    };
    request.client_request_hash = ProjectOS.Contract.sha256(request);
    var row = Object.assign({}, request, {changes_json: ProjectOS.Contract.canonicalJson(request.changes), status: 'PENDING'});
    delete row.changes;
    runtime.withLock(function () { runtime.appendChangeRequest(row); });
    return {ok: true, request_id: requestId, status: 'PENDING'};
  }
  function ownerDraft(context, payload) {
    if (!ProjectOS.Auth.requireOwner(context)) return ProjectOS.denied();
    var runtime = ProjectOS.DataService.runtime();
    var draft = Object.assign({}, payload, {draft_id: runtime.uuid(), draft_status: 'DRAFT', updated_at: runtime.now()});
    runtime.withLock(function () { runtime.appendOwnerDraft(draft); });
    return {ok: true, draft_id: draft.draft_id, status: 'DRAFTED'};
  }
  function userChange(context, payload) {
    if (!ProjectOS.Auth.requireOwner(context)) return ProjectOS.denied();
    return submit(context, Object.assign({}, payload, {entity_type: 'user', operation: payload.operation || 'UPDATE'}));
  }
  function recordAccess(context) {
    if (!context.authorized) return ProjectOS.denied();
    var runtime = ProjectOS.DataService.runtime();
    var event = {event_id: runtime.uuid(), actor_email: context.email, accessed_at: runtime.now()};
    event.payload_hash = ProjectOS.Contract.sha256(event);
    runtime.withLock(function () { runtime.appendAccessEvent(event); });
    return ProjectOS.ok({status: 'RECORDED'});
  }
  return {submit: submit, ownerDraft: ownerDraft, userChange: userChange, recordAccess: recordAccess};
}());

// source: src/server/60_AdminService.js
ProjectOS.AdminService = (function () {
  'use strict';
  function ownerOnly(context, loader) {
    if (!ProjectOS.Auth.requireOwner(context)) return ProjectOS.denied();
    return ProjectOS.ok(loader());
  }
  return {
    conflicts: function (context) { return ownerOnly(context, function () { return ProjectOS.DataService.runtime().listConflicts(); }); },
    users: function (context) { return ownerOnly(context, function () { return ProjectOS.DataService.runtime().listUsers(); }); },
    audit: function (context) { return ownerOnly(context, function () { return ProjectOS.DataService.runtime().auditSummary(); }); },
    settings: function (context) { return ownerOnly(context, function () { return ProjectOS.DataService.runtime().settings(); }); }
  };
}());

// source: src/server/70_Menu.js
ProjectOS.Menu = (function () {
  'use strict';
  function itemsFor(context) {
    if (!ProjectOS.Auth.requireOwner(context)) return [];
    return [
      {label: 'Open ProjectOS', functionName: 'showProjectOS'},
      {label: 'Submit selected draft', functionName: 'submitSelectedOwnerDraft'},
      {label: 'View sync status', functionName: 'showProjectOSStatus'}
    ];
  }
  function onOpen() {
    var context = ProjectOS.Auth.resolve();
    var items = itemsFor(context);
    if (items.length) ProjectOS.DataService.runtime().addMenu(items);
  }
  return {itemsFor: itemsFor, onOpen: onOpen};
}());

// source: src/server/90_Entry.js
ProjectOS.Entry = (function () {
  'use strict';
  function run(callback) {
    try {
      var context = ProjectOS.Auth.resolve();
      if (!context.authorized) return ProjectOS.denied();
      return callback(context);
    } catch (error) {
      return ProjectOS.fail('SERVER_ERROR', 'ProjectOS is temporarily unavailable');
    }
  }
  return {run: run};
}());

function doGet() { return ProjectOS.DataService.runtime().render('index', {version: ProjectOS.version}); }
function include(filename) { return HtmlService.createHtmlOutputFromFile(filename).getContent(); }
function getSession() {
  return ProjectOS.Entry.run(function (context) {
    return ProjectOS.ok({role: context.role, canEdit: context.canEdit, adminMenu: context.adminMenu, looker: ProjectOS.Contract.lookerCapabilities(context)});
  });
}
function listProjects() { return ProjectOS.Entry.run(function (context) { return ProjectOS.ok(ProjectOS.DataService.listProjects(context)); }); }
function searchProjects(query) { return ProjectOS.Entry.run(function (context) { return ProjectOS.ok(ProjectOS.DataService.searchProjects(context, query)); }); }
function getProjectCounts() { return ProjectOS.Entry.run(function (context) { return ProjectOS.ok(ProjectOS.DataService.projectCounts(context)); }); }
function listConnections() { return ProjectOS.Entry.run(function (context) { return ProjectOS.ok(ProjectOS.DataService.connections(context)); }); }
function getProjectDetails(projectId) {
  return ProjectOS.Entry.run(function (context) {
    var details = ProjectOS.DataService.projectDetails(context, projectId);
    return details ? ProjectOS.ok(details) : ProjectOS.notFound();
  });
}
function getSyncStatus() { return ProjectOS.Entry.run(function (context) { return ProjectOS.ok(ProjectOS.DataService.runtime().settings()); }); }
function submitChangeRequest(payload) { return ProjectOS.Entry.run(function (context) { return ProjectOS.RequestService.submit(context, payload || {}); }); }
function submitOwnerDraft(payload) { return ProjectOS.Entry.run(function (context) { return ProjectOS.RequestService.ownerDraft(context, payload || {}); }); }
function submitUserChangeRequest(payload) { return ProjectOS.Entry.run(function (context) { return ProjectOS.RequestService.userChange(context, payload || {}); }); }
function recordAccessEvent() { return ProjectOS.Entry.run(function (context) { return ProjectOS.RequestService.recordAccess(context); }); }
function listConflicts() { return ProjectOS.Entry.run(function (context) { return ProjectOS.AdminService.conflicts(context); }); }
function listUsers() { return ProjectOS.Entry.run(function (context) { return ProjectOS.AdminService.users(context); }); }
function getAuditSummary() { return ProjectOS.Entry.run(function (context) { return ProjectOS.AdminService.audit(context); }); }
function getSettings() { return ProjectOS.Entry.run(function (context) { return ProjectOS.AdminService.settings(context); }); }
function onOpen() { return ProjectOS.Menu.onOpen(); }
