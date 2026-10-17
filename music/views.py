import datetime
from urllib.parse import urlparse

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, Count, IntegerField, Max, When
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from . import imports, spotify, wikipedia
from .colors import panel_vars, theme_style
from .forms import AlbumForm, ArtistForm, PlaylistForm, TrackForm
from .models import Album, Artist, Like, Play, Playlist, PlaylistPartner, PlaylistTrack, Track, editable_playlists


# ---------------------------------------------------------------- helpers

def _redirect_back(request, fallback):
    """Redirect to the form's `next` value if it points at this site, else to `fallback`."""
    target = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = fallback
    return redirect(target)


class TrackListContextMixin:
    """Adds what the track-row partial needs: which tracks are liked, the user's own playlists, and which of
    those playlists already hold each track (shown as a tick in the "+ Playlist" menu)."""

    def get_track_context(self, tracks):
        user = self.request.user
        playlists = list(editable_playlists(user).select_related('owner'))     # your own and the ones you are a partner on
        return {
            'liked_ids': set(Like.objects.filter(user=user, track__in=tracks).values_list('track_id', flat=True)),
            'my_playlists': playlists,
            'playlist_pairs': set(PlaylistTrack.objects.filter(playlist__in=playlists, track__in=tracks)
                                  .values_list('track_id', 'playlist_id')),
        }


class FormPage(LoginRequiredMixin):
    template_name = 'music/form.html'


