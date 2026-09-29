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
