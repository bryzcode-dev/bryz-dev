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
