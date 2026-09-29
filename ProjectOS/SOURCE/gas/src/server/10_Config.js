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
