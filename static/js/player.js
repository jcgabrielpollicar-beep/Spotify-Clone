// "Now playing" bar (templates/base.html) + the play buttons on every track row (templates/music/_tracks.html).
//
// One <audio id="np-audio"> plays everything. Clicking a row's play button makes the rows of that
// .track-list the queue and starts that track. The bar has previous / next / shuffle / repeat, a seek
// bar and a volume slider. What is playing is remembered per tab (sessionStorage), so after you open
// another page the bar is still there, at the same spot, and tries to carry on playing.
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var bar = $('now-playing');
  var audio = $('np-audio');

  var STATE_KEY = 'np-state';
  var VOLUME_KEY = 'np-volume';

  function safeGet(storage, key) { try { return storage.getItem(key); } catch (e) { return null; } }
  function safeSet(storage, key, value) { try { storage.setItem(key, value); } catch (e) { /* storage blocked: just don't remember */ } }

  function fmt(seconds) {
    var s = Math.max(0, Math.floor(seconds || 0));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  // ====================================================================== heart + "+ Playlist"
  // (these work on every page, with or without the player bar)

  // heart button: like/unlike in place, so the page doesn't reload and the music keeps playing
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!form.matches || !form.matches('form[data-like]')) return;
    event.preventDefault();
    var heart = form.querySelector('.like');
    fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (response) { if (!response.ok) throw new Error(response.status); return response.json(); })
      .then(function (data) {
        heart.classList.toggle('liked', data.liked);
        heart.innerHTML = data.liked ? '&#9829;' : '&#9825;';
        heart.title = data.liked ? 'Remove from Liked Songs' : 'Add to Liked Songs';
        heart.setAttribute('aria-label', data.liked ? 'Unlike' : 'Like');
      })
      .catch(function () { form.submit(); });   // fall back to a normal form post
  });

  if (!bar || !audio) return;          // logged-out pages have no player

  // ====================================================================== state
  var queue = [];                      // [{id, src, title, artist, artistUrl, album, albumUrl, cover, seconds}]
  var index = -1;
  var shuffle = false;
  var repeat = 'off';                  // 'off' | 'all' | 'one'
  var history = [];                    // indexes played before the current one (for Previous)
  var pendingSeek = 0;                 // where to jump once the file's metadata is loaded
  var lastSaved = 0;

  function current() { return queue[index] || null; }

  // ====================================================================== listening history
  // A song counts as "played" (for the profile's top artists / songs) once it has really been listened to for
  // about 10 seconds, or half of it when it is shorter. Jumping around with the seek bar doesn't add up.
  var listened = 0;                    // seconds actually heard since this song started
  var lastPos = null;                  // where the song was at the previous tick
  var counted = false;                 // already reported for this listen

  function resetListening() { listened = 0; lastPos = null; counted = false; }

  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (match) return decodeURIComponent(match[1]);
    var field = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return field ? field.value : '';
  }

  function recordPlay(id) {
    try {
      fetch('/plays/record/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'track=' + encodeURIComponent(id)
      }).catch(function () { /* statistics are optional: never disturb the music */ });
    } catch (e) { /* same */ }
  }

  function countListening() {
    var t = current();
    if (!t || counted || audio.paused) { lastPos = null; return; }
    var pos = audio.currentTime || 0;
    if (lastPos !== null) {
      var step = pos - lastPos;
      if (step > 0 && step < 1.5) listened += step;                 // a seek jumps further than a normal tick
    }
    lastPos = pos;
    var needed = Math.min(10, (t.seconds || 10) * 0.5);
    if (listened >= needed) { counted = true; recordPlay(t.id); }
  }

  function trackFromRow(row) {
    var d = row.dataset;
    return {
      id: d.id, src: d.src, title: d.title || '', artist: d.artist || '', artistUrl: d.artistUrl || '#',
      album: d.album || '', albumUrl: d.albumUrl || '#', cover: d.cover || '', seconds: parseInt(d.seconds, 10) || 0
    };
  }

  // ====================================================================== remembering across pages
  function save(force) {
    var now = Date.now();
    if (!force && now - lastSaved < 1000) return;
    lastSaved = now;
    if (!current()) return;
    safeSet(window.sessionStorage, STATE_KEY, JSON.stringify({
      queue: queue, index: index, time: audio.currentTime || 0, playing: !audio.paused && !audio.ended,
      shuffle: shuffle, repeat: repeat
    }));
  }

  function restore() {
    var raw = safeGet(window.sessionStorage, STATE_KEY);
    var st;
    try { st = raw && JSON.parse(raw); } catch (e) { st = null; }
    if (!st || !Array.isArray(st.queue) || !st.queue[st.index]) return;
    queue = st.queue;
    shuffle = !!st.shuffle;
    repeat = st.repeat === 'all' || st.repeat === 'one' ? st.repeat : 'off';
    load(st.index, false, st.time || 0);
    if (st.playing) {
      // browsers may refuse to start sound on a fresh page; then it simply waits for you to press play
      var attempt = audio.play();
      if (attempt && attempt.catch) attempt.catch(function () { render(); });
    }
  }

  // ====================================================================== loading + transport
  function load(i, autoplay, startAt) {
    index = i;
    var t = current();
    resetListening();
    pendingSeek = startAt || 0;
    audio.preload = 'auto';
    audio.src = t.src;
    bar.hidden = false;
    document.body.classList.add('has-player');
    $('np-error').hidden = true;
    renderMeta(t);
    if (autoplay) {
      var attempt = audio.play();
      if (attempt && attempt.catch) attempt.catch(function () { showError(); });
    }
    render();
    save(true);
  }

  function startFromRow(row) {
    var list = row.closest('.track-list');
    var rows = list ? list.querySelectorAll('.trk[data-src]') : [row];
    queue = [];
    var start = 0;
    Array.prototype.forEach.call(rows, function (r) {
      if (r === row) start = queue.length;
      queue.push(trackFromRow(r));
    });
    history = [];
    load(start, true, 0);
  }

  function toggle() {
    if (!current()) return;
    if (audio.paused) {
      var attempt = audio.play();
      if (attempt && attempt.catch) attempt.catch(function () { showError(); });
    } else {
      audio.pause();
    }
  }

  function randomOther() {
    var n;
    do { n = Math.floor(Math.random() * queue.length); } while (n === index && queue.length > 1);
    return n;
  }

  function next(auto) {
    if (!queue.length) return;
    if (auto && repeat === 'one') { resetListening(); audio.currentTime = 0; audio.play(); return; }
    var n;
    if (shuffle && queue.length > 1) {
      n = randomOther();
    } else {
      n = index + 1;
      if (n >= queue.length) {
        if (repeat === 'all') {
          n = 0;
        } else {
          if (auto) { audio.pause(); audio.currentTime = 0; render(); save(true); }   // reached the end: stop on the last track
          return;
        }
      }
    }
    history.push(index);
    load(n, true, 0);
  }

  function previous() {
    if (!queue.length) return;
    if (audio.currentTime > 3 || (!history.length && index === 0)) { resetListening(); audio.currentTime = 0; return; }   // like Spotify: restart first
    var p = history.length ? history.pop() : (index > 0 ? index - 1 : queue.length - 1);
    load(p, true, 0);
  }

  // ====================================================================== drawing
  function setCover(el, url) {
    el.innerHTML = '';
    if (url) {
      var img = document.createElement('img');
      img.alt = '';
      img.src = url;
      el.appendChild(img);
    } else {
      var note = document.createElement('span');
      note.innerHTML = '&#9835;';
      el.appendChild(note);
    }
  }

  function renderMeta(t) {
    setCover($('np-cover'), t.cover);
    var title = $('np-title'), artist = $('np-artist');
    title.textContent = t.title; title.href = t.albumUrl; title.title = t.title + ' (' + t.album + ')';
    artist.textContent = t.artist; artist.href = t.artistUrl;
    document.title = (audio.paused ? '' : '▶ ') + t.title + ' · ' + t.artist;

    if ('mediaSession' in navigator && window.MediaMetadata) {
      // the lock screen picks the picture whose size suits it best; the covers are square
      var artwork = t.cover ? ['96x96', '256x256', '512x512'].map(function (size) { return { src: new URL(t.cover, window.location.href).href, sizes: size }; }) : [];
      try { navigator.mediaSession.metadata = new window.MediaMetadata({ title: t.title, artist: t.artist, album: t.album, artwork: artwork }); } catch (e) { /* the title still shows in the bar */ }
    }
  }

  // ---- what the phone's lock screen / notification shows: play or pause, and the seek bar
  var lastPositionPush = 0;
  function updateSession(force) {
    if (!('mediaSession' in navigator)) return;
    var ms = navigator.mediaSession;
    try { ms.playbackState = !current() ? 'none' : (!audio.paused && !audio.ended ? 'playing' : 'paused'); } catch (e) { /* not supported */ }
    if (!ms.setPositionState) return;
    var now = Date.now();
    if (!force && now - lastPositionPush < 1000) return;              // once a second is plenty
    lastPositionPush = now;
    var total = audio.duration;
    try {
      if (isFinite(total) && total > 0) {
        ms.setPositionState({ duration: total, playbackRate: audio.playbackRate || 1, position: Math.min(audio.currentTime || 0, total) });
      } else {
        ms.setPositionState();                                        // length not known yet: no seek bar
      }
    } catch (e) { /* not supported */ }
  }

  function render() {
    var t = current();
    var playing = !audio.paused && !audio.ended;
    var playBtn = $('np-play');
    bar.classList.toggle('is-playing', playing);
    playBtn.setAttribute('aria-label', playing ? 'Pause' : 'Play');
    playBtn.title = playing ? 'Pause' : 'Play';

    var total = isFinite(audio.duration) && audio.duration > 0 ? audio.duration : (t ? t.seconds : 0);
    var time = audio.currentTime || 0;
    if (typeof scrub === 'number' && total) time = scrub * total;     // while dragging the bar shows where you are about to jump
    $('np-cur').textContent = fmt(time);
    $('np-total').textContent = fmt(total);
    $('np-fill').style.width = (total ? Math.min(100, (time / total) * 100) : 0) + '%';
    var slider = $('np-bar');
    slider.setAttribute('aria-valuemax', String(Math.round(total)));
    slider.setAttribute('aria-valuenow', String(Math.round(time)));

    $('np-shuffle').classList.toggle('is-on', shuffle);
    $('np-shuffle').setAttribute('aria-pressed', shuffle ? 'true' : 'false');
    var rep = $('np-repeat');
    rep.classList.toggle('is-on', repeat !== 'off');
    rep.classList.toggle('is-one', repeat === 'one');
    rep.setAttribute('aria-pressed', repeat !== 'off' ? 'true' : 'false');
    rep.setAttribute('aria-label', 'Repeat: ' + repeat);
    rep.title = repeat === 'one' ? 'Repeat this track' : repeat === 'all' ? 'Repeat all' : 'Repeat';

    if (t) document.title = (playing ? '▶ ' : '') + t.title + ' · ' + t.artist;
    syncRows();
    updateSession(false);
  }

  function showError() {
    $('np-error').hidden = false;
    var row = rowFor(current());
    if (row) row.classList.add('has-error');
    render();
  }

  // ---- the track rows on the page follow what the bar is playing
  function rowFor(t) {
    return t ? document.querySelector('.trk[data-id="' + t.id + '"]') : null;
  }

  function syncRows() {
    var t = current();
    var playing = !audio.paused && !audio.ended;
    Array.prototype.forEach.call(document.querySelectorAll('.trk'), function (row) {
      var mine = !!t && row.dataset.id === t.id && !!row.dataset.src;
      row.classList.toggle('is-active', mine);
      row.classList.toggle('is-playing', mine && playing);
      if (!mine) row.classList.remove('has-error');
      var button = row.querySelector('.trk-play');
      if (button && !button.disabled) {
        var on = mine && playing;
        button.setAttribute('aria-pressed', on ? 'true' : 'false');
        button.setAttribute('aria-label', (on ? 'Pause ' : 'Play ') + (row.dataset.title || ''));
      }
      if (mine) {
        var cur = row.querySelector('.trk-cur');
        var text = fmt(audio.currentTime);
        if (cur && cur.textContent !== text) cur.textContent = text;
      }
    });
  }

  // track lists get replaced on the home page (click an album): re-apply the highlight to the new rows
  new MutationObserver(function (mutations) {
    var rowsAdded = mutations.some(function (m) {
      return Array.prototype.some.call(m.addedNodes, function (n) {
        return n.nodeType === 1 && (n.matches('.trk') || n.querySelector('.trk'));
      });
    });
    if (rowsAdded) syncRows();
  }).observe(document.body, { childList: true, subtree: true });

  // ====================================================================== audio events
  audio.addEventListener('play', function () { $('np-error').hidden = true; render(); save(true); });
  audio.addEventListener('playing', function () { $('np-error').hidden = true; render(); });
  audio.addEventListener('pause', function () { render(); save(true); });
  audio.addEventListener('ended', function () { next(true); });
  audio.addEventListener('timeupdate', function () { countListening(); render(); save(false); });
  audio.addEventListener('durationchange', function () { render(); updateSession(true); });
  audio.addEventListener('seeked', function () { updateSession(true); });                // the lock screen's bar follows a jump at once
  audio.addEventListener('loadedmetadata', function () {
    if (pendingSeek > 0 && isFinite(audio.duration)) { audio.currentTime = Math.min(pendingSeek, audio.duration); }
    pendingSeek = 0;
    render();
    updateSession(true);
  });
  audio.addEventListener('error', function () { if (current()) showError(); });
  window.addEventListener('pagehide', function () { save(true); });

  // ====================================================================== controls
  document.addEventListener('click', function (event) {
    var button = event.target.closest('.trk-play');
    if (!button || button.disabled) return;
    var row = button.closest('.trk');
    if (!row || !row.dataset.src) return;
    if (current() && current().id === row.dataset.id) toggle();
    else startFromRow(row);
  });

  $('np-play').addEventListener('click', toggle);
  $('np-next').addEventListener('click', function () { next(false); });
  $('np-prev').addEventListener('click', previous);
  $('np-shuffle').addEventListener('click', function () { shuffle = !shuffle; render(); save(true); });
  $('np-repeat').addEventListener('click', function () {
    repeat = repeat === 'off' ? 'all' : repeat === 'all' ? 'one' : 'off';
    render(); save(true);
  });

  // Space plays / pauses, unless you're typing or on a control that already uses Space
  document.addEventListener('keydown', function (event) {
    if (event.code !== 'Space' || !current()) return;
    var target = event.target;
    if (target.closest && target.closest('input, textarea, select, button, a, [contenteditable], dialog[open]')) return;
    event.preventDefault();
    toggle();
  });

  // ---- sliders: click or drag, arrow keys when focused
  function fractionOf(slider, clientX) {
    var box = slider.getBoundingClientRect();
    return Math.min(1, Math.max(0, (clientX - box.left) / box.width));
  }

  // onFraction runs on press and on every move while dragging. With onRelease the drag is only a preview:
  // onRelease(fraction) runs once when you let go (fraction is null if the drag was cancelled).
  function makeSlider(slider, onFraction, onKeyStep, onRelease) {
    var dragging = false;
    var last = 0;
    function finish(commit) {
      if (!dragging) return;
      dragging = false;
      slider.classList.remove('is-dragging');
      if (onRelease) onRelease(commit ? last : null);
    }
    slider.addEventListener('pointerdown', function (event) {
      if (event.button > 0) return;                                  // left button / touch / pen only
      dragging = true;
      slider.classList.add('is-dragging');
      last = fractionOf(slider, event.clientX);
      onFraction(last);
      try { slider.setPointerCapture(event.pointerId); } catch (e) { /* works without capture */ }
      event.preventDefault();
    });
    slider.addEventListener('pointermove', function (event) {
      if (!dragging) return;
      last = fractionOf(slider, event.clientX);
      onFraction(last);
    });
    slider.addEventListener('pointerup', function (event) {
      if (dragging) last = fractionOf(slider, event.clientX);
      finish(true);
    });
    slider.addEventListener('pointercancel', function () { finish(false); });
    slider.addEventListener('keydown', function (event) {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      onKeyStep(event.key === 'ArrowRight' ? 1 : -1);
      event.preventDefault();
    });
  }

  // the seek bar: drag the knob (or click anywhere on the bar); the song jumps when you let go
  var scrub = null;                                                 // 0..1 while dragging, otherwise null

  function trackLength() {
    var t = current();
    return isFinite(audio.duration) && audio.duration > 0 ? audio.duration : (t ? t.seconds : 0);
  }

  makeSlider($('np-bar'), function (fraction) {
    if (!current() || !trackLength()) return;
    scrub = fraction;
    render();
  }, function (direction) {
    audio.currentTime = Math.max(0, (audio.currentTime || 0) + direction * 5);
  }, function (fraction) {
    scrub = null;
    var total = trackLength();
    if (fraction !== null && total) audio.currentTime = Math.min(fraction * total, total - 0.05);
    render();
    save(true);
  });

  // ---- volume (remembered in this browser)
  function setVolume(v, remember) {
    v = Math.min(1, Math.max(0, v));
    audio.volume = v;
    audio.muted = v === 0;
    $('np-vol-fill').style.width = (v * 100) + '%';
    $('np-vol').setAttribute('aria-valuenow', String(Math.round(v * 100)));
    bar.classList.toggle('is-muted', audio.muted);
    if (remember) safeSet(window.localStorage, VOLUME_KEY, String(v));
  }

  makeSlider($('np-vol'), function (fraction) { setVolume(fraction, true); }, function (direction) {
    setVolume(audio.volume + direction * 0.05, true);
  });

  var lastVolume = 0.8;
  $('np-mute').addEventListener('click', function () {
    if (audio.muted || audio.volume === 0) { setVolume(lastVolume || 0.8, true); }
    else { lastVolume = audio.volume; audio.muted = true; $('np-vol-fill').style.width = '0%'; bar.classList.add('is-muted'); }
  });

  var storedVolume = parseFloat(safeGet(window.localStorage, VOLUME_KEY));
  setVolume(isFinite(storedVolume) ? storedVolume : 0.8, false);

  // ---- keyboard / lock-screen / headphone buttons
  if ('mediaSession' in navigator) {
    var set = function (name, handler) { try { navigator.mediaSession.setActionHandler(name, handler); } catch (e) { /* not supported */ } };
    set('play', function () { if (current() && audio.paused) toggle(); });           // play / pause do what they say, never the opposite
    set('pause', function () { if (!audio.paused) toggle(); });
    set('stop', function () { if (!audio.paused) toggle(); });
    set('previoustrack', previous);
    set('nexttrack', function () { next(false); });
    function jump(seconds) {
      if (!current()) return;
      var total = trackLength();
      audio.currentTime = Math.max(0, Math.min((audio.currentTime || 0) + seconds, total ? total - 0.05 : Infinity));
    }
    set('seekbackward', function (details) { jump(-((details && details.seekOffset) || 10)); });
    set('seekforward', function (details) { jump((details && details.seekOffset) || 10); });
    set('seekto', function (details) {                                                 // dragging the lock screen's bar
      if (!current() || !details || typeof details.seekTime !== 'number') return;
      var total = trackLength();
      audio.currentTime = Math.max(0, Math.min(details.seekTime, total ? total - 0.05 : details.seekTime));
    });
  }

  restore();
})();
