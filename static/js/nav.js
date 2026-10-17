// Page changes without a full reload, so the music in the "Now playing" bar never stops.
//
// Clicking a link or submitting a form asks Django for the next page as usual, then swaps in only the
// header and <main>. The bar and its <audio> element live outside <main> (see base.html), so they are
// never replaced. Everything is still server-rendered Django templates; if anything looks off
// (not logged in, an error page, a network problem) it just does the normal full page load.
(function () {
  'use strict';

  if (!window.fetch || !window.DOMParser || !window.history || !history.pushState) return;

  var token = 0;                                    // lets a newer click win over a slow earlier one
  history.scrollRestoration = 'manual';
  history.replaceState({ soft: true, scrollY: 0 }, '');

  function sameOrigin(url) { return url.origin === window.location.origin; }
  function eligiblePath(url) { return !/^\/(media|static|admin)\//.test(url.pathname); }
  function pathOf(url) { return url.pathname + url.search + url.hash; }
  function pageOf(url) { return url.pathname + url.search; }       // identity of a page in the trail (no #anchor)

  // ---- the Back button: not the browser's literal history but a trail of real pages.
  // Add / edit / delete screens are never on the trail, the page you are on is never its own "back", and
  // returning to a page cuts the trail back to it, so Back never bounces between two pages or lands on a form.
  var TRAIL_KEY = 'nav-trail';
  var HOME = '/';

  function readTrail() {
    try {
      var trail = JSON.parse(sessionStorage.getItem(TRAIL_KEY) || '[]');
      return Array.isArray(trail) ? trail : [];
    } catch (e) { return []; }
  }
  function writeTrail(trail) {
    try { sessionStorage.setItem(TRAIL_KEY, JSON.stringify(trail.slice(-30))); } catch (e) { /* private mode: Back falls back to Home */ }
  }
  function isFormPage(page) { return /\/(new|edit|delete)\/(\?.*)?$/.test(page) || /^\/accounts\//.test(page); }

  function visit(url) {
    var page = pageOf(url);
    if (isFormPage(page)) return;
    var trail = readTrail();
    var at = trail.lastIndexOf(page);
    if (at === trail.length - 1 && at !== -1) return;                // same page again (e.g. after saving a form)
    if (at !== -1) trail = trail.slice(0, at + 1); else trail.push(page);
    writeTrail(trail);
  }

  function forget(prefix) {                                        // a page that no longer exists (deleted album ...)
    writeTrail(readTrail().filter(function (page) { return page.indexOf(prefix) !== 0; }));
  }

  function backTarget() {
    var current = pageOf(window.location);
    var trail = readTrail();
    for (var i = trail.length - 1; i >= 0; i--) if (trail[i] !== current) return trail[i];
    return current === HOME ? null : HOME;                          // nothing earlier: the menu
  }

  function updateBackButton() {
    var button = document.getElementById('nav-back');
    if (!button) return;
    var target = backTarget();
    button.setAttribute('href', target || HOME);
    button.classList.toggle('is-disabled', !target);
    if (target) button.removeAttribute('aria-disabled'); else button.setAttribute('aria-disabled', 'true');
  }

  function goBack() {
    var target = backTarget();
    if (!target) return;
    navigate(target, { onFail: function () {                       // that page is gone: skip it and try the one before
      writeTrail(readTrail().filter(function (page) { return page !== target; }));
      goBack();
    } });
  }

  function runScripts(container) {
    // scripts inserted through innerHTML don't run, so re-create them (page-specific code, e.g. the home page)
    Array.prototype.forEach.call(container.querySelectorAll('script'), function (old) {
      var fresh = document.createElement('script');
      Array.prototype.forEach.call(old.attributes, function (attr) { fresh.setAttribute(attr.name, attr.value); });
      fresh.text = old.textContent;
      old.replaceWith(fresh);
    });
  }

  function apply(doc, finalUrl, options) {
    var player = document.getElementById('now-playing');
    var playerShowing = player && !player.hidden;

    var header = document.querySelector('header.topbar');
    var newHeader = doc.querySelector('header.topbar');
    if (header && newHeader) header.replaceWith(document.importNode(newHeader, true));

    var main = document.querySelector('main');
    main.innerHTML = doc.querySelector('main').innerHTML;
    runScripts(main);
    if (window.Toast) window.Toast.scan();           // a message that came with the new page ("Saved.") pops up as a bubble

    document.body.className = doc.body.className + (playerShowing ? ' has-player' : '');
    document.body.setAttribute('style', doc.body.getAttribute('style') || '');   // the album / artist colour theme
    document.title = doc.title;                      // the player puts "▶ track · artist" back while something plays
    Array.prototype.forEach.call(document.querySelectorAll('dialog[open]'), function (d) { d.close(); });

    var here = pathOf(window.location);
    var there = pathOf(finalUrl);
    if (!options.pop) {
      if (options.replace || here === there) {
        history.replaceState({ soft: true, scrollY: 0 }, '', there);
      } else {
        history.replaceState({ soft: true, scrollY: window.scrollY }, '');   // remember where we were scrolled
        history.pushState({ soft: true, scrollY: 0 }, '', there);
      }
    }
    window.scrollTo(0, options.pop ? (options.scrollY || 0) : 0);
    visit(window.location);
    updateBackButton();
    document.body.classList.remove('is-navigating');
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  }

  function navigate(url, options) {
    options = options || {};
    var target = new URL(url, window.location.href);
    var ticket = ++token;
    document.body.classList.add('is-navigating');

    var init = { credentials: 'same-origin', headers: { 'X-Soft-Nav': '1' } };
    if (options.method === 'POST') { init.method = 'POST'; init.body = options.body; }

    return fetch(target.href, init)
      .then(function (response) {
        var finalUrl = new URL(response.url, window.location.href);
        var type = response.headers.get('Content-Type') || '';
        return response.text().then(function (html) {
          if (ticket !== token) return;              // a newer navigation took over
          if (!/text\/html/.test(type) || !sameOrigin(finalUrl)) throw { hard: finalUrl.href };
          if (!response.ok) {
            if (options.method === 'POST') {         // the action already ran: show whatever the server answered
              document.open(); document.write(html); document.close();
              return;
            }
            if (options.onFail) { document.body.classList.remove('is-navigating'); options.onFail(); return; }
            throw { hard: target.href };
          }
          var doc = new DOMParser().parseFromString(html, 'text/html');
          // the new page must still contain the player (i.e. still logged in); otherwise load it properly
          if (!doc.getElementById('now-playing') || !doc.querySelector('main')) throw { hard: finalUrl.href };
          apply(doc, finalUrl, options);
          if (options.method === 'POST' || options.saved) {
            if (options.method === 'POST' && /\/delete\/$/.test(target.pathname)) {
              forget(target.pathname.replace(/delete\/$/, ''));  // what was just deleted must not stay on the Back trail
            } else {
              // something was saved here (a track added, a playlist edited ...): that page is where the "action" happened,
              // so Back skips over it instead of returning to it
              writeTrail(readTrail().filter(function (page) { return page !== pageOf(finalUrl); }));
            }
            updateBackButton();
          }
        });
      })
      .catch(function (error) {
        if (ticket !== token) return;
        document.body.classList.remove('is-navigating');
        window.location.href = error && error.hard ? error.hard : target.href;
      });
  }

  // ---- links
  document.addEventListener('click', function (event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var link = event.target.closest && event.target.closest('a[href]');
    if (!link) return;
    if (link.id === 'nav-back') {                                    // the Back button: follow the trail, not the browser history
      event.preventDefault();
      if (!link.classList.contains('is-disabled')) goBack();
      return;
    }
    var raw = link.getAttribute('href');
    if (!raw || raw.charAt(0) === '#') return;                       // in-page anchors
    if ((link.target && link.target !== '_self') || link.hasAttribute('download') || link.hasAttribute('data-no-soft')) return;
    var url = new URL(link.href, window.location.href);
    if (!sameOrigin(url) || !eligiblePath(url)) return;
    if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return;
    event.preventDefault();
    navigate(url.href);
  });

  // ---- forms (search box, create/edit forms, the delete popup, "+ Playlist", ...)
  document.addEventListener('submit', function (event) {
    if (event.defaultPrevented) return;
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if ((form.target && form.target !== '_self') || form.hasAttribute('data-no-soft')) return;
    var method = (form.getAttribute('method') || 'get').toUpperCase();
    if (method !== 'GET' && method !== 'POST') return;
    var action = new URL(form.getAttribute('action') || window.location.href, window.location.href);
    if (!sameOrigin(action) || !eligiblePath(action)) return;

    var data;
    try { data = new FormData(form, event.submitter); } catch (e) { data = new FormData(form); }
    event.preventDefault();
    if (method === 'GET') {
      action.search = new URLSearchParams(data).toString();
      navigate(action.href);
    } else {
      navigate(action.href, { method: 'POST', body: data });
    }
  });

  // ---- back / forward
  window.addEventListener('popstate', function (event) {
    if (!event.state || !event.state.soft) return;
    navigate(window.location.href, { pop: true, scrollY: event.state.scrollY });
  });

  visit(window.location);                            // the page that was just loaded (a normal full load too)
  updateBackButton();

  // other scripts use this to move around without a reload
  window.Nav = {
    go: function (url, options) { return navigate(url, options); },
    refresh: function (options) { return navigate(window.location.href, Object.assign({ replace: true }, options)); }
  };
})();
