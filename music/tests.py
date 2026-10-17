import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Album, Artist, Like, Playlist, PlaylistTrack, Track

User = get_user_model()


class BaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', password='pw-alice-123')
        cls.bob = User.objects.create_user('bob', password='pw-bob-123')
        cls.artist = Artist.objects.create(name='Daft Punk', bio='French duo')
        cls.album = Album.objects.create(title='Discovery', artist=cls.artist, release_date=datetime.date(2001, 3, 12))
        cls.track = Track.objects.create(album=cls.album, title='One More Time', track_number=1,
                                         duration=datetime.timedelta(minutes=5, seconds=20))
        cls.playlist = Playlist.objects.create(owner=cls.alice, name='Favourites')

    def login(self, user='alice'):
        self.client.login(username=user, password=f'pw-{user}-123')


class AuthTests(BaseTestCase):
    def test_pages_require_login(self):
        urls = [
            reverse('home'), reverse('artist_list'), reverse('artist_detail', args=[self.artist.pk]),
            reverse('album_list'), reverse('album_detail', args=[self.album.pk]),
            reverse('playlist_list'), reverse('liked_songs'), reverse('search'), reverse('profile'),
            reverse('artist_create'), reverse('artist_delete', args=[self.artist.pk]),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse('login'), response.url, url)

    def test_register_logs_user_in(self):
        response = self.client.post(reverse('register'), {
            'username': 'carol', 'password1': 'a-Strong-pass-99', 'password2': 'a-Strong-pass-99',
        })
        self.assertRedirects(response, reverse('home'))
        self.assertTrue(User.objects.filter(username='carol').exists())
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)

    def test_login_and_logout(self):
        response = self.client.post(reverse('login'), {'username': 'alice', 'password': 'pw-alice-123'})
        self.assertRedirects(response, reverse('home'))
        self.client.post(reverse('logout'))
        self.assertEqual(self.client.get(reverse('home')).status_code, 302)


class HomeTests(BaseTestCase):
    """The home page: pick an artist -> its albums; pick an album -> its tracks."""

    def test_home_shows_all_four_panels(self):
        Playlist.objects.create(owner=self.bob, name='Bobs secret')
        self.login()
        response = self.client.get(reverse('home'))
        for panel in ('area-playlists', 'area-albums', 'area-artists', 'area-tracks'):
            self.assertContains(response, panel)
        self.assertContains(response, 'Favourites')       # own playlist
        self.assertNotContains(response, 'Bobs secret')   # someone else's playlist
        self.assertContains(response, 'Daft Punk')        # artist card
        self.assertContains(response, reverse('artist_create'))  # "add artist" tile

    def test_nothing_selected_shows_hints_instead_of_albums_and_tracks(self):
        self.login()
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Select an artist or add one first')
        self.assertContains(response, 'Select an album or a playlist to see its tracks')
        self.assertNotContains(response, 'add album')   # no add-album tile until an artist is picked
        self.assertNotContains(response, 'Discovery')   # albums are hidden until an artist is picked
        self.assertNotContains(response, 'One More Time')

    def test_first_time_user_with_no_data_sees_the_hint_and_add_artist_tile(self):
        Artist.objects.all().delete()   # cascades to albums and tracks
        self.login()
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Select an artist or add one first')
        self.assertContains(response, 'add artist')

    def test_selecting_an_artist_returns_albums_and_add_tile_prefilled_with_that_artist(self):
        self.login()
        data = self.client.get(reverse('home_artist_albums', args=[self.artist.pk])).json()
        self.assertIn('Discovery', data['albums'])
        self.assertIn('add album', data['albums'])
        self.assertIn(f"{reverse('album_create')}?artist={self.artist.pk}", data['albums'])
        self.assertIn('Select an album or a playlist to see its tracks', data['tracks'])  # Tracks panel is reset

    def test_selecting_an_album_returns_its_tracks(self):
        self.login()
        data = self.client.get(reverse('home_album_tracks', args=[self.album.pk])).json()
        self.assertIn('One More Time', data['tracks'])
        self.assertIn('5:20', data['tracks'])
        self.assertIn(reverse('track_create', args=[self.album.pk]), data['tracks'])  # "+ Add track"

    def test_only_the_selected_artists_albums_are_shown(self):
        other = Artist.objects.create(name='Air')
        Album.objects.create(title='Moon Safari', artist=other, release_date=datetime.date(1998, 1, 1))
        self.login()
        data = self.client.get(reverse('home_artist_albums', args=[self.artist.pk])).json()
        self.assertIn('Discovery', data['albums'])
        self.assertNotIn('Moon Safari', data['albums'])

    def test_selection_is_remembered_across_page_loads(self):
        self.login()
        self.client.get(reverse('home_album_tracks', args=[self.album.pk]))
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Discovery')        # the artist's albums
        self.assertContains(response, 'add album')
        self.assertContains(response, 'One More Time')    # the album's tracks
        self.assertNotContains(response, 'Select an artist or add one first')
        self.assertNotContains(response, 'Select an album or a playlist to see its tracks')
        self.assertContains(response, 'is-selected')

    def test_picking_a_different_artist_clears_the_album(self):
        other = Artist.objects.create(name='Air')
        self.login()
        self.client.get(reverse('home_album_tracks', args=[self.album.pk]))
        self.client.get(reverse('home_artist_albums', args=[other.pk]))
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, 'One More Time')
        self.assertContains(response, 'Select an album or a playlist to see its tracks')

    def test_deleted_selection_falls_back_to_the_hints(self):
        self.login()
        self.client.get(reverse('home_artist_albums', args=[self.artist.pk]))
        self.artist.delete()
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select an artist or add one first')

    def test_selection_endpoints_require_login_and_404_for_unknown_ids(self):
        for url in (reverse('home_artist_albums', args=[self.artist.pk]), reverse('home_album_tracks', args=[self.album.pk])):
            self.assertEqual(self.client.get(url).status_code, 302)
        self.login()
        self.assertEqual(self.client.get(reverse('home_artist_albums', args=[9999])).status_code, 404)
        self.assertEqual(self.client.get(reverse('home_album_tracks', args=[9999])).status_code, 404)

    def test_adding_an_artist_selects_it(self):
        self.login()
        self.client.post(reverse('artist_create'), {'name': 'Air', 'bio': ''})
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'add album')   # its (empty) albums row with the add tile
        self.assertNotContains(response, 'Select an artist or add one first')
        self.assertEqual(response.context['selected_artist'].name, 'Air')

    def test_adding_an_album_selects_it_and_its_artist(self):
        self.login()
        self.client.post(reverse('album_create'), {
            'title': 'Homework', 'artist': self.artist.pk, 'release_date': '1997-01-20',
        })
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['selected_artist'], self.artist)
        self.assertEqual(response.context['selected_album'].title, 'Homework')

    def test_newest_artist_comes_first(self):
        newer = Artist.objects.create(name='Aaron')  # sorts first alphabetically, but was added last
        self.login()
        artists = list(self.client.get(reverse('home')).context['artists'])
        self.assertEqual(artists[0], newer)

    def test_newest_album_comes_right_after_add_tile(self):
        newer = Album.objects.create(title='Homework', artist=self.artist, release_date=datetime.date(1997, 1, 20))
        self.login()
        self.client.get(reverse('home_artist_albums', args=[self.artist.pk]))
        albums = list(self.client.get(reverse('home')).context['albums'])
        self.assertEqual(albums[0], newer)  # most recently added, even though Discovery is newer by release date


