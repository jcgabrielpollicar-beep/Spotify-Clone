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

  var sending = null;                                                // the upload in progress, if any

  // Closing the popup (Cancel, Esc, the dimmed area) also stops an upload that is still going
  dialog.addEventListener('close', function () { if (sending) { sending.abort(); sending = null; } });

  function megabytes(bytes) { return (bytes / 1048576).toFixed(1); }

  // Shows the bar under the audio field. state: '' (normal), 'waiting' (all sent, server is saving) or 'error'
  function progress(percent, text, state) {
    var box = document.getElementById('track-progress');
    if (!box) return;
    box.hidden = false;
    box.className = 'upload-progress' + (state ? ' is-' + state : '');
    document.getElementById('track-progress-fill').style.width = percent + '%';
    document.getElementById('track-progress-text').textContent = text;
  }

  function finished(data) {
    // on the home page just refresh (the server remembers the selected album); elsewhere go to the redirect target.
    // Nav (nav.js) swaps the page content without a reload, so music that is playing keeps going.
    var stay = document.querySelector('.home-grid') || data.redirect === window.location.pathname;
    sending = null;
    dialog.close();
    // { saved: true }: nav.js keeps this page off the Back trail, since the track was added / edited here
    if (window.Nav) { if (stay) window.Nav.refresh({ saved: true }); else window.Nav.go(data.redirect, { saved: true }); }
    else if (stay) window.location.reload();
    else window.location.href = data.redirect;
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    if (sending) return;
    var save = document.getElementById('track-save');
    var audio = form.querySelector('input[type=file]');
    var file = audio && audio.files && audio.files[0];
    var label = file ? 'Uploading ' + megabytes(file.size) + ' MB…' : '';
    if (save) { save.disabled = true; save.textContent = file ? 'Uploading…' : 'Saving…'; }
    if (file) progress(0, label + ' 0%');

    function failed(message) {                                       // keeps what was typed, so Save can simply be pressed again
      sending = null;
      if (save) { save.disabled = false; save.textContent = 'Save'; }
      progress(100, message, 'error');
    }

    var request = new XMLHttpRequest();
    sending = request;
    request.open('POST', form.action);
    request.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    request.upload.addEventListener('progress', function (e) {
      if (!file || !e.lengthComputable) return;
      var percent = Math.min(100, Math.round(e.loaded / e.total * 100));
      if (percent >= 100) { progress(100, 'Upload done, saving…', 'waiting'); if (save) save.textContent = 'Saving…'; }
      else progress(percent, label + ' ' + percent + '%  (' + megabytes(e.loaded) + ' of ' + megabytes(e.total) + ' MB)');
    });
    request.addEventListener('load', function () {
      if (sending !== request) return;
      if (request.status === 400) {                                  // validation errors: show them in place
        sending = null;
        body.innerHTML = request.responseText;
        focusFirst();
        if (save) { save.disabled = false; save.textContent = 'Save'; }
        return;
      }
      var data = null;
      try { data = JSON.parse(request.responseText); } catch (e) { /* not JSON */ }
      if (request.status >= 200 && request.status < 300 && data && data.redirect) finished(data);
      else failed('Couldn’t save the track (error ' + request.status + '). Press Save to try again.');
    });
    request.addEventListener('error', function () { failed('The upload didn’t go through. Check your connection, then press Save to try again.'); });
    request.addEventListener('timeout', function () { failed('The upload took too long. Check your connection, then press Save to try again.'); });
    request.send(new FormData(form));
  });
})();
