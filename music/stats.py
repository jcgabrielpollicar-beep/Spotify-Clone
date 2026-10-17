"""Listening statistics for the profile page: top artists and top songs of the current month."""
from django.db.models import Count, Max
from django.utils import timezone

from .models import Artist, Play, Track


def month_start(now=None):
    """Midnight on the first day of the current month."""
    now = timezone.localtime(now or timezone.now())
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def recently_played(user, limit=12):
    """The songs this user listened to last, newest first, each song once (for the home page's "Recently played")."""
    rows = list(
        Play.objects.filter(user=user)
        .values('track')
        .annotate(last=Max('played_at'))
        .order_by('-last')[:limit]
    )
    tracks = Track.objects.select_related('album__artist').in_bulk([row['track'] for row in rows])
    return [tracks[row['track']] for row in rows]


def top_artists(user, limit=5, since=None):
    """[(artist, plays), ...] for this user, most played first; ties go to whoever was played most recently."""
    since = since or month_start()
    rows = list(
        Play.objects.filter(user=user, played_at__gte=since)
        .values('track__album__artist')
        .annotate(plays=Count('id'), last=Max('played_at'))
        .order_by('-plays', '-last')[:limit]
    )
    artists = Artist.objects.in_bulk([row['track__album__artist'] for row in rows])
    return [(artists[row['track__album__artist']], row['plays']) for row in rows]


def top_songs(user, limit=30, since=None):
    """[(track, plays), ...] for this user, most played first; ties go to whatever was played most recently."""
    since = since or month_start()
    rows = list(
        Play.objects.filter(user=user, played_at__gte=since)
        .values('track')
        .annotate(plays=Count('id'), last=Max('played_at'))
        .order_by('-plays', '-last')[:limit]
    )
    tracks = Track.objects.select_related('album__artist').in_bulk([row['track'] for row in rows])
    return [(tracks[row['track']], row['plays']) for row in rows]