class CatalogCrudTests(BaseTestCase):
    def setUp(self):
        self.login()

    def test_artist_crud(self):
        response = self.client.post(reverse('artist_create'), {'name': 'Air', 'bio': 'x'})
        artist = Artist.objects.get(name='Air')
        self.assertRedirects(response, artist.get_absolute_url())

        self.client.post(reverse('artist_update', args=[artist.pk]), {'name': 'AIR', 'bio': 'y'})
        artist.refresh_from_db()
        self.assertEqual(artist.name, 'AIR')

        # GET shows the confirmation page and deletes nothing
        self.assertEqual(self.client.get(reverse('artist_delete', args=[artist.pk])).status_code, 200)
        self.assertTrue(Artist.objects.filter(pk=artist.pk).exists())
        self.client.post(reverse('artist_delete', args=[artist.pk]))
        self.assertFalse(Artist.objects.filter(pk=artist.pk).exists())

    def test_album_and_artist_lists_use_the_scrolling_card_box(self):
        for name, expected in (('album_list', 'Discovery'), ('artist_list', 'Daft Punk')):
            response = self.client.get(reverse(name))
            self.assertContains(response, 'class="list-card"')
            self.assertContains(response, 'class="list-scroll"')
            self.assertContains(response, expected)

    def test_album_and_artist_detail_pages_use_the_same_box(self):
        for url in (self.album.get_absolute_url(), self.artist.get_absolute_url()):
            response = self.client.get(url)
            self.assertContains(response, 'class="list-card is-detail"')
            self.assertContains(response, 'class="detail-scroll"')
            self.assertContains(response, 'class="detail-head"')   # the gradient header with cover, name and buttons

    def test_empty_album_list_has_no_scroll_box(self):
        Album.objects.all().delete()
        response = self.client.get(reverse('album_list'))
        self.assertContains(response, 'No albums yet.')
        self.assertNotContains(response, 'class="list-scroll"')

    def test_artist_form_has_card_and_preview(self):
        response = self.client.get(reverse('artist_create'))
        self.assertTemplateUsed(response, 'music/artist_form.html')
        for needle in ('id="preview-toggle"', 'id="artist-preview"', 'name="name"', 'name="bio"', 'name="image"'):
            self.assertContains(response, needle)

    def test_artist_edit_form_is_prefilled(self):
        response = self.client.get(reverse('artist_update', args=[self.artist.pk]))
        self.assertTemplateUsed(response, 'music/artist_form.html')
        self.assertContains(response, 'value="Daft Punk"')
        self.assertContains(response, 'French duo')  # bio textarea

    def test_artist_form_shows_validation_errors(self):
        response = self.client.post(reverse('artist_create'), {'name': '', 'bio': 'x'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertFalse(Artist.objects.filter(bio='x').exists())

    def test_album_form_has_card_and_preview(self):
        response = self.client.get(reverse('album_create'))
        self.assertTemplateUsed(response, 'music/album_form.html')
        for needle in ('id="preview-toggle"', 'id="album-preview"', 'name="title"', 'name="artist"',
                       'name="cover"', 'name="release_date"', 'type="date"'):
            self.assertContains(response, needle)

    def test_album_edit_form_is_prefilled(self):
        response = self.client.get(reverse('album_update', args=[self.album.pk]))
        self.assertTemplateUsed(response, 'music/album_form.html')
        self.assertContains(response, 'value="Discovery"')
        self.assertContains(response, 'value="2001-03-12"')
        self.assertContains(response, f'value="{self.artist.pk}" selected')

    def test_album_form_shows_validation_errors(self):
        response = self.client.post(reverse('album_create'), {'title': '', 'artist': self.artist.pk, 'release_date': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertFalse(Album.objects.filter(release_date__isnull=True).exists())

    def test_album_create_prefills_artist(self):
        response = self.client.get(reverse('album_create') + f'?artist={self.artist.pk}')
        self.assertEqual(response.context['form'].initial['artist'], str(self.artist.pk))

    def test_album_crud(self):
        self.client.post(reverse('album_create'), {
            'title': 'Homework', 'artist': self.artist.pk, 'release_date': '1997-01-20',
        })
        album = Album.objects.get(title='Homework')
        self.client.post(reverse('album_update', args=[album.pk]), {
            'title': 'Homework (Remaster)', 'artist': self.artist.pk, 'release_date': '1997-01-20',
        })
        album.refresh_from_db()
        self.assertEqual(album.title, 'Homework (Remaster)')
        self.client.post(reverse('album_delete', args=[album.pk]))
        self.assertFalse(Album.objects.filter(pk=album.pk).exists())

    def test_track_add_edit_delete_from_album(self):
        response = self.client.post(reverse('track_create', args=[self.album.pk]), {
            'title': 'Aerodynamic', 'track_number': 2, 'duration': '3:27',
        })
        self.assertRedirects(response, self.album.get_absolute_url())
        track = Track.objects.get(title='Aerodynamic')
        self.assertEqual(track.duration_display, '3:27')

        self.client.post(reverse('track_update', args=[track.pk]), {
            'title': 'Aerodynamic!', 'track_number': 2, 'duration': '3:28',
        })
        track.refresh_from_db()
        self.assertEqual(track.title, 'Aerodynamic!')

        response = self.client.post(reverse('track_delete', args=[track.pk]))
        self.assertRedirects(response, self.album.get_absolute_url())
        self.assertFalse(Track.objects.filter(pk=track.pk).exists())

    def test_album_page_lists_tracks(self):
        response = self.client.get(self.album.get_absolute_url())
        self.assertContains(response, 'One More Time')
        self.assertContains(response, '5:20')

    def test_deleting_artist_cascades(self):
        self.client.post(reverse('artist_delete', args=[self.artist.pk]))
        self.assertFalse(Album.objects.exists())
        self.assertFalse(Track.objects.exists())


def _jpeg(color, size=(80, 80), stripe=None):
    """A small in-memory JPEG upload (optionally with a coloured stripe)."""
    import io
    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image
    img = Image.new('RGB', size, color)
    if stripe:
        for x in range(size[0] // 4):
            for y in range(size[1]):
                img.putpixel((x, y), stripe)
    buffer = io.BytesIO()
    img.save(buffer, 'JPEG', quality=95)
    return SimpleUploadedFile('cover.jpg', buffer.getvalue(), content_type='image/jpeg')


class AccentColorTests(BaseTestCase):
    """The album / artist page takes its colour from the cover (music/colors.py)."""

    def test_dominant_color_is_the_vivid_colour_toned_for_white_text(self):
        from music.colors import dominant_color, from_hex, luminance
        red = dominant_color(_jpeg((200, 30, 40)))
        r, g, b = from_hex(red)
        self.assertRegex(red, r'^#[0-9a-f]{6}$')
        self.assertTrue(r > g and r > b, red)              # still reads as red
        self.assertLessEqual(luminance((r, g, b)), 0.2)    # dark enough for white text
        yellow = dominant_color(_jpeg((250, 235, 20)))     # a bright yellow cover must be darkened a lot
        self.assertLessEqual(luminance(from_hex(yellow)), 0.2)
        self.assertGreater(from_hex(yellow)[0], from_hex(yellow)[2])

    def test_vivid_colour_beats_a_white_background(self):
        from music.colors import dominant_color, from_hex
        # mostly white with a blue stripe: the stripe's colour wins, not grey
        color = dominant_color(_jpeg((250, 250, 250), stripe=(20, 60, 200)))
        r, g, b = from_hex(color)
        self.assertGreater(b, r)

    def test_greyscale_and_broken_images(self):
        from music.colors import dominant_color, from_hex
        grey = from_hex(dominant_color(_jpeg((128, 128, 128))))
        self.assertLess(max(grey) - min(grey), 25)         # stays neutral
        self.assertEqual(dominant_color(b''), '')
        import io
        self.assertEqual(dominant_color(io.BytesIO(b'this is not an image')), '')

    def test_theme_style_only_accepts_real_hex_colours(self):
        from music.colors import theme_style
        self.assertEqual(theme_style(''), '')
        self.assertEqual(theme_style('red; background: url(x)'), '')          # no CSS injection through the field
        style = theme_style('#7f7715')
        for variable in ('--accent:#7f7715;', '--accent-mid:#', '--accent-page:#'):
            self.assertIn(variable, style)

    def test_saving_a_cover_picks_its_colour_and_changing_or_clearing_it_updates(self):
        import tempfile
        from django.test import override_settings
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            album = Album.objects.create(title='Red', artist=self.artist, release_date=datetime.date(2020, 1, 1),
                                         cover=_jpeg((200, 30, 40)))
            album.refresh_from_db()
            red = album.accent_color
            self.assertRegex(red, r'^#[0-9a-f]{6}$')
            album.cover = _jpeg((30, 60, 200))
            album.save()
            album.refresh_from_db()
            self.assertNotEqual(album.accent_color, red)
            album.cover = ''
            album.save()
            album.refresh_from_db()
            self.assertEqual(album.accent_color, '')

    def test_album_without_cover_borrows_the_artists_colour_and_artist_borrows_an_albums(self):
        import tempfile
        from django.test import override_settings
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.assertEqual(self.album.theme_style, '')                       # nothing anywhere: no theme
            artist = Artist.objects.create(name='Air', image=_jpeg((30, 60, 200)))
            plain_album = Album.objects.create(title='Moon Safari', artist=artist, release_date=datetime.date(1998, 1, 1))
            self.assertEqual(plain_album.theme_color, Artist.objects.get(pk=artist.pk).accent_color)
            self.assertTrue(plain_album.theme_style.startswith('--accent:#'))
            # an artist without a photo uses the colour of an album that has a cover
            solo = Artist.objects.create(name='Solo')
            Album.objects.create(title='Cover', artist=solo, release_date=datetime.date(2001, 1, 1), cover=_jpeg((200, 30, 40)))
            self.assertTrue(solo.theme_color.startswith('#'))

    def test_pages_carry_the_theme_on_the_body(self):
        self.login()
        plain = self.client.get(self.album.get_absolute_url()).content.decode()
        self.assertIn('style=""', plain.split('<body', 1)[1].split('>', 1)[0])          # no colour yet: default look
        Album.objects.filter(pk=self.album.pk).update(accent_color='#7f7715')
        themed = self.client.get(self.album.get_absolute_url()).content.decode()
        body_tag = themed.split('<body', 1)[1].split('>', 1)[0]
        self.assertIn('--accent:#7f7715;', body_tag)
        self.assertIn('--accent-page:#', body_tag)
        # other pages keep the quiet default
        self.assertIn('style=""', self.client.get(reverse('home')).content.decode().split('<body', 1)[1].split('>', 1)[0])

    def test_refresh_accents_command_fills_in_existing_images(self):
        import tempfile
        from io import StringIO
        from django.core.management import call_command
        from django.test import override_settings
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            album = Album.objects.create(title='Red', artist=self.artist, release_date=datetime.date(2020, 1, 1), cover=_jpeg((200, 30, 40)))
            Album.objects.filter(pk=album.pk).update(accent_color='')            # as if it was added before this feature
            out = StringIO()
            call_command('refresh_accents', stdout=out)
            album.refresh_from_db()
            self.assertRegex(album.accent_color, r'^#[0-9a-f]{6}$')
            self.assertIn('Done.', out.getvalue())


class HomeThemeTests(BaseTestCase):
    """Home page panels are tinted by the selected artist (Artists, Albums) and album (Tracks)."""

    def setUp(self):
        self.login()
        Artist.objects.filter(pk=self.artist.pk).update(accent_color='#114a69')       # blue artist
        Album.objects.filter(pk=self.album.pk).update(accent_color='#801521')         # red album

    def test_panel_vars_stay_dark_and_ignore_bad_values(self):
        from music.colors import from_hex, luminance, panel_vars
        style = panel_vars('artist', '#b4251d')
        for name in ('panel', 'inner', 'card', 'lift', 'hi'):
            self.assertIn(f'--artist-{name}:#', style)
        for name in ('panel', 'inner', 'card', 'lift'):             # the backgrounds are dark; only the outline is light
            value = style.split(f'--artist-{name}:')[1][:7]
            self.assertLess(luminance(from_hex(value)), 0.05, name)
        self.assertGreater(luminance(from_hex(style.split('--artist-hi:')[1][:7])), 0.2)
        self.assertEqual(panel_vars('artist', ''), '')
        self.assertEqual(panel_vars('artist', 'red; x: y'), '')

    def test_nothing_selected_means_the_neutral_look(self):
        body_tag = self.client.get(reverse('home')).content.decode().split('<body', 1)[1].split('>', 1)[0]
        self.assertIn('style=""', body_tag)

    def test_selecting_an_artist_tints_only_the_artists_container(self):
        data = self.client.get(reverse('home_artist_albums', args=[self.artist.pk])).json()
        theme = data['theme']
        self.assertIn('--artist-panel:#', theme)
        self.assertIn('--accent-page:#', theme)
        # no album picked yet: the Albums / Tracks containers stay neutral
        self.assertNotIn('--album-panel', theme)

    def test_selecting_an_album_tints_the_albums_container_with_its_own_cover_colour(self):
        data = self.client.get(reverse('home_album_tracks', args=[self.album.pk])).json()
        theme = data['theme']
        artist_panel = theme.split('--artist-panel:')[1][:7]
        album_panel = theme.split('--album-panel:')[1][:7]
        self.assertNotEqual(artist_panel, album_panel)           # blue artist, red album

    def test_home_page_renders_the_remembered_selection_with_its_tint(self):
        self.client.get(reverse('home_album_tracks', args=[self.album.pk]))
        body_tag = self.client.get(reverse('home')).content.decode().split('<body', 1)[1].split('>', 1)[0]
        for variable in ('--artist-panel:#', '--album-panel:#', '--accent-page:#'):
            self.assertIn(variable, body_tag)

    def test_album_without_a_colour_borrows_the_artists(self):
        Album.objects.filter(pk=self.album.pk).update(accent_color='')
        theme = self.client.get(reverse('home_album_tracks', args=[self.album.pk])).json()['theme']
        self.assertEqual(theme.split('--artist-panel:')[1][:7], theme.split('--album-panel:')[1][:7])


class MediaRangeTests(TestCase):
    """Uploaded songs are served with HTTP Range support so the seek bar can jump to any point of a long song."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from django.test import override_settings
        self._dir = tempfile.TemporaryDirectory()
        (Path(self._dir.name) / 'audio').mkdir()
        self.data = bytes(range(256)) * 40                                   # 10240 bytes
        (Path(self._dir.name) / 'audio' / 'song.mp3').write_bytes(self.data)
        override = override_settings(MEDIA_ROOT=self._dir.name, DEBUG=True)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._dir.cleanup)
        from music.media_views import serve_media
        from django.test import RequestFactory
        self.serve = lambda path, **headers: serve_media(RequestFactory().get('/media/' + path, **headers), path)

    def body(self, response):
        return b''.join(response.streaming_content)

    def test_whole_file_advertises_range_support(self):
        response = self.serve('audio/song.mp3')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Accept-Ranges'], 'bytes')
        self.assertEqual(response['Content-Type'], 'audio/mpeg')
        self.assertEqual(self.body(response), self.data)

    def test_partial_range_returns_206_with_exactly_those_bytes(self):
        response = self.serve('audio/song.mp3', HTTP_RANGE='bytes=1000-1999')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response['Content-Range'], 'bytes 1000-1999/10240')
        self.assertEqual(response['Content-Length'], '1000')
        self.assertEqual(self.body(response), self.data[1000:2000])

    def test_open_ended_and_suffix_ranges(self):
        self.assertEqual(self.body(self.serve('audio/song.mp3', HTTP_RANGE='bytes=10000-')), self.data[10000:])
        self.assertEqual(self.body(self.serve('audio/song.mp3', HTTP_RANGE='bytes=-100')), self.data[-100:])

    def test_range_past_the_end_is_416(self):
        response = self.serve('audio/song.mp3', HTTP_RANGE='bytes=20000-')
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response['Content-Range'], 'bytes */10240')

    def test_missing_files_and_path_tricks_are_404(self):
        from django.http import Http404
        for path in ('audio/nope.mp3', '../manage.py', 'audio/../../manage.py'):
            with self.assertRaises(Http404, msg=path):
                self.serve(path)


class BackHomeButtonTests(BaseTestCase):
    """Back / Home buttons in the header (the Back trail itself lives in static/js/nav.js)."""

    def test_buttons_appear_for_logged_in_users_on_every_page(self):
        self.login()
        for url in (reverse('home'), reverse('artist_list'), self.album.get_absolute_url(), reverse('playlist_list'),
                    reverse('artist_create'), reverse('search') + '?q=disc'):
            html = self.client.get(url).content.decode()
            self.assertIn('id="nav-back"', html, url)
            self.assertIn('id="nav-home"', html, url)
            self.assertIn(f'id="nav-home" href="{reverse("home")}"', html, url)

    def test_logged_out_pages_have_no_such_buttons(self):
        html = self.client.get(reverse('login')).content.decode()
        self.assertNotIn('nav-back', html)

    def test_track_popup_asks_nav_js_to_keep_the_page_off_the_back_trail(self):
        js = (settings.BASE_DIR / 'static' / 'js' / 'track_dialog.js').read_text(encoding='utf-8')
        self.assertIn('saved: true', js)


class UninterruptedPlaybackTests(BaseTestCase):
    """nav.js swaps only <header> and <main>; the player must therefore live outside <main> on every page."""

    def pages(self):
        return [reverse('home'), reverse('artist_list'), reverse('album_list'), self.artist.get_absolute_url(),
                self.album.get_absolute_url(), reverse('playlist_list'), self.playlist.get_absolute_url(),
                reverse('liked_songs'), reverse('search') + '?q=disc', reverse('profile'),
                reverse('artist_create'), reverse('album_create')]

    def test_player_bar_and_audio_sit_outside_main_on_every_page(self):
        self.login()
        for url in self.pages():
            html = self.client.get(url).content.decode()
            self.assertEqual(html.count('<main'), 1, url)
            self.assertEqual(html.count('<header class="topbar"'), 1, url)
            end_of_main = html.index('</main>')
            for marker in ('id="now-playing"', 'id="np-audio"'):
                self.assertGreater(html.index(marker), end_of_main, f'{marker} must not be inside <main> ({url})')
            self.assertLess(html.index('<header class="topbar"'), html.index('<main'), url)

    def test_nav_script_loads_last_and_only_when_logged_in(self):
        self.login()
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('js/nav.js', html)
        self.assertGreater(html.index('js/nav.js'), html.index('js/player.js'))     # after the player and popup scripts
        self.assertGreater(html.index('js/nav.js'), html.index('js/track_dialog.js'))
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('login')), 'js/nav.js')

    def test_plain_page_requests_are_not_confused_with_the_popup_requests(self):
        # nav.js asks for pages with X-Soft-Nav (not X-Requested-With), so it always gets the full page back
        self.login()
        create = reverse('track_create', args=[self.album.pk])
        response = self.client.get(create, HTTP_X_SOFT_NAV='1')
        self.assertTemplateUsed(response, 'music/form.html')
        self.assertContains(response, '<main')
        self.assertContains(response, 'id="now-playing"')

    def test_pages_that_run_their_own_script_keep_it_inside_main(self):
        # nav.js re-runs scripts found in <main> after a swap, so page scripts must live there
        self.login()
        for url in (reverse('home'), reverse('artist_create'), reverse('album_create')):
            html = self.client.get(url).content.decode()
            main = html[html.index('<main'):html.index('</main>')]
            self.assertIn('<script>', main, url)


class AssetCacheBustingTests(BaseTestCase):
    """CSS/JS links carry the file's modified time, so a browser never keeps running a stale script."""

    def test_asset_tag_adds_the_files_modified_time(self):
        import os
        from django.contrib.staticfiles import finders
        from django.template import Context, Template
        url = Template("{% load assets %}{% asset 'js/player.js' %}").render(Context())
        path, _, version = url.partition('?v=')
        self.assertEqual(path, '/static/js/player.js')
        self.assertEqual(version, str(int(os.path.getmtime(finders.find('js/player.js')))))

    def test_asset_tag_for_a_missing_file_gives_the_plain_url_instead_of_crashing(self):
        from django.template import Context, Template
        self.assertEqual(Template("{% load assets %}{% asset 'js/nope.js' %}").render(Context()), '/static/js/nope.js')

    def test_every_page_links_versioned_assets(self):
        self.login()
        html = self.client.get(self.album.get_absolute_url()).content.decode()
        for name in ('css/style.css', 'js/player.js', 'js/confirm.js', 'js/track_dialog.js'):
            self.assertRegex(html, rf'/static/{name}\?v=\d+')
        self.client.logout()
        self.assertRegex(self.client.get(reverse('login')).content.decode(), r'/static/css/style\.css\?v=\d+')


class TrackRowTests(BaseTestCase):
    """Track rows: a play button that hands the track to the Now playing bar, plus the time."""

    def setUp(self):
        self.login()

    def test_track_without_audio_has_a_disabled_play_button_and_nothing_to_play(self):
        response = self.client.get(self.album.get_absolute_url())
        self.assertContains(response, 'class="trk"')
        self.assertContains(response, 'disabled aria-label="No audio file for One More Time"')
        self.assertNotContains(response, 'data-src=')       # no source on the row, so the bar can't try to play it
        self.assertContains(response, '5:20')               # duration is still shown

    def test_track_with_audio_hands_its_source_to_the_player(self):
        self.track.audio_file = 'audio/one_more_time.mp3'
        self.track.save()
        response = self.client.get(self.album.get_absolute_url())
        self.assertContains(response, 'data-src="/media/audio/one_more_time.mp3"')
        self.assertContains(response, 'data-seconds="320"')
        self.assertContains(response, 'aria-label="Play One More Time"')
        self.assertNotContains(response, '<audio controls')   # no browser-default player
        self.assertNotContains(response, 'trk-bar')           # the seek bar now lives in the Now playing bar

    def test_row_carries_what_the_now_playing_bar_shows(self):
        self.track.audio_file = 'audio/one_more_time.mp3'
        self.track.save()
        self.album.cover = 'covers/discovery.jpg'
        self.album.save()
        html = self.client.get(self.album.get_absolute_url()).content.decode()
        for attribute in (f'data-id="{self.track.pk}"', 'data-title="One More Time"', 'data-artist="Daft Punk"',
                          f'data-artist-url="{self.artist.get_absolute_url()}"', 'data-album="Discovery"',
                          f'data-album-url="{self.album.get_absolute_url()}"', 'data-cover="/media/covers/discovery.jpg"'):
            self.assertIn(attribute, html)

    def test_now_playing_bar_is_on_logged_in_pages_only(self):
        for url in (reverse('home'), self.album.get_absolute_url(), reverse('album_list')):
            html = self.client.get(url).content.decode()
            for needle in ('id="now-playing"', 'id="np-audio"', 'id="np-play"', 'id="np-prev"', 'id="np-next"',
                           'id="np-shuffle"', 'id="np-repeat"', 'id="np-bar"', 'id="np-vol"'):
                self.assertIn(needle, html, url)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('login')), 'now-playing')

    def test_playable_url_prefers_the_uploaded_file_then_the_preview_link(self):
        self.assertEqual(self.track.playable_url, '')
        self.assertFalse(self.track.is_preview_only)

        self.track.preview_url = 'https://audio-ssl.itunes.apple.com/preview/one-more-time.m4a'
        self.assertEqual(self.track.playable_url, 'https://audio-ssl.itunes.apple.com/preview/one-more-time.m4a')
        self.assertTrue(self.track.is_preview_only)

        self.track.audio_file = 'audio/one_more_time.mp3'      # an upload always wins
        self.assertEqual(self.track.playable_url, '/media/audio/one_more_time.mp3')
        self.assertFalse(self.track.is_preview_only)

    def test_preview_only_track_is_playable_and_labelled(self):
        self.track.preview_url = 'https://audio-ssl.itunes.apple.com/preview/one-more-time.m4a'
        self.track.save()
        response = self.client.get(self.album.get_absolute_url())
        self.assertContains(response, 'data-src="https://audio-ssl.itunes.apple.com/preview/one-more-time.m4a"')
        self.assertContains(response, 'aria-label="Play One More Time"')
        self.assertContains(response, '30s preview')
        self.assertNotContains(response, 'disabled aria-label="No audio file')

    def test_uploaded_file_hides_the_preview_label(self):
        self.track.audio_file = 'audio/one_more_time.mp3'
        self.track.preview_url = 'https://audio-ssl.itunes.apple.com/preview/one-more-time.m4a'
        self.track.save()
        response = self.client.get(self.album.get_absolute_url())
        self.assertContains(response, 'data-src="/media/audio/one_more_time.mp3"')
        self.assertNotContains(response, '30s preview')

    def test_preview_link_cannot_be_set_from_the_public_track_form(self):
        response = self.client.post(reverse('track_create', args=[self.album.pk]), {
            'title': 'Sneaky', 'track_number': 2, 'duration': '3:00',
            'preview_url': 'https://evil.example/x.mp3',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Track.objects.get(title='Sneaky').preview_url, '')

    def test_row_actions_follow_the_page(self):
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)
        album_page = self.client.get(self.album.get_absolute_url())
        self.assertContains(album_page, reverse('track_update', args=[self.track.pk]))      # Edit
        self.assertContains(album_page, reverse('track_delete', args=[self.track.pk]))      # Delete
        self.assertContains(album_page, '+ Playlist')                                       # add-to-playlist dropdown
        playlist_page = self.client.get(self.playlist.get_absolute_url())
        self.assertContains(playlist_page, reverse('playlist_remove_track', args=[self.playlist.pk, self.track.pk]))
        self.assertNotContains(playlist_page, reverse('track_delete', args=[self.track.pk]))
        self.assertContains(playlist_page, 'Discovery')   # album link shows on playlist pages

    def test_player_script_is_loaded(self):
        self.assertContains(self.client.get(reverse('home')), 'js/player.js')


class HomeTrackPlayerTests(BaseTestCase):
    """The home page Tracks panel uses the same playable rows as the album page."""

    def setUp(self):
        self.login()
        self.track.audio_file = 'audio/one_more_time.mp3'
        self.track.save()

    def test_album_tracks_fragment_has_playable_compact_rows(self):
        data = self.client.get(reverse('home_album_tracks', args=[self.album.pk])).json()
        html = data['tracks']
        self.assertIn('class="trk trk-compact"', html)
        self.assertIn('data-src="/media/audio/one_more_time.mp3"', html)
        self.assertIn('aria-label="Play One More Time"', html)
        self.assertIn('data-artist="Daft Punk"', html)             # the bar can show who it is
        self.assertNotIn('+ Playlist', html)                       # compact: no dropdown
        self.assertNotIn(reverse('track_update', args=[self.track.pk]), html)   # and no edit/delete links

    def test_home_page_renders_the_same_rows_for_the_remembered_album(self):
        self.client.get(reverse('home_album_tracks', args=[self.album.pk]))
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'class="trk trk-compact"')
        self.assertContains(response, 'data-src="/media/audio/one_more_time.mp3"')

    def test_heart_in_the_panel_shows_the_current_like_state(self):
        Like.objects.create(user=self.alice, track=self.track)
        html = self.client.get(reverse('home_album_tracks', args=[self.album.pk])).json()['tracks']
        self.assertIn('class="like liked"', html)

    def test_heart_form_returns_to_the_home_page_not_the_json_url(self):
        html = self.client.get(reverse('home_album_tracks', args=[self.album.pk])).json()['tracks']
        self.assertIn(f'name="next" value="{reverse("home")}"', html)
        self.assertIn('data-like', html)

    def test_like_via_ajax_returns_json_and_toggles(self):
        url = reverse('track_like', args=[self.track.pk])
        ajax = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        self.assertEqual(self.client.post(url, **ajax).json(), {'liked': True})
        self.assertTrue(Like.objects.filter(user=self.alice, track=self.track).exists())
        self.assertEqual(self.client.post(url, **ajax).json(), {'liked': False})
        self.assertFalse(Like.objects.exists())

    def test_like_without_ajax_still_redirects(self):
        response = self.client.post(reverse('track_like', args=[self.track.pk]), {'next': '/liked/'})
        self.assertRedirects(response, '/liked/', fetch_redirect_response=False)


class DeletePopupTests(BaseTestCase):
    """Delete links open a popup (confirm.js); the confirmation pages still work as the fallback."""

    def setUp(self):
        self.login()
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)

    def test_popup_markup_is_on_every_logged_in_page(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, '<dialog id="confirm-dialog"')
        self.assertContains(response, 'js/confirm.js')
        self.assertContains(response, 'Yes, delete')

    def test_popup_is_not_rendered_for_logged_out_pages(self):
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('login')), 'confirm-dialog')

    def test_every_delete_link_is_wired_to_the_popup(self):
        pages = {
            self.artist.get_absolute_url(): reverse('artist_delete', args=[self.artist.pk]),
            self.album.get_absolute_url(): reverse('album_delete', args=[self.album.pk]),
            self.playlist.get_absolute_url(): reverse('playlist_delete', args=[self.playlist.pk]),
        }
        for page, delete_url in pages.items():
            html = self.client.get(page).content.decode()
            self.assertIn(f'href="{delete_url}" data-confirm-delete', html, page)
        # track delete link sits in the album's tracklist
        html = self.client.get(self.album.get_absolute_url()).content.decode()
        self.assertIn(f'href="{reverse("track_delete", args=[self.track.pk])}" data-confirm-delete data-name="One More Time"', html)

    def test_names_and_warnings_come_through_escaped(self):
        self.artist.name = 'Tom "Tricky" <b>Smith</b>'
        self.artist.save()
        html = self.client.get(self.artist.get_absolute_url()).content.decode()
        self.assertIn('data-name="Tom &quot;Tricky&quot; &lt;b&gt;Smith&lt;/b&gt;"', html)
        self.assertIn("albums and tracks will be deleted too", html)

    def test_popup_posts_to_the_same_delete_url_and_deletes(self):
        # what "Yes, delete" does: a POST (with the CSRF token) to the link's href
        response = self.client.post(reverse('track_delete', args=[self.track.pk]))
        self.assertRedirects(response, self.album.get_absolute_url())
        self.assertFalse(Track.objects.filter(pk=self.track.pk).exists())

    def test_confirmation_page_still_works_without_javascript(self):
        response = self.client.get(reverse('album_delete', args=[self.album.pk]))
        self.assertContains(response, 'Yes, delete')
        self.assertTrue(Album.objects.filter(pk=self.album.pk).exists())   # a GET deletes nothing


