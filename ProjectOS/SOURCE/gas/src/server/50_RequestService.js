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
