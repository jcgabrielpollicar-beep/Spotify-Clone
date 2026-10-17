"""A tiny client for Spotify's Web API, used only to look up information when adding artists and albums.

It uses the "client credentials" login: the site's own app keys (settings.SPOTIFY_CLIENT_ID / _SECRET), no
Spotify account of the user is involved. Only public catalog data is read: names, genres, release dates, cover
and artist pictures, and an album's song list. Nothing is played or downloaded from Spotify except those pictures.
"""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from django.conf import settings

TIMEOUT = 10                   # seconds to wait for Spotify
MAX_IMAGE_BYTES = 5 * 1024 * 1024

_token = {'value': '', 'expires': 0.0}


class SpotifyError(Exception):
    """Spotify could not be reached or refused the request (bad keys, rate limit ...)."""


def is_configured():
    return bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET)


def _open(request):
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise SpotifyError(f'Spotify answered {error.code}') from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise SpotifyError('Could not reach Spotify') from error


def _access_token():
    if _token['value'] and time.time() < _token['expires'] - 30:
        return _token['value']
    if not is_configured():
        raise SpotifyError('Spotify keys are not set up')
    basic = base64.b64encode(f'{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}'.encode()).decode()
    request = urllib.request.Request(
        settings.SPOTIFY_TOKEN_URL, data=b'grant_type=client_credentials', method='POST',
        headers={'Authorization': f'Basic {basic}', 'Content-Type': 'application/x-www-form-urlencoded'},
    )
    data = json.loads(_open(request))
    _token.update(value=data['access_token'], expires=time.time() + int(data.get('expires_in', 3600)))
    return _token['value']


def _get(path, **params):
    url = f"{settings.SPOTIFY_API_URL}{path}"
    if params:
        url += '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'Authorization': f'Bearer {_access_token()}'})
    try:
        return json.loads(_open(request))
    except ValueError as error:
        raise SpotifyError('Spotify sent something unexpected') from error


def _image(images, wanted=640):
    """URL of the picture closest to `wanted` pixels wide (they come in several sizes), or ''."""
    images = [i for i in (images or []) if i.get('url')]
    if not images:
        return ''
    return min(images, key=lambda i: abs((i.get('width') or wanted) - wanted))['url']


def search_artists(query, limit=6):
    data = _get('/search', q=query, type='artist', limit=limit)
    return [{
        'id': a['id'],
        'name': a['name'],
        'image': _image(a.get('images')),
        'genres': a.get('genres') or [],
        'followers': (a.get('followers') or {}).get('total', 0),
    } for a in data.get('artists', {}).get('items', []) if a]


def search_albums(query, limit=6):
    data = _get('/search', q=query, type='album', limit=limit)
    return [{
        'id': a['id'],
        'title': a['name'],
        'artist': ', '.join(x['name'] for x in a.get('artists', [])),
        'main_artist': (a.get('artists') or [{}])[0].get('name', ''),
        'date': a.get('release_date', ''),
        'image': _image(a.get('images')),
        'total_tracks': a.get('total_tracks', 0),
        'kind': a.get('album_type', 'album'),
    } for a in data.get('albums', {}).get('items', []) if a]


def album_details(album_id):
    """One album with its song list: title, main artist, release date (always a full YYYY-MM-DD), cover, tracks."""
    a = _get(f'/albums/{urllib.parse.quote(album_id, safe="")}')
    tracks = []
    for t in a.get('tracks', {}).get('items', []):
        tracks.append({
            'number': t.get('track_number') or len(tracks) + 1,
            'title': t.get('name', ''),
            'seconds': round((t.get('duration_ms') or 0) / 1000),
            'artist': ', '.join(x['name'] for x in t.get('artists', [])),
        })
    return {
        'id': a['id'],
        'title': a['name'],
        'main_artist': (a.get('artists') or [{}])[0].get('name', ''),
        'artist': ', '.join(x['name'] for x in a.get('artists', [])),
        'date': full_date(a.get('release_date', ''), a.get('release_date_precision', 'day')),
        'image': _image(a.get('images')),
        'tracks': tracks,
    }


def full_date(value, precision='day'):
    """Spotify sometimes gives only a year ("2019") or a month ("2019-06"); the form needs YYYY-MM-DD."""
    parts = (value or '').split('-')
    if not parts or not parts[0].isdigit():
        return ''
    year = parts[0]
    month = parts[1] if len(parts) > 1 else '01'
    day = parts[2] if len(parts) > 2 else '01'
    return f'{year}-{month}-{day}'


def allowed_image_url(url):
    """Pictures are only ever downloaded from Spotify's own picture servers over https (never from arbitrary
    addresses typed into a form)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or '').lower()
    hosts = settings.SPOTIFY_IMAGE_HOSTS
    if parsed.scheme not in ('https', 'http') or not host:
        return False
    if parsed.scheme == 'http' and host not in ('localhost', '127.0.0.1'):
        return False
    return any(host == h or host.endswith('.' + h) for h in hosts)


def download_image(url):
    """Bytes of an allowed picture (at most 5 MB), or raise SpotifyError."""
    if not allowed_image_url(url):
        raise SpotifyError('That picture address is not allowed')
    request = urllib.request.Request(url, headers={'User-Agent': 'spotify-clone-class-project'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = response.read(MAX_IMAGE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise SpotifyError('Could not download the picture') from error
    if len(data) > MAX_IMAGE_BYTES:
        raise SpotifyError('The picture is too large')
    return data
