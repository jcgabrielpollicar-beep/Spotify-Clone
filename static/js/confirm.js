// Delete links carry data-confirm-delete (+ data-name, optional data-warning).
// Clicking one opens the small popup in base.html instead of going to the confirmation page;
// "Yes, delete" posts to the link's own URL, so the server-side delete view is unchanged.
// Without JavaScript the link still opens the normal confirmation page.
(function () {
  'use strict';

  var dialog = document.getElementById('confirm-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;   // old browser: keep the confirmation page

  var form = document.getElementById('confirm-form');
  var title = document.getElementById('confirm-title');
  var warning = document.getElementById('confirm-warning');
  var cancel = document.getElementById('confirm-cancel');

  document.addEventListener('click', function (event) {
    var link = event.target.closest('a[data-confirm-delete]');
    if (!link) return;
    // ctrl/shift/middle click: let the browser open the page the normal way
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;

    event.preventDefault();
    form.action = link.href;
    title.textContent = 'Delete “' + (link.dataset.name || 'this item') + '”?';
    warning.textContent = link.dataset.warning || '';
    warning.hidden = !link.dataset.warning;
    dialog.showModal();
    cancel.focus();                                 // the safe choice has focus, so Enter doesn't delete
  });

  cancel.addEventListener('click', function () { dialog.close(); });

  // click on the dimmed area outside the box closes it too (Esc is built in)
  dialog.addEventListener('click', function (event) {
    if (event.target === dialog) dialog.close();
  });
})();
