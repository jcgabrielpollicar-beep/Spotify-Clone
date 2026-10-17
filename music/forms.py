import re

from django import forms
from django.urls import reverse

from . import spotify
from .models import Album, Artist, Playlist, Track

SPOTIFY_ID = re.compile(r'^[A-Za-z0-9]{10,40}$')


class SpotifyPictureMixin:
    """The hidden `spotify_image` field: the address of a picture picked in the Spotify search box. The picture is
    downloaded when the form is saved (never trusted blindly: see spotify.allowed_image_url)."""

    def clean_spotify_image(self):
        url = self.cleaned_data.get('spotify_image', '').strip()
        if url and not spotify.allowed_image_url(url):
            raise forms.ValidationError('That picture address is not allowed.')
        return url


class ArtistForm(SpotifyPictureMixin, forms.ModelForm):
    spotify_image = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Artist
        fields = ['name', 'bio', 'bio_source', 'image']
        widgets = {'bio_source': forms.HiddenInput}

    def clean_bio_source(self):
        """Only a Wikipedia address is accepted here (it comes from the Spotify box), and only while there is a bio."""
        url = self.cleaned_data.get('bio_source', '').strip()
        return url if url.startswith('https://en.wikipedia.org/wiki/') else ''

    def clean(self):
        cleaned = super().clean()
        if not (cleaned.get('bio') or '').strip():
            cleaned['bio_source'] = ''                       # no bio left, so nothing to credit
        return cleaned


class ArtistSelect(forms.Select):
    """The Artist dropdown of the album form. Each option carries the artist's photo address so the page script
    (static/js/artist_picker.js) can show a nicer picker with pictures and a search box; without JavaScript it is
    still an ordinary dropdown."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, 'instance', None)
        if instance is not None and instance.image:
            option['attrs']['data-image'] = instance.image.url
        return option


class AlbumForm(SpotifyPictureMixin, forms.ModelForm):
    spotify_image = forms.CharField(required=False, widget=forms.HiddenInput)
    spotify_album_id = forms.CharField(required=False, widget=forms.HiddenInput)
    import_tracks = forms.BooleanField(required=False, initial=True, label='Also add the song list from Spotify')

    class Meta:
        model = Album
        fields = ['title', 'artist', 'cover', 'release_date']
        widgets = {
            'artist': ArtistSelect(attrs={'data-artist-picker': ''}),
            'release_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['artist'].widget.attrs['data-new-url'] = reverse('artist_create')    # the picker's "+ New artist" link

    def clean_spotify_album_id(self):
        value = self.cleaned_data.get('spotify_album_id', '').strip()
        if value and not SPOTIFY_ID.match(value):
            raise forms.ValidationError('That is not a Spotify album id.')
        return value


class TrackForm(forms.ModelForm):
    class Meta:
        model = Track
        fields = ['title', 'track_number', 'duration', 'audio_file']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # show 5:20 (what the hint asks for) instead of Django's default 00:05:20
            self.initial['duration'] = self.instance.duration_display


class PlaylistForm(forms.ModelForm):
    class Meta:
        model = Playlist
        fields = ['name', 'description']
