from django.contrib import admin

from .models import Album, Artist, Like, Playlist, PlaylistTrack, Track

admin.site.register([Artist, Album, Track, Playlist, PlaylistTrack, Like])
