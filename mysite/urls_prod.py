"""URLs for the PythonAnywhere copy: the normal site plus uploaded files.

Covers and photos are normally served straight by PythonAnywhere's "Static files" mapping (fast); this view is
the fallback. Full-length songs (media/audio/) must NOT be mapped there: they go through Django so that only
signed-in people can play them.
"""
from django.http import HttpResponseNotFound
from django.urls import re_path

from music.media_views import serve_media

from .urls import urlpatterns as base_urlpatterns


def private_audio(request, path):
    if not request.user.is_authenticated:
        return HttpResponseNotFound()
    return serve_media(request, 'audio/' + path)


urlpatterns = base_urlpatterns + [
    re_path(r'^media/audio/(?P<path>.*)$', private_audio),
    re_path(r'^media/(?P<path>.*)$', serve_media),
]
