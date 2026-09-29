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
