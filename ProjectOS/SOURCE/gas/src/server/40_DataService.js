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
