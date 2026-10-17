// Search suggestions: while you type in the header search box, a list of matching artists, albums and songs
// that already exist in the catalog drops down (from /search/suggest/). Click one (or use the arrow keys +
// Enter) to open it; plain Enter with nothing highlighted runs the normal full search.
//
// The header is swapped by nav.js when you change page, so everything here listens on the document instead of
// on the box itself, and the dropdown is created when needed.
(function () {
  'use strict';

  var DELAY = 150;                     // ms to wait after the last key before asking the server
  var timer = null;
  var ticket = 0;                      // lets a newer answer win over a slow older one
  var cache = {};                      // query -> results, so backspacing is instant

  function formOf(node) { return node && node.closest ? node.closest('form.search') : null; }
  function inputOf(form) { return form.querySelector('input[name="q"]'); }
  function listOf(form) { return form.querySelector('.suggest'); }

  function close(form) {
    var list = form && listOf(form);
    if (list) list.remove();
    var input = form && inputOf(form);
    if (input) { input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); }
  }

  function closeAll() {
    Array.prototype.forEach.call(document.querySelectorAll('form.search'), close);
  }

  function row(item, index) {
    var link = document.createElement('a');
    link.className = 'sg-item';
    link.href = item.url;
    link.id = 'sg-' + index;
    link.setAttribute('role', 'option');

    var pic = document.createElement('span');
    pic.className = 'sg-pic' + (item.type === 'artist' ? ' is-round' : '');
    if (item.image) {
      var img = document.createElement('img');
      img.src = item.image;
      img.alt = '';
      pic.appendChild(img);
    } else {
      pic.textContent = '♫';
    }

    var text = document.createElement('span');
    text.className = 'sg-text';
    var title = document.createElement('span');
    title.className = 'sg-title';
    title.textContent = item.title;                               // textContent: names are never treated as HTML
    var sub = document.createElement('span');
    sub.className = 'sg-sub';
    sub.textContent = item.sub;
    text.appendChild(title);
    text.appendChild(sub);

    link.appendChild(pic);
    link.appendChild(text);
    return link;
  }

  function show(form, query, results) {
    if (document.activeElement !== inputOf(form) || inputOf(form).value.trim() !== query) return;   // moved on already
    var list = listOf(form);
    if (!list) {
      list = document.createElement('div');
      list.className = 'suggest';
      list.id = 'suggest-box';
      list.setAttribute('role', 'listbox');
      form.appendChild(list);
    }
    list.textContent = '';
    if (!results.length) {
      var none = document.createElement('div');
      none.className = 'sg-empty';
      none.textContent = 'Nothing added yet matches “' + query + '”';
      list.appendChild(none);
    } else {
      results.forEach(function (item, index) { list.appendChild(row(item, index)); });
      var all = document.createElement('a');
      all.className = 'sg-all';
      all.href = form.getAttribute('action') + '?q=' + encodeURIComponent(query);
      all.textContent = 'See all results for “' + query + '”';
      list.appendChild(all);
    }
    inputOf(form).setAttribute('aria-expanded', 'true');
  }

  function ask(form) {
    var query = inputOf(form).value.trim();
    if (!query) { close(form); return; }
    if (cache[query]) { show(form, query, cache[query]); return; }
    var mine = ++ticket;
    var url = form.dataset.suggestUrl + '?q=' + encodeURIComponent(query);
    fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (response) { if (!response.ok) throw new Error(response.status); return response.json(); })
      .then(function (data) {
        if (mine !== ticket) return;
        cache[query] = data.results;
        show(form, query, data.results);
      })
      .catch(function () { close(form); });                       // no suggestions is fine: the normal search still works
  }

  function move(form, step) {
    var rows = form.querySelectorAll('.sg-item, .sg-all');
    if (!rows.length) return;
    var current = -1;
    Array.prototype.forEach.call(rows, function (r, i) { if (r.classList.contains('is-active')) current = i; });
    if (current >= 0) rows[current].classList.remove('is-active');
    var next = current + step;
    if (next < 0) next = rows.length - 1;
    if (next >= rows.length) next = 0;
    rows[next].classList.add('is-active');
    rows[next].scrollIntoView({ block: 'nearest' });
    inputOf(form).setAttribute('aria-activedescendant', rows[next].id || '');
  }

  document.addEventListener('input', function (event) {
    var form = event.target.matches && event.target.matches('form.search input[name="q"]') ? formOf(event.target) : null;
    if (!form) return;
    clearTimeout(timer);
    timer = setTimeout(function () { ask(form); }, DELAY);
  });

  document.addEventListener('focusin', function (event) {
    var form = event.target.matches && event.target.matches('form.search input[name="q"]') ? formOf(event.target) : null;
    if (form && inputOf(form).value.trim() && !listOf(form)) ask(form);
  });

  document.addEventListener('keydown', function (event) {
    var form = event.target.matches && event.target.matches('form.search input[name="q"]') ? formOf(event.target) : null;
    if (!form) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!listOf(form)) { ask(form); return; }
      move(form, event.key === 'ArrowDown' ? 1 : -1);
      event.preventDefault();
    } else if (event.key === 'Enter') {
      var active = listOf(form) && listOf(form).querySelector('.is-active');
      if (active) { event.preventDefault(); active.click(); }     // nav.js opens it without reloading the page
    } else if (event.key === 'Escape') {
      close(form);
    }
  });

  // clicking anywhere else, or opening a result, closes the list
  document.addEventListener('click', function (event) {
    Array.prototype.forEach.call(document.querySelectorAll('form.search'), function (form) {
      if (!form.contains(event.target) || event.target.closest('.sg-item, .sg-all')) close(form);
    });
  });
  document.addEventListener('submit', closeAll);
})();
