from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render
from django.views.generic import CreateView

from music.colors import theme_style
from music.stats import month_start, top_artists, top_songs
from music.views import TrackListContextMixin

from .forms import ProfileForm
from .models import Profile

TOP_ARTISTS = 5
TOP_SONGS = 30


class Register(CreateView):
    form_class = UserCreationForm
    template_name = 'accounts/register.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        return redirect('home')


class _TrackContext(TrackListContextMixin):
    """Lets a plain function view reuse the track-row context (liked hearts, the "+ Playlist" menu)."""

    def __init__(self, request):
        self.request = request


@login_required
def profile(request):
    me = Profile.for_user(request.user)
    since = month_start()
    artists = top_artists(request.user, TOP_ARTISTS, since)
    songs = top_songs(request.user, TOP_SONGS, since)
    tracks = [track for track, _plays in songs]
    context = {
        'profile': me,
        'theme_style': theme_style(me.theme_color),
        'month': since,
        'top_artists': artists,
        'tracks': tracks,
        'playlist_count': request.user.playlists.count(),
        'like_count': request.user.likes.count(),
    }
    context.update(_TrackContext(request).get_track_context(tracks))
    return render(request, 'accounts/profile.html', context)


@login_required
def profile_edit(request):
    me = Profile.for_user(request.user)
    form = ProfileForm(request.POST or None, request.FILES or None, instance=me)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Profile saved.')
        return redirect('profile')
    return render(request, 'accounts/profile_form.html', {'form': form, 'profile': me})
