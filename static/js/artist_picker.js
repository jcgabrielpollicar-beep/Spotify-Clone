// A nicer "Artist" dropdown for the album form.
//
// The real <select> stays in the form (it is what gets submitted and what the live preview and the Spotify
// box read and set); this script hides it and puts a picker on top: a button showing the chosen artist with
// their photo, and a list with a search box. Arrow keys, Enter and Escape work; typing filters the list.
(function () {
  'use strict';

  Array.prototype.forEach.call(document.querySelectorAll('select[data-artist-picker]'), function (select) {
    if (select.dataset.ready) return;
    select.dataset.ready = '1';

    var options = Array.prototype.filter.call(select.options, function (o) { return o.value !== ''; });
    var wrap = document.createElement('div');
    wrap.className = 'ap';

    // ---- the button
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'ap-button';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    var chevron = document.createElement('span');
    chevron.className = 'ap-chevron';
    chevron.setAttribute('aria-hidden', 'true');
    chevron.textContent = '▾';

    // ---- the popup
    var panel = document.createElement('div');
    panel.className = 'ap-panel';
    panel.hidden = true;
    var search = document.createElement('input');
    search.type = 'search';
    search.className = 'ap-search';
    search.placeholder = 'Search artists…';
    search.autocomplete = 'off';
    search.setAttribute('aria-label', 'Search artists');
    var list = document.createElement('div');
    list.className = 'ap-list';
    list.setAttribute('role', 'listbox');
    var empty = document.createElement('p');
    empty.className = 'ap-empty';
    empty.textContent = 'No artist found.';
    empty.hidden = true;
    var footer = null;
    if (select.dataset.newUrl) {
      footer = document.createElement('a');
      footer.className = 'ap-new';
      footer.href = select.dataset.newUrl;
      footer.textContent = '+ New artist';
    }

    function face(option, big) {
      var pic = document.createElement('span');
      pic.className = 'ap-pic' + (big ? ' is-big' : '');
      var image = option && option.dataset.image;
      if (image) { var img = document.createElement('img'); img.src = image; img.alt = ''; pic.appendChild(img); }
      else pic.textContent = option ? (option.text.trim().charAt(0).toUpperCase() || '♫') : '♫';
      return pic;
    }

    function item(option) {
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'ap-item';
      row.setAttribute('role', 'option');
      row.dataset.value = option.value;
      row.appendChild(face(option, false));
      var name = document.createElement('span');
      name.className = 'ap-name';
      name.textContent = option.text;
      var tick = document.createElement('span');
      tick.className = 'ap-tick';
      tick.setAttribute('aria-hidden', 'true');
      tick.textContent = '✓';
      row.appendChild(name);
      row.appendChild(tick);
      row.addEventListener('click', function () { choose(option.value); });
      return row;
    }

    options.forEach(function (o) { list.appendChild(item(o)); });
    panel.appendChild(search);
    panel.appendChild(list);
    panel.appendChild(empty);
    if (footer) panel.appendChild(footer);

    // ---- keeping the button in step with the real select (also when the Spotify box changes it)
    function refresh() {
      var current = options.filter(function (o) { return o.value === select.value; })[0];
      button.textContent = '';
      if (current) {
        button.appendChild(face(current, false));
        var label = document.createElement('span');
        label.className = 'ap-label';
        label.textContent = current.text;
        button.appendChild(label);
      } else {
        var placeholder = document.createElement('span');
        placeholder.className = 'ap-label is-empty';
        placeholder.textContent = 'Choose an artist';
        button.appendChild(placeholder);
      }
      button.appendChild(chevron);
      Array.prototype.forEach.call(list.children, function (row) {
        var on = row.dataset.value === select.value;
        row.classList.toggle('is-selected', on);
        row.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }

    function choose(value) {
      select.value = value;
      select.dispatchEvent(new Event('change', { bubbles: true }));       // the live preview listens for this
      close(true);
    }

    // ---- opening, closing, filtering, keys
    function rows() { return Array.prototype.filter.call(list.children, function (r) { return !r.hidden; }); }
    function mark(row) {
      Array.prototype.forEach.call(list.children, function (r) { r.classList.remove('is-active'); });
      if (row) { row.classList.add('is-active'); row.scrollIntoView({ block: 'nearest' }); }
    }
    function filter() {
      var q = search.value.trim().toLowerCase();
      Array.prototype.forEach.call(list.children, function (r) { r.hidden = q && r.textContent.toLowerCase().indexOf(q) === -1; });
      empty.hidden = rows().length > 0;
      mark(rows()[0] || null);
    }
    function open() {
      panel.hidden = false;
      button.setAttribute('aria-expanded', 'true');
      search.value = '';
      filter();
      var selected = list.querySelector('.is-selected');
      if (selected) { mark(selected); }
      search.focus();
    }
    function close(refocus) {
      panel.hidden = true;
      button.setAttribute('aria-expanded', 'false');
      if (refocus) button.focus();
    }

    button.addEventListener('click', function () { if (panel.hidden) open(); else close(true); });
    button.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); if (panel.hidden) open(); }
    });
    search.addEventListener('input', filter);
    search.addEventListener('keydown', function (event) {
      var visible = rows();
      var at = visible.indexOf(list.querySelector('.is-active'));
      if (event.key === 'ArrowDown') { event.preventDefault(); mark(visible[Math.min(visible.length - 1, at + 1)]); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); mark(visible[Math.max(0, at - 1)]); }
      else if (event.key === 'Enter') { event.preventDefault(); var row = list.querySelector('.is-active'); if (row && !row.hidden) choose(row.dataset.value); }
      else if (event.key === 'Escape') { event.preventDefault(); close(true); }
      else if (event.key === 'Tab') { close(false); }
    });
    document.addEventListener('click', function (event) { if (!wrap.contains(event.target)) close(false); });
    select.addEventListener('change', refresh);

    // ---- put it in place
    select.classList.add('ap-native');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(button);
    wrap.appendChild(panel);
    wrap.appendChild(select);
    refresh();
  });
})();
