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
