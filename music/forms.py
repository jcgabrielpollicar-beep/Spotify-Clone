from django import forms

from .models import Album, Artist, Playlist, Track


class ArtistForm(forms.ModelForm):
    class Meta:
        model = Artist
        fields = ['name', 'bio', 'image']


class AlbumForm(forms.ModelForm):
    class Meta:
        model = Album
        fields = ['title', 'artist', 'cover', 'release_date']
        widgets = {'release_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}


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
