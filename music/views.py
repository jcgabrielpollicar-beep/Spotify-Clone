from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .colors import panel_vars, theme_style
from .forms import AlbumForm, ArtistForm, PlaylistForm, TrackForm
from .models import Album, Artist, Like, Playlist, PlaylistTrack, Track


# ---------------------------------------------------------------- helpers

def _redirect_back(request, fallback):
    """Redirect to the form's `next` value if it points at this site, else to `fallback`."""
    target = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = fallback
    return redirect(target)


class TrackListContextMixin:
    """Adds what the track-row partial needs: which tracks are liked, and the user's playlists."""

    def get_track_context(self, tracks):
        user = self.request.user
        return {
            'liked_ids': set(Like.objects.filter(user=user, track__in=tracks).values_list('track_id', flat=True)),
            'my_playlists': user.playlists.all(),
        }


class FormPage(LoginRequiredMixin):
    template_name = 'music/form.html'


class ConfirmDeletePage(LoginRequiredMixin):
    template_name = 'music/confirm_delete.html'


# ---------------------------------------------------------------- home

# The home page remembers what you picked (one click on an artist or album) in the session,
# so it survives reloads and trips to other pages.
SESSION_ARTIST = 'home_artist'
SESSION_ALBUM = 'home_album'
SESSION_PLAYLIST = 'home_playlist'


def _select(request, artist=None, album=None, playlist=None):
    """Remember the selection. The Tracks panel shows either an album or a playlist, whichever was picked last:
    picking an artist clears the album, picking an artist or album clears the playlist, picking a playlist
    clears the album (the artist stays)."""
    if playlist is not None:
        request.session[SESSION_PLAYLIST] = playlist.pk
        request.session.pop(SESSION_ALBUM, None)
        return
    if artist is not None:
        request.session[SESSION_ARTIST] = artist.pk
    if album is not None:
        request.session[SESSION_ARTIST] = album.artist_id
        request.session[SESSION_ALBUM] = album.pk
    elif artist is not None:
        request.session.pop(SESSION_ALBUM, None)
    request.session.pop(SESSION_PLAYLIST, None)


def _selection(request):
    """The selected (artist, album, playlist), ignoring anything that no longer exists or no longer matches."""
    artist = Artist.objects.filter(pk=request.session.get(SESSION_ARTIST)).first()
    album = None
    if artist is not None:
        album = Album.objects.filter(pk=request.session.get(SESSION_ALBUM), artist=artist).first()
    playlist = None
    if request.session.get(SESSION_PLAYLIST) is not None:
        playlist = Playlist.objects.filter(pk=request.session[SESSION_PLAYLIST], owner=request.user).first()
        if playlist is not None:
            album = None
    return artist, album, playlist


def _albums_context(artist, album=None):
    if artist is None:
        return {'selected_artist': None}
    return {
        'selected_artist': artist,
        'selected_album_id': album.pk if album else None,
        'albums': artist.albums.order_by('-pk'),  # newest added first, right next to the add tile
        'album_add_url': f"{reverse('album_create')}?artist={artist.pk}",
    }


def _home_theme(artist, album, playlist=None):
    """CSS variables (for <body style>) that tint the home page from what is selected.

    Each container follows its own selection: --artist-* tints the Artists panel, --album-* the Albums panel and
    --tracks-* the Tracks panel (the playlist's colour while a playlist is showing, otherwise the album's). A
    container whose selection is empty keeps the neutral look. The page background takes the most specific colour.
    """
    artist_color = artist.theme_color if artist else ''
    album_color = album.theme_color if album else ''        # an album with no cover of its own borrows its artist's colour
    playlist_color = playlist.theme_color if playlist else ''
    tracks_color = playlist_color or album_color
    return ''.join([
        theme_style(tracks_color or artist_color),
        panel_vars('artist', artist_color),
        panel_vars('album', album_color),
        panel_vars('tracks', tracks_color),
    ])


def _tracks_context(album, user, playlist=None):
    """Tracks of the selected playlist or album, plus which of them this user has liked (for the heart buttons)."""
    if playlist is not None:
        entries = PlaylistTrack.objects.filter(playlist=playlist).select_related('track__album__artist')
        tracks = [entry.track for entry in entries]
    else:
        tracks = list(album.tracks.all()) if album else []
    liked_ids = set(Like.objects.filter(user=user, track__in=tracks).values_list('track_id', flat=True))
    return {'selected_album': album, 'selected_playlist': playlist, 'tracks': tracks, 'liked_ids': liked_ids}


@login_required
def home(request):
    artist, album, playlist = _selection(request)
    return render(request, 'music/home.html', {
        'playlists': request.user.playlists.annotate(track_count=Count('tracks')),
        'artists': Artist.objects.order_by('-pk')[:30],  # newest added first
        'theme_style': _home_theme(artist, album, playlist),
        **_albums_context(artist, album),
        **_tracks_context(album, request.user, playlist),
    })