class CancelLinkMixin:
    """The Cancel button of a "new ..." form goes back to the page the form was opened from (the albums page, an
    artist's page, the home page ...), not always to the same place. The page comes from a hidden `next` value
    (kept when the form is shown again after an error), a `?next=` link, or the browser's Referer; only pages of
    this site are accepted. With none of those, `cancel_fallback` is used."""
    cancel_fallback = 'home'

    def get_cancel_url(self):
        request = self.request
        for candidate in (request.POST.get('next'), request.GET.get('next'), request.META.get('HTTP_REFERER')):
            if not candidate or not url_has_allowed_host_and_scheme(
                    candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                continue
            parsed = urlparse(candidate)
            if parsed.path == request.path:             # the form itself (e.g. after a mistake): not a place to go back to
                continue
            return parsed.path + (f'?{parsed.query}' if parsed.query else '')
        return reverse(self.cancel_fallback)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cancel_url'] = self.get_cancel_url()
        return context


class ConfirmDeletePage(LoginRequiredMixin):
    template_name = 'music/confirm_delete.html'


# ---------------------------------------------------------------- home

# The home page remembers what you picked (one click on an artist or album) in the session,
# so it survives reloads and trips to other pages.
SESSION_ARTIST = 'home_artist'
SESSION_ALBUM = 'home_album'
SESSION_PLAYLIST = 'home_playlist'
SESSION_LIKED = 'home_liked'
LIKED_COLOR = '#4b2e83'                  # the purple of the "Liked Songs" heart (pages and the Tracks panel use it)


def _select(request, artist=None, album=None, playlist=None, liked=False):
    """Remember the selection. The Tracks panel shows one thing at a time (an album, a playlist or Liked Songs),
    whichever was picked last: picking an artist clears the album, picking an artist or album clears the playlist
    and Liked Songs, picking a playlist or Liked Songs clears the album (the artist stays)."""
    if playlist is not None or liked:
        request.session.pop(SESSION_ALBUM, None)
        if playlist is not None:
            request.session[SESSION_PLAYLIST] = playlist.pk
            request.session.pop(SESSION_LIKED, None)
        else:
            request.session[SESSION_LIKED] = True
            request.session.pop(SESSION_PLAYLIST, None)
        return
    if artist is not None:
        request.session[SESSION_ARTIST] = artist.pk
    if album is not None:
        request.session[SESSION_ARTIST] = album.artist_id
        request.session[SESSION_ALBUM] = album.pk
    elif artist is not None:
        request.session.pop(SESSION_ALBUM, None)
    request.session.pop(SESSION_PLAYLIST, None)
    request.session.pop(SESSION_LIKED, None)


def _selection(request):
    """The selected (artist, album, playlist, liked), ignoring anything that no longer exists or no longer matches."""
    artist = Artist.objects.filter(pk=request.session.get(SESSION_ARTIST)).first()
    album = None
    if artist is not None:
        album = Album.objects.filter(pk=request.session.get(SESSION_ALBUM), artist=artist).first()
    playlist = None
    if request.session.get(SESSION_PLAYLIST) is not None:
        playlist = Playlist.objects.filter(pk=request.session[SESSION_PLAYLIST]).first()    # anyone's playlist can be viewed
    liked = bool(request.session.get(SESSION_LIKED)) and playlist is None
    if playlist is not None or liked:
        album = None
    return artist, album, playlist, liked


def _albums_context(artist, album=None):
    if artist is None:
        return {'selected_artist': None}
    return {
        'selected_artist': artist,
        'selected_album_id': album.pk if album else None,
        'albums': artist.albums.order_by('-pk'),  # newest added first, right next to the add tile
        'album_add_url': f"{reverse('album_create')}?artist={artist.pk}",
    }


def _home_theme(artist, album, playlist=None, liked=False):
    """CSS variables (for <body style>) that tint the home page from what is selected.

    Each container follows its own selection: --artist-* tints the Artists panel, --album-* the Albums panel and
    --tracks-* the Tracks panel (purple for Liked Songs, the playlist's colour while a playlist is showing,
    otherwise the album's). A container whose selection is empty keeps the neutral look. The page background
    takes the most specific colour.
    """
    artist_color = artist.theme_color if artist else ''
    album_color = album.theme_color if album else ''        # an album with no cover of its own borrows its artist's colour
    playlist_color = playlist.theme_color if playlist else ''
    tracks_color = (LIKED_COLOR if liked else '') or playlist_color or album_color
    return ''.join([
        theme_style(tracks_color or artist_color),
        panel_vars('artist', artist_color),
        panel_vars('album', album_color),
        panel_vars('tracks', tracks_color),
    ])


def _tracks_context(album, user, playlist=None, liked=False):
    """Tracks of the selected playlist, album or Liked Songs, plus which of them this user has liked (heart buttons)."""
    if liked:
        likes = Like.objects.filter(user=user).select_related('track__album__artist')
        tracks = [like.track for like in likes]
    elif playlist is not None:
        entries = PlaylistTrack.objects.filter(playlist=playlist).select_related('track__album__artist')
        tracks = [entry.track for entry in entries]
    else:
        tracks = list(album.tracks.all()) if album else []
    liked_ids = set(Like.objects.filter(user=user, track__in=tracks).values_list('track_id', flat=True))
    return {'selected_album': album, 'selected_playlist': playlist, 'selected_liked': liked,
            'tracks': tracks, 'liked_ids': liked_ids}


@login_required
def home(request):
    artist, album, playlist, liked = _selection(request)
    return render(request, 'music/home.html', {
        # yours first (the ones you partner on are included), then everyone else's
        'playlists': editable_playlists(request.user).select_related('owner').annotate(track_count=Count('tracks', distinct=True)),
        'other_playlists': Playlist.objects.exclude(pk__in=editable_playlists(request.user).values('pk')).select_related('owner')
                           .annotate(track_count=Count('tracks', distinct=True)),
        'liked_count': request.user.likes.count(),
        'artists': Artist.objects.order_by('-pk')[:30],  # newest added first
        'theme_style': _home_theme(artist, album, playlist, liked),
        **_albums_context(artist, album),
        **_tracks_context(album, request.user, playlist, liked),
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
    playlist = get_object_or_404(Playlist, pk=pk)
    _select(request, playlist=playlist)
    artist = _selection(request)[0]
    return JsonResponse({
        'tracks': render_to_string('music/_home_tracks.html', _tracks_context(None, request.user, playlist), request),
        'theme': _home_theme(artist, None, playlist),
    })


@login_required
def home_liked_tracks(request):
    """One click on the pinned "Liked Songs" row: the songs this user has liked, newest first."""
    _select(request, liked=True)
    artist = _selection(request)[0]
    return JsonResponse({
        'tracks': render_to_string('music/_home_tracks.html', _tracks_context(None, request.user, liked=True), request),
        'theme': _home_theme(artist, None, liked=True),
    })


# ---------------------------------------------------------------- artists

class ArtistList(LoginRequiredMixin, ListView):
    model = Artist


class ArtistDetail(LoginRequiredMixin, DetailView):
    model = Artist


def _import_picture(request, form, instance, field_name, stem):
    """If a picture was picked in the Spotify search box (and no file was uploaded), download and attach it."""
    url = form.cleaned_data.get('spotify_image')
    if not url or getattr(instance, field_name):
        return
    try:
        imports.attach_picture(instance, field_name, url, stem)
    except spotify.SpotifyError as error:
        messages.warning(request, f'Saved, but the Spotify picture could not be added ({error}). You can upload one by editing it.')


class ArtistCreate(CancelLinkMixin, FormPage, CreateView):
    cancel_fallback = 'artist_list'
    model = Artist
    form_class = ArtistForm
    template_name = 'music/artist_form.html'  # centered card with a live preview
    extra_context = {'title': 'New artist'}

    def get_initial(self):
        initial = super().get_initial()
        if name := self.request.GET.get('name', '').strip()[:200]:
            initial['name'] = name                       # e.g. from the album form: "add this artist first"
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['spotify_enabled'] = spotify.is_configured()
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        _import_picture(self.request, form, self.object, 'image', self.object.name)
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


class AlbumCreate(CancelLinkMixin, FormPage, CreateView):
    cancel_fallback = 'album_list'
    model = Album
    form_class = AlbumForm
    template_name = 'music/album_form.html'  # centered card with a live preview
    extra_context = {'title': 'New album'}

    def get_initial(self):
        initial = super().get_initial()
        if artist_id := self.request.GET.get('artist'):
            initial['artist'] = artist_id
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['spotify_enabled'] = spotify.is_configured()
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        _import_picture(self.request, form, self.object, 'cover', self.object.title)
        album_id = form.cleaned_data.get('spotify_album_id')
        if album_id and form.cleaned_data.get('import_tracks'):
            try:
                added = imports.add_album_tracks(self.object, spotify.album_details(album_id)['tracks'])
                messages.success(self.request, f'Added {added} song{"s" if added != 1 else ""} from Spotify.')
            except spotify.SpotifyError as error:
                messages.warning(self.request, f'Saved, but the song list could not be added ({error}).')
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
    """Only the creator may do this (delete the playlist, invite or remove partners): for anyone else the page
    is "not found". Every signed-in user can still *see* a playlist."""

    def get_queryset(self):
        return Playlist.objects.filter(owner=self.request.user)


class EditablePlaylistsMixin(LoginRequiredMixin):
    """The creator and the partners they invited may edit a playlist; for anyone else the page is "not found"."""

    def get_queryset(self):
        return editable_playlists(self.request.user)


class PlaylistList(LoginRequiredMixin, ListView):
    model = Playlist

    def get_queryset(self):
        return Playlist.objects.select_related('owner').annotate(track_count=Count('tracks', distinct=True))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        partner_of = set(PlaylistPartner.objects.filter(user=user).values_list('playlist_id', flat=True))
        playlists = list(context['object_list'])
        context['mine'] = [p for p in playlists if p.owner_id == user.pk]
        context['shared_with_me'] = [p for p in playlists if p.pk in partner_of]          # you are a partner on these
        context['others'] = [p for p in playlists if p.owner_id != user.pk and p.pk not in partner_of]
        return context


class PlaylistDetail(LoginRequiredMixin, TrackListContextMixin, DetailView):
    model = Playlist
    queryset = Playlist.objects.select_related('owner')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entries = PlaylistTrack.objects.filter(playlist=self.object).select_related('track__album__artist')
        tracks = [entry.track for entry in entries]
        user = self.request.user
        is_owner = self.object.owner_id == user.pk
        partnerships = list(self.object.partnerships.select_related('user'))
        is_partner = any(p.user_id == user.pk for p in partnerships)
        context['tracks'] = tracks
        context['is_owner'] = is_owner
        context['is_partner'] = is_partner
        context['can_edit_playlist'] = is_owner or is_partner            # edit details, add and remove songs
        context['partnerships'] = partnerships
        if is_owner:                                                      # suggestions for the "add a partner" box
            taken = {self.object.owner_id, *(p.user_id for p in partnerships)}
            context['partner_candidates'] = list(
                get_user_model().objects.exclude(pk__in=taken).order_by('username').values_list('username', flat=True))
        context.update(self.get_track_context(tracks))
        return context


class PlaylistCreate(CancelLinkMixin, FormPage, CreateView):
    cancel_fallback = 'playlist_list'
    model = Playlist
    form_class = PlaylistForm
    template_name = 'music/playlist_form.html'  # centered card, same look as the artist / album forms
    extra_context = {'title': 'New playlist'}

    def form_valid(self, form):
        form.instance.owner = self.request.user
        response = super().form_valid(form)
        _select(self.request, playlist=self.object)  # the new playlist is selected on the home page
        return response


class PlaylistUpdate(EditablePlaylistsMixin, FormPage, UpdateView):
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
    playlist = get_object_or_404(editable_playlists(request.user), pk=request.POST.get('playlist'))   # yours, or one you partner on
    _, created = PlaylistTrack.objects.get_or_create(playlist=playlist, track=track)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':        # the "+ Playlist" menu adds in place
        return JsonResponse({'created': created, 'playlist': playlist.name, 'track': track.title})
    if created:
        messages.success(request, f'Added "{track.title}" to {playlist.name}.')
    else:
        messages.info(request, f'"{track.title}" is already in {playlist.name}.')
    return _redirect_back(request, track.album.get_absolute_url())


@login_required
@require_POST
def playlist_remove_track(request, pk, track_pk):
    playlist = get_object_or_404(editable_playlists(request.user), pk=pk)
    PlaylistTrack.objects.filter(playlist=playlist, track_id=track_pk).delete()
    messages.success(request, 'Track removed from playlist.')
    return redirect(playlist)


@login_required
@require_POST
def playlist_partner_add(request, pk):
    """The creator invites another user (by username) to look after the playlist."""
    playlist = get_object_or_404(Playlist, pk=pk, owner=request.user)
    username = request.POST.get('username', '').strip()
    person = get_user_model().objects.filter(username__iexact=username).first() if username else None
    if person is None:
        messages.error(request, f'There is no user named \u201c{username}\u201d.' if username else 'Type the username of the person to add.')
    elif person.pk == request.user.pk:
        messages.info(request, 'You already own this playlist.')
    elif PlaylistPartner.objects.filter(playlist=playlist, user=person).exists():
        messages.info(request, f'{person.username} is already a partner.')
    else:
        PlaylistPartner.objects.create(playlist=playlist, user=person)
        messages.success(request, f'{person.username} is now a partner on \u201c{playlist.name}\u201d.')
    return redirect(playlist)


@login_required
@require_POST
def playlist_partner_remove(request, pk, user_pk):
    """The creator removes a partner, or a partner leaves the playlist (removes themselves)."""
    playlist = get_object_or_404(Playlist, pk=pk)
    leaving = user_pk == request.user.pk
    if playlist.owner_id != request.user.pk and not leaving:
        raise Http404('Not found')
    partnership = get_object_or_404(PlaylistPartner, playlist=playlist, user_id=user_pk)
    name = partnership.user.username
    partnership.delete()
    if leaving:
        messages.success(request, f'You left \u201c{playlist.name}\u201d.')
        return redirect('playlist_list')
    messages.success(request, f'{name} is no longer a partner.')
    return redirect(playlist)


# ---------------------------------------------------------------- listening history

PLAY_DEDUPE_SECONDS = 20          # the same song twice within this long counts once (a page reload mid-song, a double send)


@login_required
@require_POST
def record_play(request):
    """The player calls this once a song has been listened to for a while; it feeds the profile's top lists."""
    try:
        track = Track.objects.get(pk=int(request.POST.get('track', '')))
    except (ValueError, Track.DoesNotExist):
        return JsonResponse({'recorded': False}, status=404)
    recent = timezone.now() - datetime.timedelta(seconds=PLAY_DEDUPE_SECONDS)
    if Play.objects.filter(user=request.user, track=track, played_at__gte=recent).exists():
        return JsonResponse({'recorded': False})
    Play.objects.create(user=request.user, track=track)
    return JsonResponse({'recorded': True})


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
        context['theme_style'] = theme_style(LIKED_COLOR)
        context.update(self.get_track_context(tracks))
        return context


# ---------------------------------------------------------------- Spotify lookups (for the New artist / New album forms)

def _spotify_json(call, *args):
    """Run a Spotify lookup and wrap the answer for the form's script: {"results": ...} or {"error": "..."}."""
    if not spotify.is_configured():
        return JsonResponse({'error': 'Spotify search is not set up.', 'enabled': False}, status=404)
    try:
        return JsonResponse({'enabled': True, **call(*args)})
    except spotify.SpotifyError as error:
        return JsonResponse({'error': str(error), 'enabled': True}, status=502)


def _our_artist_id(name):
    artist = Artist.objects.filter(name__iexact=name).first() if name else None
    return artist.pk if artist else None


@login_required
def spotify_artists(request):
    query = request.GET.get('q', '').strip()[:100]
    if not query:
        return JsonResponse({'enabled': spotify.is_configured(), 'results': []})
    return _spotify_json(lambda: {'results': spotify.search_artists(query)})


@login_required
def spotify_albums(request):
    query = request.GET.get('q', '').strip()[:100]
    if not query:
        return JsonResponse({'enabled': spotify.is_configured(), 'results': []})

    def call():
        results = spotify.search_albums(query)
        for item in results:
            item['artist_id'] = _our_artist_id(item['main_artist'])      # the matching artist in this catalog, if any
        return {'results': results}
    return _spotify_json(call)


@login_required
def artist_bio(request):
    """A short bio for an artist from Wikipedia, for the "Fill in from Spotify" box (Spotify has no bios).
    Answers {"bio": "..."} or {"bio": ""} when no suitable page exists; never an error page."""
    found = wikipedia.artist_bio(request.GET.get('name', ''))
    if not found:
        return JsonResponse({'bio': '', 'source': ''})
    # the text and its source are kept apart: the page shows a small "Bio from Wikipedia" credit under the bio
    return JsonResponse({'bio': found['bio'], 'source': found['url'], 'title': found['title']})


@login_required
def spotify_album(request, album_id):
    def call():
        album = spotify.album_details(album_id)
        album['artist_id'] = _our_artist_id(album['main_artist'])
        return {'album': album}
    return _spotify_json(call)


# ---------------------------------------------------------------- search

def _best_first(queryset, field, query):
    """Matches that start with what was typed come before matches that only contain it."""
    return queryset.annotate(
        starts=Case(When(**{f'{field}__istartswith': query}, then=0), default=1, output_field=IntegerField()),
    ).order_by('starts', field)


@login_required
def search_suggest(request):
    """Suggestions for the search box while typing: only artists, albums and songs that already exist."""
    query = request.GET.get('q', '').strip()[:100]
    results = []
    if query:
        for artist in _best_first(Artist.objects.filter(name__icontains=query), 'name', query)[:3]:
            results.append({'type': 'artist', 'title': artist.name, 'sub': 'Artist', 'url': artist.get_absolute_url(),
                            'image': artist.image.url if artist.image else ''})
        albums = Album.objects.filter(title__icontains=query).select_related('artist')
        for album in _best_first(albums, 'title', query)[:3]:
            results.append({'type': 'album', 'title': album.title, 'sub': f'Album · {album.artist.name}',
                            'url': album.get_absolute_url(), 'image': album.cover.url if album.cover else ''})
        tracks = Track.objects.filter(title__icontains=query).select_related('album__artist')
        for track in _best_first(tracks, 'title', query)[:4]:
            results.append({'type': 'track', 'title': track.title, 'sub': f'Song · {track.album.artist.name}',
                            'url': track.album.get_absolute_url(),
                            'image': track.album.cover.url if track.album.cover else ''})
    return JsonResponse({'query': query, 'results': results})


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