class TrackPopupTests(BaseTestCase):
    """Add / Edit track open in a popup (track_dialog.js): the same views serve the fields, JSON and errors."""

    AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

    def setUp(self):
        self.login()
        self.create_url = reverse('track_create', args=[self.album.pk])
        self.edit_url = reverse('track_update', args=[self.track.pk])

    def test_links_and_popup_shell_are_on_the_page(self):
        album_page = self.client.get(self.album.get_absolute_url())
        self.assertContains(album_page, '<dialog id="track-dialog"')
        self.assertContains(album_page, 'js/track_dialog.js')
        self.assertContains(album_page, f'href="{self.create_url}" data-track-form')   # Add track
        self.assertContains(album_page, f'href="{self.edit_url}" data-track-form')     # Edit
        home = self.client.get(reverse('home'))
        self.assertContains(home, '<dialog id="track-dialog"')

    def test_home_panel_add_track_link_opens_the_popup_too(self):
        self.client.get(reverse('home_album_tracks', args=[self.album.pk]))
        html = self.client.get(reverse('home_album_tracks', args=[self.album.pk])).json()['tracks']
        self.assertIn(f'href="{self.create_url}" data-track-form', html)

    def test_get_with_ajax_header_returns_only_the_fields(self):
        response = self.client.get(self.create_url, **self.AJAX)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'music/_track_form_dialog.html')
        self.assertTemplateNotUsed(response, 'base.html')
        html = response.content.decode()
        self.assertNotIn('<html', html)
        for needle in ('Add track', 'on Discovery', 'name="title"', 'name="track_number"', 'name="duration"',
                       'name="audio_file"', 'Format m:ss', 'data-dialog-close'):
            self.assertIn(needle, html)
        self.assertNotIn('csrfmiddlewaretoken', html)   # the token lives on the popup's <form> in base.html

    def test_track_number_suggests_the_next_free_number(self):
        # the album already has track 1; an album with none starts at 1
        html = self.client.get(self.create_url, **self.AJAX).content.decode()
        self.assertIn('name="track_number" value="2"', html)
        empty = Album.objects.create(title='Homework', artist=self.artist, release_date=datetime.date(1997, 1, 20))
        html = self.client.get(reverse('track_create', args=[empty.pk]), **self.AJAX).content.decode()
        self.assertIn('name="track_number" value="1"', html)

    def test_get_without_the_header_still_serves_the_full_page(self):
        response = self.client.get(self.create_url)
        self.assertTemplateUsed(response, 'music/form.html')
        self.assertContains(response, '<html')

    def test_valid_post_returns_json_and_creates_the_track(self):
        response = self.client.post(self.create_url, {'title': 'Aerodynamic', 'track_number': 2, 'duration': '3:27'}, **self.AJAX)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'redirect': self.album.get_absolute_url()})
        track = Track.objects.get(title='Aerodynamic')
        self.assertEqual((track.album, track.track_number, track.duration_display), (self.album, 2, '3:27'))
        self.assertEqual(self.client.get(reverse('home')).context['selected_album'], self.album)   # remembered for the home panel

    def test_invalid_post_returns_400_with_the_errors_and_keeps_what_was_typed(self):
        response = self.client.post(self.create_url, {'title': '', 'track_number': 2, 'duration': 'not a time'}, **self.AJAX)
        self.assertEqual(response.status_code, 400)
        html = response.content.decode()
        self.assertIn('This field is required', html)
        self.assertIn('value="2"', html)
        self.assertEqual(Track.objects.filter(album=self.album).count(), 1)   # nothing was saved

    def test_audio_upload_works_through_the_popup(self):
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            response = self.client.post(self.create_url, {
                'title': 'With audio', 'track_number': 3, 'duration': '0:04',
                'audio_file': SimpleUploadedFile('tone.wav', b'RIFF....WAVEfmt ', content_type='audio/wav'),
            }, **self.AJAX)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(Track.objects.get(title='With audio').audio_file.name.startswith('audio/tone'))

    def test_edit_popup_is_prefilled_and_saves(self):
        response = self.client.get(self.edit_url, **self.AJAX)
        html = response.content.decode()
        self.assertIn('Edit track', html)
        self.assertIn('value="One More Time"', html)
        self.assertIn('name="duration" value="5:20"', html)      # shown the way the hint asks for it
        saved = self.client.post(self.edit_url, {'title': 'One More Time (Remix)', 'track_number': 1, 'duration': '5:20'}, **self.AJAX)
        self.assertEqual(saved.json(), {'redirect': self.album.get_absolute_url()})
        self.track.refresh_from_db()
        self.assertEqual(self.track.title, 'One More Time (Remix)')

    def test_login_is_still_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.create_url, **self.AJAX).status_code, 302)
        self.assertEqual(self.client.post(self.create_url, {'title': 'x', 'track_number': 1, 'duration': '1:00'}, **self.AJAX).status_code, 302)
        self.assertFalse(Track.objects.filter(title='x').exists())


