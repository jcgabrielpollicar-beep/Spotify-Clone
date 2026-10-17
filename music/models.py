from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .colors import dominant_color, theme_style


class AccentColorMixin(models.Model):
    """Keeps `accent_color` (a '#rrggbb' picked from the picture) up to date whenever the picture changes.

    The subclass names its picture field in `accent_source`. The colour themes the artist / album page.
    """
    accent_source = ''
    accent_color = models.CharField(max_length=7, blank=True, editable=False)

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._picture_name = getattr(self, self.accent_source).name or ''

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)                 # the uploaded file is stored now, so it can be read
        picture = getattr(self, self.accent_source)
        name = picture.name or ''
        if name != self._picture_name or (name and not self.accent_color):
            self.refresh_accent()
        self._picture_name = name

    def refresh_accent(self):
        picture = getattr(self, self.accent_source)
        color = ''
        if picture.name:
            try:
                with picture.storage.open(picture.name, 'rb') as handle:
                    color = dominant_color(handle)
            except OSError:
                color = ''
        self.accent_color = color
        type(self).objects.filter(pk=self.pk).update(accent_color=color)   # no second full save
        return color

    @property
    def theme_color(self):
        return self.accent_color

    @property
    def theme_style(self):
        """CSS variables for <body style="...">; empty when there is no colour to use."""
        return theme_style(self.theme_color)


class Artist(AccentColorMixin):
    accent_source = 'image'
    name = models.CharField(max_length=200)
    bio = models.TextField(blank=True)
    bio_source = models.URLField(max_length=300, blank=True,
                                help_text='Where the bio came from (a Wikipedia page); shown as a small credit under the bio.')
    image = models.ImageField(upload_to='artists/', blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('artist_detail', args=[self.pk])

    @property
    def theme_color(self):
        # no photo of their own: borrow the colour of their newest album cover
        return self.accent_color or self.albums.exclude(accent_color='').values_list('accent_color', flat=True).first() or ''


class Album(AccentColorMixin):
    accent_source = 'cover'
    title = models.CharField(max_length=200)
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name='albums')
    cover = models.ImageField(upload_to='covers/', blank=True)
    release_date = models.DateField()

    class Meta:
        ordering = ['-release_date', 'title']

    def __str__(self):
        return f'{self.title} - {self.artist}'

    def get_absolute_url(self):
        return reverse('album_detail', args=[self.pk])

    @property
    def theme_color(self):
        # no cover of its own: use the artist's colour
        return self.accent_color or self.artist.theme_color


class Track(models.Model):
    album = models.ForeignKey(Album, on_delete=models.CASCADE, related_name='tracks')
    title = models.CharField(max_length=200)
    track_number = models.PositiveSmallIntegerField(default=1)
    duration = models.DurationField(help_text='Format m:ss, e.g. 3:25')
    audio_file = models.FileField(upload_to='audio/', blank=True)
    # Optional link to an official 30-second preview hosted elsewhere (set from the admin or a script,
    # not from the public forms). An uploaded audio_file always wins over it.
    preview_url = models.URLField(max_length=500, blank=True)

    class Meta:
        ordering = ['album', 'track_number', 'title']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        # Tracks have no page of their own; they live on the album page.
        return self.album.get_absolute_url()

    @property
    def playable_url(self):
        """What the player should play: the uploaded file, else the preview link, else nothing."""
        if self.audio_file:
            return self.audio_file.url
        return self.preview_url

    @property
    def is_preview_only(self):
        return not self.audio_file and bool(self.preview_url)

    @property
    def duration_seconds(self):
        return int(self.duration.total_seconds())

    @property
    def duration_display(self):
        total = int(self.duration.total_seconds())
        return f'{total // 60}:{total % 60:02d}'


class Playlist(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='playlists')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    tracks = models.ManyToManyField(Track, through='PlaylistTrack', related_name='playlists')
    partners = models.ManyToManyField(settings.AUTH_USER_MODEL, through='PlaylistPartner', related_name='partner_playlists', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('playlist_detail', args=[self.pk])

    def is_partner(self, user):
        return user.is_authenticated and PlaylistPartner.objects.filter(playlist=self, user=user).exists()

    def can_edit(self, user):
        """The creator and the partners the creator added may change the playlist and its songs."""
        return user.is_authenticated and (self.owner_id == user.pk or self.is_partner(user))

    def _cover_album(self):
        """The album of the first track (in the order they were added) that has a cover, or None."""
        entry = (PlaylistTrack.objects.filter(playlist=self).exclude(track__album__cover='')
                 .select_related('track__album').first())
        return entry.track.album if entry else None

    @property
    def cover_url(self):
        """A playlist has no picture of its own: it shows the cover of its first track's album."""
        album = self._cover_album()
        return album.cover.url if album else ''

    @property
    def theme_color(self):
        album = self._cover_album()
        return album.accent_color if album else ''

    @property
    def theme_style(self):
        return theme_style(self.theme_color)


class PlaylistTrack(models.Model):
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE)
    track = models.ForeignKey(Track, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['added_at']
        constraints = [
            models.UniqueConstraint(fields=['playlist', 'track'], name='unique_track_per_playlist'),
        ]


class PlaylistPartner(models.Model):
    """A user the creator invited to look after a playlist with them (edit it, add and remove songs).

    Partners cannot delete the playlist or invite other people: that stays with the creator.
    """
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name='partnerships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='partnerships')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['added_at']
        constraints = [
            models.UniqueConstraint(fields=['playlist', 'user'], name='unique_partner_per_playlist'),
        ]

    def __str__(self):
        return f'{self.user} partners on {self.playlist}'


def editable_playlists(user):
    """Playlists this user may change: their own and the ones they were invited to as a partner."""
    return Playlist.objects.filter(models.Q(owner=user) | models.Q(partnerships__user=user)).distinct()


class Play(models.Model):
    """One listen: written by the player after a song has really been listened to for a while (static/js/player.js).

    The profile page counts these per month to show someone's top artists and top songs.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='plays')
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name='plays')
    played_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-played_at']
        indexes = [models.Index(fields=['user', 'played_at'])]

    def __str__(self):
        return f'{self.user} played {self.track}'


class Like(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='likes')
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'track'], name='unique_like_per_user_track'),
        ]
