from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('home/artist/<int:pk>/albums/', views.home_artist_albums, name='home_artist_albums'),
    path('home/album/<int:pk>/tracks/', views.home_album_tracks, name='home_album_tracks'),
    path('home/playlist/<int:pk>/tracks/', views.home_playlist_tracks, name='home_playlist_tracks'),
    path('home/liked/tracks/', views.home_liked_tracks, name='home_liked_tracks'),
    path('search/', views.Search.as_view(), name='search'),
    path('search/suggest/', views.search_suggest, name='search_suggest'),

    path('artists/', views.ArtistList.as_view(), name='artist_list'),
    path('artists/new/', views.ArtistCreate.as_view(), name='artist_create'),
    path('artists/<int:pk>/', views.ArtistDetail.as_view(), name='artist_detail'),
    path('artists/<int:pk>/edit/', views.ArtistUpdate.as_view(), name='artist_update'),
    path('artists/<int:pk>/delete/', views.ArtistDelete.as_view(), name='artist_delete'),

    path('albums/', views.AlbumList.as_view(), name='album_list'),
    path('albums/new/', views.AlbumCreate.as_view(), name='album_create'),
    path('albums/<int:pk>/', views.AlbumDetail.as_view(), name='album_detail'),
    path('albums/<int:pk>/edit/', views.AlbumUpdate.as_view(), name='album_update'),
    path('albums/<int:pk>/delete/', views.AlbumDelete.as_view(), name='album_delete'),
    path('albums/<int:album_pk>/tracks/new/', views.TrackCreate.as_view(), name='track_create'),

    path('tracks/<int:pk>/edit/', views.TrackUpdate.as_view(), name='track_update'),
    path('tracks/<int:pk>/delete/', views.TrackDelete.as_view(), name='track_delete'),
    path('tracks/<int:pk>/like/', views.toggle_like, name='track_like'),
    path('tracks/<int:track_pk>/add-to-playlist/', views.playlist_add_track, name='playlist_add_track'),

    path('liked/', views.LikedSongs.as_view(), name='liked_songs'),

    path('playlists/', views.PlaylistList.as_view(), name='playlist_list'),
    path('playlists/new/', views.PlaylistCreate.as_view(), name='playlist_create'),
    path('playlists/<int:pk>/', views.PlaylistDetail.as_view(), name='playlist_detail'),
    path('playlists/<int:pk>/edit/', views.PlaylistUpdate.as_view(), name='playlist_update'),
    path('playlists/<int:pk>/delete/', views.PlaylistDelete.as_view(), name='playlist_delete'),
    path('playlists/<int:pk>/remove/<int:track_pk>/', views.playlist_remove_track, name='playlist_remove_track'),
]