class PlaylistTests(BaseTestCase):
    def test_create_sets_owner(self):
        self.login()
        self.client.post(reverse('playlist_create'), {'name': 'Road trip', 'description': 'vroom'})
        self.assertEqual(Playlist.objects.get(name='Road trip').owner, self.alice)

    def test_list_shows_only_own_playlists(self):
        Playlist.objects.create(owner=self.bob, name='Bobs secret')
        self.login()
        response = self.client.get(reverse('playlist_list'))
        self.assertContains(response, 'Favourites')
        self.assertNotContains(response, 'Bobs secret')

    def test_only_owner_can_view_edit_delete(self):
        self.login('bob')
        for name in ('playlist_detail', 'playlist_update', 'playlist_delete'):
            url = reverse(name, args=[self.playlist.pk])
            self.assertEqual(self.client.get(url).status_code, 404, name)
        self.client.post(reverse('playlist_update', args=[self.playlist.pk]), {'name': 'hacked'})
        self.client.post(reverse('playlist_delete', args=[self.playlist.pk]))
        self.playlist.refresh_from_db()
        self.assertEqual(self.playlist.name, 'Favourites')

    def test_owner_can_update_and_delete(self):
        self.login()
        self.client.post(reverse('playlist_update', args=[self.playlist.pk]), {'name': 'Renamed'})
        self.playlist.refresh_from_db()
        self.assertEqual(self.playlist.name, 'Renamed')
        self.client.post(reverse('playlist_delete', args=[self.playlist.pk]))
        self.assertFalse(Playlist.objects.filter(pk=self.playlist.pk).exists())

    def test_add_and_remove_track(self):
        self.login()
        add_url = reverse('playlist_add_track', args=[self.track.pk])
        self.client.post(add_url, {'playlist': self.playlist.pk})
        self.client.post(add_url, {'playlist': self.playlist.pk})  # duplicate is ignored
        self.assertEqual(PlaylistTrack.objects.filter(playlist=self.playlist).count(), 1)
        self.assertContains(self.client.get(self.playlist.get_absolute_url()), 'One More Time')

        self.client.post(reverse('playlist_remove_track', args=[self.playlist.pk, self.track.pk]))
        self.assertEqual(PlaylistTrack.objects.count(), 0)

    def test_cannot_modify_someone_elses_playlist_tracks(self):
        self.login('bob')
        response = self.client.post(reverse('playlist_add_track', args=[self.track.pk]), {'playlist': self.playlist.pk})
        self.assertEqual(response.status_code, 404)
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)
        response = self.client.post(reverse('playlist_remove_track', args=[self.playlist.pk, self.track.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(PlaylistTrack.objects.count(), 1)

    def test_add_to_playlist_requires_post(self):
        self.login()
        response = self.client.get(reverse('playlist_add_track', args=[self.track.pk]))
        self.assertEqual(response.status_code, 405)


class HomePlaylistTests(BaseTestCase):
    """The home Playlists panel: library-style rows; one click shows the playlist's tracks, double-click opens it."""

    def setUp(self):
        self.login()
        Album.objects.filter(pk=self.album.pk).update(cover='covers/discovery.jpg', accent_color='#801521')
        Artist.objects.filter(pk=self.artist.pk).update(accent_color='#114a69')
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)

    def test_panel_lists_playlists_like_a_library(self):
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('class="lib-row"', html)
        self.assertIn('Playlist &middot; 1 song<', html)                   # "1 song", not "1 songs"
        self.assertIn('covers/discovery.jpg', html)                        # cover of the first track's album
        self.assertIn(f'data-playlist-url="{reverse("home_playlist_tracks", args=[0])}"', html)

    def test_clicking_a_playlist_returns_its_tracks_and_tint(self):
        data = self.client.get(reverse('home_playlist_tracks', args=[self.playlist.pk])).json()
        self.assertIn('One More Time', data['tracks'])
        self.assertNotIn('+ Add track', data['tracks'])                    # that link belongs to an album
        self.assertIn('--tracks-panel:#', data['theme'])
        self.assertNotIn('--album-panel', data['theme'])                   # the Albums container is left alone

    def test_playlist_selection_is_remembered_and_replaces_the_album(self):
        self.client.get(reverse('home_album_tracks', args=[self.album.pk]))
        self.client.get(reverse('home_playlist_tracks', args=[self.playlist.pk]))
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'lib-row is-selected')
        self.assertEqual(response.context['selected_playlist'], self.playlist)
        self.assertIsNone(response.context['selected_album'])
        self.assertContains(response, 'One More Time')
        self.client.get(reverse('home_album_tracks', args=[self.album.pk]))   # picking an album takes over again
        response = self.client.get(reverse('home'))
        self.assertIsNone(response.context['selected_playlist'])
        self.assertEqual(response.context['selected_album'], self.album)

    def test_empty_playlist_shows_a_hint(self):
        empty = Playlist.objects.create(owner=self.alice, name='Empty one')
        data = self.client.get(reverse('home_playlist_tracks', args=[empty.pk])).json()
        self.assertIn('This playlist is empty', data['tracks'])

    def test_cannot_open_someone_elses_playlist(self):
        secret = Playlist.objects.create(owner=self.bob, name='Bobs secret')
        self.assertEqual(self.client.get(reverse('home_playlist_tracks', args=[secret.pk])).status_code, 404)

    def test_a_deleted_playlist_is_forgotten(self):
        self.client.get(reverse('home_playlist_tracks', args=[self.playlist.pk]))
        self.playlist.delete()
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)

    def test_creating_a_playlist_selects_it_on_the_home_page(self):
        self.client.post(reverse('playlist_create'), {'name': 'Road trip', 'description': ''})
        self.assertEqual(self.client.get(reverse('home')).context['selected_playlist'].name, 'Road trip')


