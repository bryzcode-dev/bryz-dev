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
