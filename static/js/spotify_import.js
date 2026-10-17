// "Fill in from Spotify" on the New artist / New album forms.
//
// Type a name, pick a result, and the form fills itself in: name + genres + photo for an artist, title + artist
// + release date + cover (+ the song list on save) for an album. Nothing is saved until you press Save, and
// every filled-in field can still be changed. The server does the Spotify lookups (/spotify/...), so the
// site's keys never reach the browser.
(function () {
  'use strict';

  var boxes = document.querySelectorAll('.sp-search');
  Array.prototype.forEach.call(boxes, function (box) {
    if (box.dataset.ready) return;
    box.dataset.ready = '1';

    var kind = box.dataset.kind;
    var input = box.querySelector('.sp-input');
    var list = box.querySelector('.sp-results');
    var status = box.querySelector('.sp-status');
    var chosen = box.querySelector('.sp-chosen');
    var form = box.closest('form');
    var editor = box.closest('.editor');
    var timer = null;
    var ticket = 0;

    function field(name) { return form.querySelector('[name="' + name + '"]'); }
    function say(text, isError) {
      status.textContent = text || '';
      status.hidden = !text;
      status.classList.toggle('is-error', !!isError);
    }
    function hideList() { list.hidden = true; list.textContent = ''; }

    function setValue(name, value) {
      var el = field(name);
      if (!el) return;
      el.value = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));       // lets the live preview follow
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function useImage(url, label) {
      var hidden = field('spotify_image');
      if (hidden) hidden.value = url || '';
      if (editor) editor.dataset.image = url || '';                  // the preview shows it until a file is chosen
      var file = form.querySelector('input[type=file]');
      if (file) file.dispatchEvent(new Event('change', { bubbles: true }));
      if (url) {
        chosen.hidden = false;
        chosen.querySelector('.sp-chosen-pic').src = url;
        chosen.querySelector('.sp-chosen-text').textContent = label;
      } else {
        chosen.hidden = true;
      }
    }

    chosen.querySelector('.sp-clear').addEventListener('click', function () { useImage('', ''); });

    function row(title, sub, image, round) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'sp-item';
      button.setAttribute('role', 'option');
      var pic = document.createElement('span');
      pic.className = 'sp-pic' + (round ? ' is-round' : '');
      if (image) { var img = document.createElement('img'); img.src = image; img.alt = ''; pic.appendChild(img); } else { pic.textContent = '♫'; }
      var text = document.createElement('span');
      text.className = 'sp-text';
      var t = document.createElement('span'); t.className = 'sp-title'; t.textContent = title;
      var s = document.createElement('span'); s.className = 'sp-sub'; s.textContent = sub;
      text.appendChild(t); text.appendChild(s);
      button.appendChild(pic); button.appendChild(text);
      return button;
    }

    // ---- picking an artist
    var picks = 0;
    function fillArtist(a) {
      var mine = ++picks;
      setValue('name', a.name);
      useImage(a.image, 'Photo from Spotify');
      var bio = field('bio');
      var genres = a.genres.length ? 'Genres: ' + a.genres.slice(0, 4).join(', ') + '.' : '';
      var done = 'Filled in from Spotify. Change anything you like, then press Save.';
      if (!bio || bio.value.trim()) { say(done); return; }            // never overwrite a bio you already typed
      if (!box.dataset.bioUrl) { if (genres) setValue('bio', genres); say(done); return; }
      say('Filled in from Spotify. Looking for a bio on Wikipedia…');
      fetch(box.dataset.bioUrl + '?name=' + encodeURIComponent(a.name), { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (mine !== picks || bio.value.trim()) return;               // picked someone else, or you started typing
          if (data.bio) {
            setValue('bio', data.bio);
            var source = field('bio_source');
            if (source) source.value = data.source || '';           // shown as a small credit under the bio on the artist page
            say('Filled in from Spotify, with a bio from Wikipedia. Change anything you like, then press Save.');
          } else { if (genres) setValue('bio', genres); say('Filled in from Spotify. No Wikipedia bio was found, so write one if you like, then press Save.'); }
        })
        .catch(function () {
          if (mine !== picks || bio.value.trim()) return;
          if (genres) setValue('bio', genres);
          say('Filled in from Spotify. The bio lookup didn’t work, so write one if you like, then press Save.');
        });
    }

    // ---- picking an album
    function fillAlbum(summary) {
      say('Getting the album…');
      var url = box.dataset.albumUrl.replace('/x/', '/' + encodeURIComponent(summary.id) + '/');
      fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json().then(function (data) { if (!r.ok) throw new Error(data.error || r.status); return data; }); })
        .then(function (data) {
          var album = data.album;
          setValue('title', album.title);
          if (album.date) setValue('release_date', album.date);
          var artist = field('artist');
          var idField = field('spotify_album_id');
          if (idField) idField.value = album.id;
          useImage(album.image, 'Cover from Spotify');
          var count = album.tracks.length;
          var tracksBox = field('import_tracks');
          if (tracksBox) tracksBox.checked = true;
          if (artist && album.artist_id) {
            setValue('artist', String(album.artist_id));
            say('Filled in from Spotify' + (count ? ' (' + count + ' songs will be added when you save)' : '') + '.');
          } else {
            if (artist) artist.value = '';
            status.textContent = '';
            var note = document.createElement('span');
            note.textContent = '“' + album.main_artist + '” isn’t in your catalog yet. ';
            var link = document.createElement('a');
            link.href = box.dataset.addArtistUrl + '?name=' + encodeURIComponent(album.main_artist);
            link.textContent = 'Add the artist first';
            status.appendChild(note); status.appendChild(link);
            status.hidden = false;
            status.classList.add('is-error');
          }
        })
        .catch(function (error) { say('Couldn’t get that album: ' + error.message, true); });
    }

    // ---- searching
    function render(results) {
      list.textContent = '';
      if (!results.length) { say('Nothing found on Spotify for that.'); list.hidden = true; return; }
      say('');
      results.forEach(function (item) {
        var button;
        if (kind === 'artist') {
          var followers = item.followers ? item.followers.toLocaleString() + ' followers' : 'Artist';
          button = row(item.name, item.genres.length ? item.genres.slice(0, 2).join(', ') : followers, item.image, true);
          button.addEventListener('click', function () { hideList(); input.value = item.name; fillArtist(item); });
        } else {
          var year = (item.date || '').slice(0, 4);
          button = row(item.title, item.artist + (year ? ' · ' + year : '') + (item.total_tracks ? ' · ' + item.total_tracks + ' songs' : ''), item.image, false);
          button.addEventListener('click', function () { hideList(); input.value = item.title; fillAlbum(item); });
        }
        list.appendChild(button);
      });
      list.hidden = false;
    }

    function search() {
      var query = input.value.trim();
      if (query.length < 2) { hideList(); say(''); return; }
      var mine = ++ticket;
      say('Searching Spotify…');
      fetch(box.dataset.searchUrl + '?q=' + encodeURIComponent(query), { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json().then(function (data) { if (!r.ok) throw new Error(data.error || r.status); return data; }); })
        .then(function (data) { if (mine === ticket) render(data.results || []); })
        .catch(function (error) { if (mine === ticket) { hideList(); say('Spotify search isn’t working right now (' + error.message + ').', true); } });
    }

    input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(search, 300); });
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') { event.preventDefault(); clearTimeout(timer); search(); }   // never submits the form
      if (event.key === 'Escape') hideList();
    });
    document.addEventListener('click', function (event) { if (!box.contains(event.target)) hideList(); });
  });
})();