class PlaylistPageTests(BaseTestCase):
    """Playlist form / list / detail use the same card look as the artist and album pages."""

    def setUp(self):
        self.login()
        Album.objects.filter(pk=self.album.pk).update(cover='covers/discovery.jpg', accent_color='#801521')

    def test_form_is_a_centered_card_without_a_preview(self):
        for url in (reverse('playlist_create'), reverse('playlist_update', args=[self.playlist.pk])):
            html = self.client.get(url).content.decode()
            self.assertIn('class="editor-card editor-form"', html)
            self.assertIn('page-center', html)
            self.assertNotIn('preview', html.lower())

    def test_playlist_without_tracks_has_no_cover_or_colour(self):
        self.assertEqual(self.playlist.cover_url, '')
        self.assertEqual(self.playlist.theme_style, '')

    def test_cover_and_colour_come_from_the_first_track(self):
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)
        self.assertTrue(self.playlist.cover_url.endswith('covers/discovery.jpg'))
        self.assertEqual(self.playlist.theme_color, '#801521')

    def test_list_and_detail_use_the_card_layout(self):
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)
        listing = self.client.get(reverse('playlist_list'))
        self.assertContains(listing, 'list-card')
        self.assertContains(listing, '1 track')
        detail = self.client.get(self.playlist.get_absolute_url())
        self.assertContains(detail, 'list-card is-detail')
        self.assertContains(detail, '--accent:#801521')
        self.assertContains(detail, 'One More Time')

    def test_playlist_page_has_no_add_to_playlist_menu_but_album_page_does(self):
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)
        detail = self.client.get(self.playlist.get_absolute_url())
        self.assertNotContains(detail, '+ Playlist')                       # its songs are already in a playlist
        self.assertContains(detail, 'Remove')                              # but they can be taken out
        self.assertContains(self.client.get(self.album.get_absolute_url()), '+ Playlist')

