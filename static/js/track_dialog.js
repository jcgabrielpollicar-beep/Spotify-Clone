// Links with data-track-form (Add track / Edit track) open a popup instead of a new page.
// The form fields come from the same Django view (asked with an X-Requested-With header);
// submitting posts to that same URL. On success the page reloads; on errors the fields are
// shown again with the messages. Without JavaScript the link just opens the normal page.
(function () {
  'use strict';

  var dialog = document.getElementById('track-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;

  var form = document.getElementById('track-form');
  var body = document.getElementById('track-dialog-body');
  var HEADERS = { 'X-Requested-With': 'XMLHttpRequest' };

  function focusFirst() {
    var first = body.querySelector('.errorlist ~ input, .errorlist ~ select, input[type=text], input, select');
    var withError = body.querySelector('.field .errorlist');
    if (withError) {
      var near = withError.parentElement.querySelector('input, select, textarea');
      if (near) first = near;
    }
    if (first) first.focus();
  }

  function open(url) {
    fetch(url, { headers: HEADERS, credentials: 'same-origin' })
      .then(function (response) { if (!response.ok) throw new Error(response.status); return response.text(); })
      .then(function (html) {
        body.innerHTML = html;
        form.action = url;
        dialog.showModal();
        focusFirst();
      })
      .catch(function () { window.location.href = url; });          // fall back to the normal page
  }

  document.addEventListener('click', function (event) {
    var link = event.target.closest('a[data-track-form]');
    if (!link) return;
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    open(link.href);
  });

  // Cancel button (inside the fetched fields) and click on the dimmed area
  dialog.addEventListener('click', function (event) {
    if (event.target === dialog || event.target.closest('[data-dialog-close]')) dialog.close();
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var save = document.getElementById('track-save');
    if (save) { save.disabled = true; save.textContent = 'Saving…'; }

    fetch(form.action, { method: 'POST', body: new FormData(form), headers: HEADERS, credentials: 'same-origin' })
      .then(function (response) {
        if (response.status === 400) {                               // validation errors: show them in place
          return response.text().then(function (html) { body.innerHTML = html; focusFirst(); });
        }
        if (!response.ok) throw new Error(response.status);
        return response.json().then(function (data) {
          // on the home page just refresh (the server remembers the selected album); elsewhere go to the redirect target.
          // Nav (nav.js) swaps the page content without a reload, so music that is playing keeps going.
          var stay = document.querySelector('.home-grid') || data.redirect === window.location.pathname;
          dialog.close();
          // { saved: true }: nav.js keeps this page off the Back trail, since the track was added / edited here
          if (window.Nav) { if (stay) window.Nav.refresh({ saved: true }); else window.Nav.go(data.redirect, { saved: true }); }
          else if (stay) window.location.reload();
          else window.location.href = data.redirect;
        });
      })
      .catch(function () { form.submit(); });                        // last resort: ordinary form post
  });
})();