@login_required
def home_artist_albums(request, pk):
    """One click on an artist: that artist's albums, and an emptied Tracks panel."""
    artist = get_object_or_404(Artist, pk=pk)
    _select(request, artist=artist)
    return JsonResponse({
        'albums': render_to_string('music/_home_albums.html', _albums_context(artist), request),
        'tracks': render_to_string('music/_home_tracks.html', _tracks_context(None, request.user), request),
        'theme': _home_theme(artist, None),
    })


@login_required
def home_album_tracks(request, pk):
    """One click on an album: its tracks."""
    album = get_object_or_404(Album, pk=pk)
    _select(request, album=album)
    return JsonResponse({
        'tracks': render_to_string('music/_home_tracks.html', _tracks_context(album, request.user), request),
        'theme': _home_theme(album.artist, album),
    })


@login_required
def home_playlist_tracks(request, pk):
    """One click on a playlist: its tracks in the Tracks panel (the album highlight is dropped, the artist stays)."""
    playlist = get_object_or_404(Playlist, pk=pk, owner=request.user)
    _select(request, playlist=playlist)
    artist, _album, _playlist = _selection(request)
    return JsonResponse({
        'tracks': render_to_string('music/_home_tracks.html', _tracks_context(None, request.user, playlist), request),
        'theme': _home_theme(artist, None, playlist),
    })


# ---------------------------------------------------------------- artists

class ArtistList(LoginRequiredMixin, ListView):
    model = Artist


class ArtistDetail(LoginRequiredMixin, DetailView):
    model = Artist


class ArtistCreate(FormPage, CreateView):
    model = Artist
    form_class = ArtistForm
    template_name = 'music/artist_form.html'  # centered card with a live preview
    extra_context = {'title': 'New artist'}

    def form_valid(self, form):
        response = super().form_valid(form)
        _select(self.request, artist=self.object)  # the new artist is selected on the home page
        return response


class ArtistUpdate(FormPage, UpdateView):
    model = Artist
    form_class = ArtistForm
    template_name = 'music/artist_form.html'
    extra_context = {'title': 'Edit artist'}


class ArtistDelete(ConfirmDeletePage, DeleteView):
    model = Artist
    success_url = reverse_lazy('artist_list')
    extra_context = {'warning': 'All of this artist\'s albums and tracks will be deleted too.'}


# ---------------------------------------------------------------- albums

class AlbumList(LoginRequiredMixin, ListView):
    model = Album
    queryset = Album.objects.select_related('artist')


class AlbumDetail(LoginRequiredMixin, TrackListContextMixin, DetailView):
    model = Album
    queryset = Album.objects.select_related('artist')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tracks = list(self.object.tracks.all())
        context['tracks'] = tracks
        context.update(self.get_track_context(tracks))
        return context


class AlbumCreate(FormPage, CreateView):
    model = Album
    form_class = AlbumForm
    template_name = 'music/album_form.html'  # centered card with a live preview
    extra_context = {'title': 'New album'}

    def get_initial(self):
        initial = super().get_initial()
        if artist_id := self.request.GET.get('artist'):
            initial['artist'] = artist_id
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        _select(self.request, album=self.object)  # selects the album and its artist
        return response


class AlbumUpdate(FormPage, UpdateView):
    model = Album
    form_class = AlbumForm
    template_name = 'music/album_form.html'
    extra_context = {'title': 'Edit album'}


class AlbumDelete(ConfirmDeletePage, DeleteView):
    model = Album
    success_url = reverse_lazy('album_list')
    extra_context = {'warning': 'All tracks on this album will be deleted too.'}


# ---------------------------------------------------------------- tracks

class DialogFormMixin:
    """Lets a normal form page also serve the popup (static/js/track_dialog.js).

    The popup asks for the same URL with an X-Requested-With header and gets back:
      GET            -> just the form fields (music/_track_form_dialog.html)
      POST, valid    -> JSON {"redirect": url}
      POST, invalid  -> the fields again, with the errors, and status 400
    Without that header (no JavaScript, or a normal visit) the full page works exactly as before.
    """
    dialog_template_name = 'music/_track_form_dialog.html'

    def wants_dialog(self):
        return self.request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def get_template_names(self):
        if self.wants_dialog():
            return [self.dialog_template_name]
        return super().get_template_names()

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.wants_dialog():
            return JsonResponse({'redirect': response.url})
        return response

    def form_invalid(self, form):
        response = super().form_invalid(form)
        if self.wants_dialog():
            response.status_code = 400
        return response


