"""Applies what was looked up on Spotify when an artist or album is saved: the picture and the song list."""
import datetime
import io

from django.core.files.base import ContentFile
from django.utils.text import slugify
from PIL import Image

from . import spotify
from .models import Track


def attach_picture(instance, field_name, url, stem):
    """Download the Spotify picture at `url` and store it as instance.<field_name> (a clean JPEG copy).

    Raises spotify.SpotifyError when the address isn't allowed, the download fails, or it isn't a real image.
    """
    data = spotify.download_image(url)
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ('JPEG', 'PNG', 'WEBP'):
                raise spotify.SpotifyError('The picture is not a normal image')
            picture = img.convert('RGB')                  # also drops any embedded metadata
            picture.thumbnail((800, 800))
    except spotify.SpotifyError:
        raise
    except Exception as error:                            # damaged or not an image at all
        raise spotify.SpotifyError('The picture could not be read') from error
    out = io.BytesIO()
    picture.save(out, 'JPEG', quality=90, optimize=True)
    getattr(instance, field_name).save(f'{slugify(stem) or "spotify"}.jpg', ContentFile(out.getvalue()), save=True)


def add_album_tracks(album, tracks):
    """Create the album's songs from Spotify's list (title, number, length). Songs whose number is already
    taken are left alone, so running it twice never doubles anything. Returns how many were created."""
    taken = set(album.tracks.values_list('track_number', flat=True))
    created = 0
    for item in tracks:
        number = int(item.get('number') or 0)
        title = (item.get('title') or '').strip()[:200]
        if not title or not 1 <= number <= 99 or number in taken:
            continue
        seconds = max(1, min(int(item.get('seconds') or 0), 3600 * 3))
        Track.objects.create(album=album, title=title, track_number=number, duration=datetime.timedelta(seconds=seconds))
        taken.add(number)
        created += 1
    return created
