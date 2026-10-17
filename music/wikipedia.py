"""Looks up a short artist biography on Wikipedia for the "Fill in from Spotify" box on the New artist form.

Spotify itself has no biographies, so this asks Wikipedia (free, no key needed) for the first few sentences of the
artist's page. Wikipedia's text is licensed CC BY-SA 4.0, so the page's address is saved with the artist
(Artist.bio_source) and shown as a small credit line under the bio. To avoid pasting the wrong person's page, a page is only used when
its title matches the artist's name and its intro reads like a musician or band.
"""
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from django.core.cache import cache

API = 'https://en.wikipedia.org/w/api.php'
PAGE = 'https://en.wikipedia.org/wiki/'
TIMEOUT = 8
MAX_CHARS = 700
CACHE_SECONDS = 24 * 3600
USER_AGENT = 'spotify-clone-class-project/1.0 (student project; looks up short artist intros)'

SUFFIXES = ('', ' (band)', ' (singer)', ' (musician)', ' (rapper)', ' (group)', ' (duo)', ' (American band)', ' (singer-songwriter)')
MUSICAL = re.compile(
    r'\b(singer|songwriter|band|musician|rapper|vocalist|duo|group|record producer|producer|dj|composer|pop|r&b|rock|hip hop|music)\b',
    re.IGNORECASE)


def _get(params):
    url = API + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read())


def _plain(text):
    """Lower-case letters and digits only, accents removed, so "Beyoncé" == "Beyonce" and parentheses can be ignored."""
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'[^a-z0-9]', '', text.lower())


def _same_name(title, artist):
    title = re.sub(r'\s*\([^)]*\)\s*$', '', title)            # "Chase Atlantic (band)" -> "Chase Atlantic"
    return bool(_plain(artist)) and _plain(title) == _plain(artist)


def _shorten(text):
    """At most MAX_CHARS, cut at the end of a sentence where possible; blank lines and footnote marks removed."""
    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'\s*\n+\s*', ' ', text).strip()
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    end = max(cut.rfind('. '), cut.rfind('! '), cut.rfind('? '))
    return cut[:end + 1] if end > 150 else cut.rstrip() + '…'


def _resolve(title, query):
    """Follow Wikipedia's own title clean-up and redirects for one requested title."""
    for mapping in (query.get('normalized', []), query.get('redirects', [])):
        for step in mapping:
            if step.get('from') == title:
                title = step.get('to', title)
    return title


def artist_bio(name):
    """{'bio': text, 'title': page title, 'url': link} for the artist, or None when no suitable page exists."""
    name = (name or '').strip()[:120]
    if not name:
        return None
    key = 'wikibio:' + _plain(name)
    cached = cache.get(key)
    if cached is not None:
        return cached or None

    candidates = [name + suffix for suffix in SUFFIXES]
    try:
        data = _get({
            'action': 'query', 'format': 'json', 'redirects': 1, 'titles': '|'.join(candidates),
            'prop': 'extracts|pageprops', 'ppprop': 'disambiguation', 'exintro': 1, 'explaintext': 1,
            'exsentences': 4, 'exlimit': 'max',
        })
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None                                               # not cached: try again next time

    query = data.get('query', {})
    pages = {page.get('title'): page for page in query.get('pages', {}).values()}
    result = None
    for candidate in candidates:
        page = pages.get(_resolve(candidate, query))
        if not page or 'missing' in page or 'disambiguation' in (page.get('pageprops') or {}):
            continue
        extract = (page.get('extract') or '').strip()
        if not extract or not _same_name(page['title'], name) or not MUSICAL.search(extract[:500]):
            continue
        title = page['title']
        url = PAGE + urllib.parse.quote(title.replace(' ', '_'))
        result = {'bio': _shorten(extract), 'title': title, 'url': url}
        break

    cache.set(key, result or '', CACHE_SECONDS)
    return result
