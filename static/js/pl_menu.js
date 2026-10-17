// The "+ Playlist" menu next to each song (markup: templates/music/_tracks.html).
//
// Each song has a <details> element: the summary is the button, the form inside is the popup list of your own
// playlists. This script opens the popup next to the button (flipping it upwards near the bottom of the screen),
// closes it again on outside click / Escape / scroll, and adds the song without reloading the page: the chosen
// playlist gets a tick and a small message appears. Without JavaScript the form still works as a normal post.
(function () {
  'use strict';

  var WIDTH = 230;

  // ---- small confirmation message: a popup bubble (static/js/toast.js)
  function say(text, kind) {
    if (window.Toast) window.Toast.show(text, kind || 'success');
  }

  // ---- open / close
  function closeAll(except) {
    Array.prototype.forEach.call(document.querySelectorAll('details.pl-details[open]'), function (d) {
      if (d !== except) d.removeAttribute('open');
    });
  }

  function place(details) {
    var button = details.querySelector('summary');
    var pop = details.querySelector('.pl-pop');
    if (!button || !pop) return;
    var box = button.getBoundingClientRect();
    var bottomLimit = window.innerHeight - (parseFloat(getComputedStyle(document.body).getPropertyValue('--np-bar')) || 0) - 8;
    var left = Math.max(8, Math.min(box.left, window.innerWidth - WIDTH - 8));
    pop.style.left = left + 'px';
    pop.style.top = (box.bottom + 6) + 'px';
    var height = pop.offsetHeight;
    if (box.bottom + 6 + height > bottomLimit && box.top - 6 - height > 8) {
      pop.style.top = (box.top - 6 - height) + 'px';                 // not enough room below: open upwards
    }
  }

  document.addEventListener('toggle', function (event) {
    var details = event.target;
    if (!(details instanceof HTMLDetailsElement) || !details.classList.contains('pl-details')) return;
    if (details.open) { closeAll(details); place(details); }
  }, true);

  document.addEventListener('click', function (event) {
    if (!event.target.closest || !event.target.closest('details.pl-details')) closeAll(null);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    var open = document.querySelector('details.pl-details[open]');
    if (open) { open.removeAttribute('open'); var s = open.querySelector('summary'); if (s) s.focus(); }
  });
  window.addEventListener('scroll', function () { closeAll(null); }, true);   // the popup is fixed, so it would drift
  window.addEventListener('resize', function () { closeAll(null); });

  // ---- adding a song
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.classList.contains('pl-pop')) return;
    var item = event.submitter;
    if (!item || !item.value) return;
    event.preventDefault();                                          // nav.js leaves a handled submit alone

    var data;
    try { data = new FormData(form, item); } catch (e) { data = new FormData(form); data.set(item.name, item.value); }
    fetch(form.action, { method: 'POST', body: data, credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (response) { if (!response.ok) throw new Error(response.status); return response.json(); })
      .then(function (result) {
        item.classList.add('is-in');
        item.disabled = true;
        if (!item.querySelector('.pl-check')) {
          var tick = document.createElement('span');
          tick.className = 'pl-check';
          tick.textContent = '✓';
          item.appendChild(tick);
        }
        var details = form.closest('details');
        if (details) details.removeAttribute('open');
        say(result.created ? 'Added to “' + result.playlist + '”' : 'Already in “' + result.playlist + '”');
      })
      .catch(function () { say('Couldn’t add the song. Try again.', 'error'); });
  });
})();
