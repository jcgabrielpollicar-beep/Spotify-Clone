// Notifications as small popup bubbles that disappear by themselves.
//
// The server still renders Django's messages ("Sample1 is no longer a partner.") as a plain list in the page, so
// everything works without JavaScript. With JavaScript this script turns that list into bubbles above the Now
// playing bar and removes the list; nav.js calls Toast.scan() after each page change so messages that arrive
// with a new page are handled too. Other scripts (the "+ Playlist" menu) call Toast.show(text, kind).
(function () {
  'use strict';

  var SHOW_MS = { error: 3800, warning: 3800 };      // mistakes get a little longer so they can be read
  var DEFAULT_MS = 2200;                             // everything else: about two seconds
  var stack = null;

  function container() {
    if (!stack || !stack.isConnected) {
      stack = document.createElement('div');
      stack.className = 'toasts';
      document.body.appendChild(stack);
    }
    return stack;
  }

  function show(text, kind) {
    text = (text || '').trim();
    if (!text) return;
    kind = /^(success|error|warning|info)$/.test(kind) ? kind : 'info';
    var bubble = document.createElement('div');
    bubble.className = 'toast toast-' + kind;
    bubble.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    bubble.textContent = text;
    container().appendChild(bubble);

    var gone = false;
    function dismiss() {
      if (gone) return;
      gone = true;
      bubble.classList.remove('is-on');
      setTimeout(function () { bubble.remove(); }, 300);
    }
    bubble.addEventListener('click', dismiss);        // click to close early
    void bubble.offsetWidth;                          // lets the start position register, so the fade-in animates
    bubble.classList.add('is-on');
    setTimeout(dismiss, SHOW_MS[kind] || DEFAULT_MS);
  }

  function scan() {
    Array.prototype.forEach.call(document.querySelectorAll('ul.messages'), function (list) {
      Array.prototype.forEach.call(list.querySelectorAll('li'), function (item) {
        show(item.textContent, (item.className || '').split(' ')[0]);
      });
      list.remove();
    });
  }

  window.Toast = { show: show, scan: scan };
  scan();
})();