class TrackCreate(DialogFormMixin, FormPage, CreateView):
    model = Track
    form_class = TrackForm
    extra_context = {'title': 'Add track'}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['album'] = get_object_or_404(Album, pk=self.kwargs['album_pk'])
        return context

    def get_initial(self):
        initial = super().get_initial()
        album = get_object_or_404(Album, pk=self.kwargs['album_pk'])
        last = album.tracks.aggregate(last=Max('track_number'))['last'] or 0
        initial['track_number'] = last + 1          # suggest the next free number
        return initial

    def form_valid(self, form):
        form.instance.album = get_object_or_404(Album, pk=self.kwargs['album_pk'])
        response = super().form_valid(form)
        _select(self.request, album=self.object.album)  # Tracks panel shows this album next time
        return response


class TrackUpdate(DialogFormMixin, FormPage, UpdateView):
    model = Track
    form_class = TrackForm
    extra_context = {'title': 'Edit track'}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['album'] = self.object.album
        return context


class TrackDelete(ConfirmDeletePage, DeleteView):
    model = Track

    def get_success_url(self):
        return self.object.album.get_absolute_url()


# ---------------------------------------------------------------- playlists

class OwnPlaylistsMixin(LoginRequiredMixin):
    """Playlists are private: other users' playlists 404."""

    def get_queryset(self):
        return Playlist.objects.filter(owner=self.request.user)


class PlaylistList(OwnPlaylistsMixin, ListView):
    model = Playlist

    def get_queryset(self):
        return super().get_queryset().annotate(track_count=Count('tracks'))


class PlaylistDetail(OwnPlaylistsMixin, TrackListContextMixin, DetailView):
    model = Playlist

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entries = PlaylistTrack.objects.filter(playlist=self.object).select_related('track__album__artist')
        tracks = [entry.track for entry in entries]
        context['tracks'] = tracks
        context.update(self.get_track_context(tracks))
        return context


class PlaylistCreate(FormPage, CreateView):
    model = Playlist
    form_class = PlaylistForm
    template_name = 'music/playlist_form.html'  # centered card, same look as the artist / album forms
    extra_context = {'title': 'New playlist'}

    def form_valid(self, form):
        form.instance.owner = self.request.user
        response = super().form_valid(form)
        _select(self.request, playlist=self.object)  # the new playlist is selected on the home page
        return response


class PlaylistUpdate(OwnPlaylistsMixin, FormPage, UpdateView):
    form_class = PlaylistForm
    template_name = 'music/playlist_form.html'
    extra_context = {'title': 'Edit playlist'}


class PlaylistDelete(OwnPlaylistsMixin, ConfirmDeletePage, DeleteView):
    success_url = reverse_lazy('playlist_list')
    extra_context = {'warning': 'The tracks themselves are not deleted.'}


@login_required
@require_POST
def playlist_add_track(request, track_pk):
    track = get_object_or_404(Track, pk=track_pk)
    playlist = get_object_or_404(Playlist, pk=request.POST.get('playlist'), owner=request.user)
    _, created = PlaylistTrack.objects.get_or_create(playlist=playlist, track=track)
    if created:
        messages.success(request, f'Added "{track.title}" to {playlist.name}.')
    else:
        messages.info(request, f'"{track.title}" is already in {playlist.name}.')
    return _redirect_back(request, track.album.get_absolute_url())


@login_required
@require_POST
def playlist_remove_track(request, pk, track_pk):
    playlist = get_object_or_404(Playlist, pk=pk, owner=request.user)
    PlaylistTrack.objects.filter(playlist=playlist, track_id=track_pk).delete()
    messages.success(request, 'Track removed from playlist.')
    return redirect(playlist)


# ---------------------------------------------------------------- liked songs

@login_required
@require_POST
def toggle_like(request, pk):
    track = get_object_or_404(Track, pk=pk)
    like, created = Like.objects.get_or_create(user=request.user, track=track)
    if not created:
        like.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # the heart button updates in place, so music keeps playing instead of the page reloading
        return JsonResponse({'liked': created})
    return _redirect_back(request, track.album.get_absolute_url())


class LikedSongs(LoginRequiredMixin, TrackListContextMixin, ListView):
    template_name = 'music/liked_songs.html'

    def get_queryset(self):
        return Like.objects.filter(user=self.request.user).select_related('track__album__artist')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tracks = [like.track for like in context['object_list']]
        context['tracks'] = tracks
        context.update(self.get_track_context(tracks))
        return context


# ---------------------------------------------------------------- search

class Search(LoginRequiredMixin, TrackListContextMixin, ListView):
    template_name = 'music/search.html'
    context_object_name = 'tracks'

    def get_queryset(self):
        self.query = self.request.GET.get('q', '').strip()
        if not self.query:
            return Track.objects.none()
        return Track.objects.filter(title__icontains=self.query).select_related('album__artist')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.query
        if self.query:
            context['artists'] = Artist.objects.filter(name__icontains=self.query)
            context['albums'] = Album.objects.filter(title__icontains=self.query).select_related('artist')
        context.update(self.get_track_context(context['tracks']))
        return context
