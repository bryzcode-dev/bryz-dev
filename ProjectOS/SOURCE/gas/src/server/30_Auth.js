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