class LikeTests(BaseTestCase):
    def test_like_toggle_and_liked_page(self):
        self.login()
        url = reverse('track_like', args=[self.track.pk])
        self.client.post(url)
        self.assertTrue(Like.objects.filter(user=self.alice, track=self.track).exists())
        self.assertContains(self.client.get(reverse('liked_songs')), 'One More Time')

        self.client.post(url)
        self.assertFalse(Like.objects.exists())
        self.assertNotContains(self.client.get(reverse('liked_songs')), 'One More Time')

    def test_likes_are_per_user(self):
        Like.objects.create(user=self.bob, track=self.track)
        self.login()
        self.assertNotContains(self.client.get(reverse('liked_songs')), 'One More Time')

    def test_like_redirects_back_but_not_off_site(self):
        self.login()
        url = reverse('track_like', args=[self.track.pk])
        response = self.client.post(url, {'next': '/liked/'})
        self.assertRedirects(response, '/liked/', fetch_redirect_response=False)
        response = self.client.post(url, {'next': 'https://evil.example/'})
        self.assertRedirects(response, self.album.get_absolute_url())

    def test_like_requires_post(self):
        self.login()
        self.assertEqual(self.client.get(reverse('track_like', args=[self.track.pk])).status_code, 405)


class SearchTests(BaseTestCase):
    def test_search_finds_tracks_artists_albums(self):
        self.login()
        response = self.client.get(reverse('search'), {'q': 'disc'})
        self.assertContains(response, 'Discovery')
        response = self.client.get(reverse('search'), {'q': 'daft'})
        self.assertContains(response, 'Daft Punk')
        response = self.client.get(reverse('search'), {'q': 'one more'})
        self.assertContains(response, 'One More Time')

    def test_search_page_uses_the_gradient_box(self):
        self.login()
        for params in ({'q': 'disc'}, {'q': 'zzzz'}, {}):
            response = self.client.get(reverse('search'), params)
            self.assertContains(response, 'class="list-card is-detail"')
            self.assertContains(response, 'class="detail-head"')
        # results scroll inside the box; with nothing to show there is no scroll area
        self.assertContains(self.client.get(reverse('search'), {'q': 'disc'}), 'class="detail-scroll"')
        self.assertNotContains(self.client.get(reverse('search'), {'q': 'zzzz'}), 'class="detail-scroll"')

    def test_search_no_results_and_empty_query(self):
        self.login()
        self.assertContains(self.client.get(reverse('search'), {'q': 'zzzz'}), 'No results')
        self.assertEqual(self.client.get(reverse('search')).status_code, 200)


class CsrfTests(BaseTestCase):
    def test_forms_reject_missing_csrf_token(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.login(username='alice', password='pw-alice-123')
        response = client.post(reverse('playlist_create'), {'name': 'x'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Playlist.objects.filter(name='x').exists())

    def test_forms_render_csrf_token(self):
        self.login()
        for url in (reverse('artist_create'), reverse('playlist_create'),
                    reverse('artist_delete', args=[self.artist.pk]), self.album.get_absolute_url()):
            self.assertContains(self.client.get(url), 'csrfmiddlewaretoken', msg_prefix=url)
