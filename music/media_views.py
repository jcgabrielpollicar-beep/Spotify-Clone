"""Serves uploaded files (covers, photos, songs) with support for HTTP Range requests.

Django's built-in `static.serve` always sends the whole file. A browser needs byte ranges to jump to another
position of a long song (dragging the seek bar), so this view answers `Range: bytes=a-b` with `206 Partial Content`.
Only used while DEBUG is on (see mysite/urls.py); a real web server does the same job in production.
"""
import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.utils._os import safe_join
from django.utils.http import http_date

CHUNK = 64 * 1024
RANGE = re.compile(r'^bytes=(\d*)-(\d*)$')


def _read(path, start, length):
    with open(path, 'rb') as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            data = handle.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def serve_media(request, path):
    try:
        full = Path(safe_join(settings.MEDIA_ROOT, path))
    except Exception:                       # path tries to leave MEDIA_ROOT
        raise Http404('Not found')
    if not full.is_file():
        raise Http404('Not found')

    size = full.stat().st_size
    content_type = mimetypes.guess_type(str(full))[0] or 'application/octet-stream'
    headers = {'Accept-Ranges': 'bytes', 'Last-Modified': http_date(full.stat().st_mtime)}

    match = RANGE.match(request.headers.get('Range', '').strip())
    if not match or match.group(1) == match.group(2) == '':
        response = StreamingHttpResponse(_read(full, 0, size), content_type=content_type)
        response['Content-Length'] = str(size)
    else:
        first, last = match.groups()
        if first == '':                                         # "-500": the last 500 bytes
            start, end = max(0, size - int(last)), size - 1
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        if start >= size or start > end:
            response = HttpResponse(status=416)
            response['Content-Range'] = f'bytes */{size}'
            return response
        length = end - start + 1
        response = StreamingHttpResponse(_read(full, start, length), status=206, content_type=content_type)
        response['Content-Length'] = str(length)
        response['Content-Range'] = f'bytes {start}-{end}/{size}'
    for name, value in headers.items():
        response[name] = value
    return response
