import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile

from .models import Album, Artist, Like, Play, Playlist, PlaylistPartner, PlaylistTrack, Track
from .stats import month_start, recently_played, top_artists, top_songs
from .views import LIKED_COLOR

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
        self.assertContains(response, 'Shared by others')  # everyone's playlists are visible ...
        self.assertContains(response, 'Bobs secret')
        self.assertContains(response, 'Daft Punk')        # artist card
        self.assertContains(response, reverse('artist_create'))  # "add artist" tile

    def test_nothing_selected_shows_hints_instead_of_albums_and_tracks(self):
        self.login()
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Select an artist or add one first')
        self.assertContains(response, 'Select an album or a playlist to see its tracks')
        self.assertNotContains(response, 'add album')   # no add-album tile until an artist is picked
        html = response.content.decode()
        panels = html.split('<div class="home-recent">')[0]     # the Albums panel stays empty ("Recently added" below lists albums on purpose)
        self.assertNotIn('Discovery', panels)                   # albums are hidden until an artist is picked
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


class SearchSuggestTests(BaseTestCase):
    """The search box suggests only artists, albums and songs that already exist."""

    def setUp(self):
        self.url = reverse('search_suggest')
        Artist.objects.create(name='Discovery Channel Band')
        Album.objects.filter(pk=self.album.pk).update(cover='covers/discovery.jpg')

    def suggest(self, q):
        self.login()
        return self.client.get(self.url, {'q': q}).json()['results']

    def test_requires_login(self):
        response = self.client.get(self.url, {'q': 'disc'})
        self.assertEqual(response.status_code, 302)

    def test_finds_artists_albums_and_songs_that_exist(self):
        results = self.suggest('disc')
        kinds = {(r['type'], r['title']) for r in results}
        self.assertIn(('album', 'Discovery'), kinds)
        self.assertIn(('artist', 'Discovery Channel Band'), kinds)
        song = {r['title'] for r in self.suggest('one more')}
        self.assertEqual(song, {'One More Time'})

    def test_each_suggestion_links_to_its_page(self):
        by_type = {r['type']: r for r in self.suggest('discovery')}
        self.assertEqual(by_type['album']['url'], self.album.get_absolute_url())
        self.assertTrue(by_type['album']['image'].endswith('covers/discovery.jpg'))
        track = {r['type']: r for r in self.suggest('one more')}['track']
        self.assertEqual(track['url'], self.album.get_absolute_url())      # a song opens its album
        self.assertIn('Daft Punk', track['sub'])

    def test_nothing_added_means_nothing_suggested(self):
        self.assertEqual(self.suggest('zzzz-not-here'), [])
        self.assertEqual(self.suggest('   '), [])
        self.assertEqual(self.suggest(''), [])

    def test_matches_that_start_with_the_text_come_first(self):
        Album.objects.create(title='The Discoverers', artist=self.artist, release_date=datetime.date(2005, 1, 1))
        albums = [r['title'] for r in self.suggest('disco') if r['type'] == 'album']
        self.assertEqual(albums, ['Discovery', 'The Discoverers'])

    def test_result_count_is_limited(self):
        for n in range(10):
            Artist.objects.create(name=f'Disco Artist {n}')
        artists = [r for r in self.suggest('disco') if r['type'] == 'artist']
        self.assertEqual(len(artists), 3)

    def test_search_box_is_wired_up_on_pages(self):
        self.login()
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn(f'data-suggest-url="{self.url}"', html)
        self.assertIn('js/suggest.js', html)


class PlayRecordingTests(BaseTestCase):
    """The player reports a song once it has really been listened to; those plays feed the profile."""

    def setUp(self):
        self.url = reverse('record_play')

    def test_requires_login_and_post(self):
        self.assertEqual(self.client.post(self.url, {'track': self.track.pk}).status_code, 302)
        self.login()
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(Play.objects.count(), 0)

    def test_a_play_is_recorded_for_the_signed_in_user(self):
        self.login()
        response = self.client.post(self.url, {'track': self.track.pk})
        self.assertEqual(response.json(), {'recorded': True})
        play = Play.objects.get()
        self.assertEqual((play.user, play.track), (self.alice, self.track))

    def test_the_same_song_twice_in_a_few_seconds_counts_once(self):
        self.login()
        self.client.post(self.url, {'track': self.track.pk})
        again = self.client.post(self.url, {'track': self.track.pk}).json()
        self.assertEqual(again, {'recorded': False})
        self.assertEqual(Play.objects.count(), 1)

    def test_a_later_listen_counts_again(self):
        self.login()
        Play.objects.create(user=self.alice, track=self.track, played_at=timezone.now() - datetime.timedelta(minutes=5))
        self.assertTrue(self.client.post(self.url, {'track': self.track.pk}).json()['recorded'])
        self.assertEqual(Play.objects.count(), 2)

    def test_unknown_or_bad_track_ids_are_not_found(self):
        self.login()
        for bad in ('99999', 'abc', ''):
            self.assertEqual(self.client.post(self.url, {'track': bad}).status_code, 404, bad)
        self.assertEqual(Play.objects.count(), 0)

    def test_player_script_reports_plays(self):
        js = (settings.BASE_DIR / 'static' / 'js' / 'player.js').read_text(encoding='utf-8')
        self.assertIn('/plays/record/', js)
        self.assertIn('countListening', js)


class RecentRowsTests(BaseTestCase):
    """The home page's "Recently played" and "Recently added" rows (under the four panels)."""

    def setUp(self):
        self.second = Track.objects.create(album=self.album, title='Aerodynamic', track_number=2, duration=datetime.timedelta(minutes=3))

    def play(self, track, user=None, minutes_ago=0):
        Play.objects.create(user=user or self.alice, track=track, played_at=timezone.now() - datetime.timedelta(minutes=minutes_ago))

    def test_recently_played_is_newest_first_and_lists_each_song_once(self):
        self.play(self.track, minutes_ago=30)
        self.play(self.second, minutes_ago=20)
        self.play(self.track, minutes_ago=5)                 # listened to again: moves to the front, no duplicate
        self.assertEqual([t.title for t in recently_played(self.alice)], ['One More Time', 'Aerodynamic'])

    def test_recently_played_is_per_person_and_limited(self):
        self.play(self.track, user=self.bob)
        self.assertEqual(recently_played(self.alice), [])
        for n in range(15):
            track = Track.objects.create(album=self.album, title=f'Extra {n}', track_number=10 + n, duration=datetime.timedelta(minutes=3))
            self.play(track, minutes_ago=n)
        self.assertEqual(len(recently_played(self.alice)), 12)

    def test_home_shows_both_rows(self):
        self.play(self.track)
        self.login()
        response = self.client.get(reverse('home'))
        html = response.content.decode()
        self.assertIn('Recently played', html)
        self.assertIn('Recently added', html)
        self.assertEqual([t.title for t in response.context['recent_tracks']], ['One More Time'])
        self.assertEqual([a.title for a in response.context['recent_albums']], ['Discovery'])

    def test_empty_states_and_no_play_button_without_audio(self):
        self.login()
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('Nothing played yet', html)
        self.play(self.track)                                # no audio file: the tile shows, without a play button
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('class="rc"', html)
        self.assertNotIn('rc-play', html.split('id="recent-played-row"')[1].split('Recently added')[0])

    def test_recently_added_puts_the_newest_album_first(self):
        newer = Album.objects.create(title='Homework', artist=self.artist, release_date=datetime.date(1997, 1, 20))   # older release, added later
        self.login()
        albums = list(self.client.get(reverse('home')).context['recent_albums'])
        self.assertEqual(albums[0], newer)


class PlayAllButtonTests(BaseTestCase):
    """The big Play button on album, playlist and Liked Songs pages (static/js/player.js starts the whole list)."""

    def setUp(self):
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)
        Like.objects.create(user=self.alice, track=self.track)
        self.empty_playlist = Playlist.objects.create(owner=self.alice, name='Empty one')
        self.login()

    def test_album_playlist_and_liked_pages_have_it(self):
        for url in (self.album.get_absolute_url(), self.playlist.get_absolute_url(), reverse('liked_songs')):
            self.assertContains(self.client.get(url), 'data-play-all', msg_prefix=url)

    def test_it_sits_in_the_actions_row_for_a_playlist_you_cannot_edit(self):
        other = Playlist.objects.create(owner=self.bob, name='Bobs')
        PlaylistTrack.objects.create(playlist=other, track=self.track)
        html = self.client.get(other.get_absolute_url()).content.decode()
        self.assertIn('data-play-all', html)
        self.assertNotIn('Edit playlist', html)

    def test_no_button_when_there_is_nothing_to_play(self):
        empty_album = Album.objects.create(title='Empty LP', artist=self.artist, release_date=datetime.date(2020, 1, 1))
        for url in (empty_album.get_absolute_url(), self.empty_playlist.get_absolute_url()):
            self.assertNotContains(self.client.get(url), 'data-play-all', msg_prefix=url)
        Like.objects.all().delete()
        self.assertNotContains(self.client.get(reverse('liked_songs')), 'data-play-all')


class DeleteNoticeTests(BaseTestCase):
    """Deleting something leaves a message, which toast.js shows as a popup bubble on the next page."""

    def deleted_message(self, url):
        self.login()
        response = self.client.post(url, follow=True)
        return [str(m) for m in response.context['messages']]

    def test_each_kind_says_what_was_deleted(self):
        self.assertEqual(self.deleted_message(reverse('track_delete', args=[self.track.pk])), ['Deleted track “One More Time”.'])
        self.assertEqual(self.deleted_message(reverse('album_delete', args=[self.album.pk])), ['Deleted album “Discovery”.'])
        self.assertEqual(self.deleted_message(reverse('playlist_delete', args=[self.playlist.pk])), ['Deleted playlist “Favourites”.'])
        self.assertEqual(self.deleted_message(reverse('artist_delete', args=[self.artist.pk])), ['Deleted artist “Daft Punk”.'])

    def test_the_notice_reaches_the_page_as_a_message_list_the_toast_script_reads(self):
        self.login()
        html = self.client.post(reverse('album_delete', args=[self.album.pk]), follow=True).content.decode()
        self.assertIn('<ul class="messages">', html)
        self.assertIn('Deleted album', html)

    def test_nothing_is_announced_when_the_delete_is_refused(self):
        outsider_url = reverse('playlist_delete', args=[self.playlist.pk])
        self.login('bob')                                   # not the owner: the playlist stays, no "Deleted" message
        response = self.client.post(outsider_url)
        self.assertTrue(Playlist.objects.filter(pk=self.playlist.pk).exists())
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)], [])


class TopStatsTests(BaseTestCase):
    """Top artists / songs of the current month, per user."""

    def setUp(self):
        self.other_artist = Artist.objects.create(name='Justice')
        self.other_album = Album.objects.create(title='Cross', artist=self.other_artist, release_date=datetime.date(2007, 6, 11))
        self.t2 = Track.objects.create(album=self.other_album, title='D.A.N.C.E.', track_number=1, duration=datetime.timedelta(minutes=4))

    def play(self, track, times=1, user=None, days_ago=0):
        for _ in range(times):
            Play.objects.create(user=user or self.alice, track=track,
                                played_at=timezone.now() - datetime.timedelta(days=days_ago))

    def test_most_played_first_with_counts(self):
        self.play(self.track, 3)
        self.play(self.t2, 5)
        songs = top_songs(self.alice)
        self.assertEqual([(t.title, n) for t, n in songs], [('D.A.N.C.E.', 5), ('One More Time', 3)])
        artists = top_artists(self.alice)
        self.assertEqual([(a.name, n) for a, n in artists], [('Justice', 5), ('Daft Punk', 3)])

    def test_artist_plays_add_up_across_their_songs(self):
        second = Track.objects.create(album=self.album, title='Aerodynamic', track_number=2, duration=datetime.timedelta(minutes=3))
        self.play(self.track, 2)
        self.play(second, 2)
        self.play(self.t2, 3)
        artists = top_artists(self.alice)
        self.assertEqual([(a.name, n) for a, n in artists], [('Daft Punk', 4), ('Justice', 3)])

    def test_only_this_month_counts(self):
        self.play(self.track, 4, days_ago=45)                   # last month or earlier
        self.play(self.t2, 1)
        self.assertEqual([t.title for t, _ in top_songs(self.alice)], ['D.A.N.C.E.'])

    def test_each_person_sees_only_their_own_listening(self):
        self.play(self.track, 2, user=self.bob)
        self.assertEqual(top_songs(self.alice), [])
        self.assertEqual(top_artists(self.alice), [])

    def test_limits_are_5_artists_and_30_songs(self):
        for n in range(8):
            artist = Artist.objects.create(name=f'Band {n}')
            album = Album.objects.create(title=f'LP {n}', artist=artist, release_date=datetime.date(2020, 1, 1))
            track = Track.objects.create(album=album, title=f'Song {n}', track_number=1, duration=datetime.timedelta(minutes=3))
            self.play(track, n + 1)
        self.assertEqual(len(top_artists(self.alice)), 5)
        for n in range(35):
            track = Track.objects.create(album=self.album, title=f'Extra {n}', track_number=10 + n, duration=datetime.timedelta(minutes=3))
            self.play(track)
        self.assertEqual(len(top_songs(self.alice)), 30)

    def test_ties_go_to_the_most_recent(self):
        self.play(self.track, 2, days_ago=3)
        self.play(self.t2, 2, days_ago=0)
        self.assertEqual([t.title for t, _ in top_songs(self.alice)], ['D.A.N.C.E.', 'One More Time'])

    def test_month_starts_at_midnight_on_the_first(self):
        start = month_start(timezone.make_aware(datetime.datetime(2026, 10, 17, 15, 30)))
        self.assertEqual((start.day, start.hour, start.minute), (1, 0, 0))


class ProfilePageTests(BaseTestCase):
    """Profile: photo, name, bio, top 5 artists and top 30 songs of the month."""

    def setUp(self):
        self.login()
        self.url = reverse('profile')

    def test_shows_username_until_a_name_is_set(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('<h1>alice</h1>', html)
        self.assertIn('class="avatar"', html)
        self.assertIn('<span>A</span>', html)                        # initial in place of a photo

    def test_name_and_bio_can_be_edited(self):
        response = self.client.post(reverse('profile_edit'), {'display_name': 'Alice A.', 'bio': 'I like synths.\nA lot.'})
        self.assertRedirects(response, self.url)
        html = self.client.get(self.url).content.decode()
        self.assertIn('<h1>Alice A.</h1>', html)
        self.assertIn('I like synths.<br>A lot.', html)
        self.assertEqual(Profile.objects.get(user=self.alice).bio, 'I like synths.\nA lot.')

    def test_edit_form_is_a_card_and_prefilled(self):
        Profile.objects.update_or_create(user=self.alice, defaults={'display_name': 'Ally'})
        html = self.client.get(reverse('profile_edit')).content.decode()
        self.assertIn('editor-card editor-form', html)
        self.assertIn('value="Ally"', html)

    def test_other_users_profiles_are_separate(self):
        self.client.post(reverse('profile_edit'), {'display_name': 'Alice A.', 'bio': ''})
        self.client.logout()
        self.login('bob')
        self.assertIn('<h1>bob</h1>', self.client.get(self.url).content.decode())

    def test_bio_is_limited_to_300_characters(self):
        response = self.client.post(reverse('profile_edit'), {'display_name': '', 'bio': 'x' * 301})
        self.assertEqual(response.status_code, 200)                  # form shown again with an error
        self.assertFalse(Profile.objects.filter(user=self.alice, bio__startswith='xxx').exists())

    def test_empty_top_lists_explain_themselves(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('Top artists this month', html)
        self.assertIn('Top songs this month', html)
        self.assertIn('Listen to some songs', html)

    def test_top_lists_show_what_was_played(self):
        for _ in range(3):
            Play.objects.create(user=self.alice, track=self.track)
        response = self.client.get(self.url)
        self.assertContains(response, 'class="top-artist"')
        self.assertContains(response, 'Daft Punk')
        self.assertContains(response, '3 plays')
        self.assertContains(response, 'One More Time')               # in the playable song list
        self.assertEqual(response.context['tracks'], [self.track])

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.get(reverse('profile_edit')).status_code, 302)


def _fake_jpeg():
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (40, 40), (180, 40, 40)).save(out, 'JPEG')
    return out.getvalue()


KEYS = {'SPOTIFY_CLIENT_ID': 'test-id', 'SPOTIFY_CLIENT_SECRET': 'test-secret'}


class SpotifyClientTests(TestCase):
    """music/spotify.py with Spotify's answers faked: nothing here touches the internet."""

    def setUp(self):
        from . import spotify
        self.spotify = spotify
        spotify._token.update(value='', expires=0.0)

    def test_artist_search_picks_the_picture_closest_to_640px(self):
        payload = {'artists': {'items': [{'id': 'a1', 'name': 'Chase Atlantic', 'genres': ['pop'], 'followers': {'total': 12},
                                          'images': [{'url': 'https://i.scdn.co/small', 'width': 64},
                                                     {'url': 'https://i.scdn.co/big', 'width': 640},
                                                     {'url': 'https://i.scdn.co/huge', 'width': 1000}]}]}}
        from unittest import mock
        with override_settings(**KEYS), mock.patch.object(self.spotify, '_get', return_value=payload):
            result = self.spotify.search_artists('chase')
        self.assertEqual(result, [{'id': 'a1', 'name': 'Chase Atlantic', 'image': 'https://i.scdn.co/big',
                                   'genres': ['pop'], 'followers': 12}])

    def test_album_details_fills_in_partial_dates_and_the_song_list(self):
        payload = {'id': 'al1', 'name': 'PHASES', 'release_date': '2019-06', 'release_date_precision': 'month',
                   'artists': [{'name': 'Chase Atlantic'}, {'name': 'Guest'}], 'images': [],
                   'tracks': {'items': [{'track_number': 1, 'name': 'INTRO', 'duration_ms': 122500, 'artists': [{'name': 'Chase Atlantic'}]},
                                        {'track_number': 2, 'name': 'ANGELS', 'duration_ms': 258000, 'artists': []}]}}
        from unittest import mock
        with override_settings(**KEYS), mock.patch.object(self.spotify, '_get', return_value=payload):
            album = self.spotify.album_details('al1')
        self.assertEqual(album['date'], '2019-06-01')
        self.assertEqual(album['main_artist'], 'Chase Atlantic')
        self.assertEqual([(t['number'], t['title'], t['seconds']) for t in album['tracks']], [(1, 'INTRO', 122), (2, 'ANGELS', 258)])

    def test_full_date_handles_year_month_and_day(self):
        self.assertEqual(self.spotify.full_date('2021'), '2021-01-01')
        self.assertEqual(self.spotify.full_date('2021-04'), '2021-04-01')
        self.assertEqual(self.spotify.full_date('2021-04-23'), '2021-04-23')
        self.assertEqual(self.spotify.full_date(''), '')

    def test_the_access_token_is_reused_until_it_expires(self):
        from unittest import mock
        reply = b'{"access_token": "tok", "expires_in": 3600}'
        with override_settings(**KEYS), mock.patch.object(self.spotify, '_open', return_value=reply) as opened:
            self.assertEqual(self.spotify._access_token(), 'tok')
            self.assertEqual(self.spotify._access_token(), 'tok')
        self.assertEqual(opened.call_count, 1)

    def test_without_keys_nothing_is_called(self):
        with override_settings(SPOTIFY_CLIENT_ID='', SPOTIFY_CLIENT_SECRET=''):
            self.assertFalse(self.spotify.is_configured())
            with self.assertRaises(self.spotify.SpotifyError):
                self.spotify._access_token()

    def test_pictures_are_only_taken_from_spotifys_own_servers(self):
        ok = self.spotify.allowed_image_url
        self.assertTrue(ok('https://i.scdn.co/image/abc'))
        self.assertTrue(ok('https://mosaic.scdn.co/640/x'))
        for bad in ('http://i.scdn.co/image/abc', 'https://evil.example.com/i.jpg', 'https://scdn.co.evil.com/i.jpg',
                    'file:///etc/passwd', 'javascript:alert(1)', '', 'not a url'):
            self.assertFalse(ok(bad), bad)


@override_settings(**KEYS)
class SpotifyFormTests(BaseTestCase):
    """The Spotify box on the New artist / New album forms and what happens on Save."""

    def setUp(self):
        from unittest import mock
        self.mock = mock
        self.login()

    def test_endpoints_need_login(self):
        self.client.logout()
        for url in (reverse('spotify_artists'), reverse('spotify_albums'), reverse('spotify_album', args=['abc123'])):
            self.assertEqual(self.client.get(url, {'q': 'x'}).status_code, 302, url)

    def test_artist_search_returns_results(self):
        fake = [{'id': 'a1', 'name': 'Chase Atlantic', 'image': 'https://i.scdn.co/x', 'genres': [], 'followers': 5}]
        with self.mock.patch('music.spotify.search_artists', return_value=fake):
            data = self.client.get(reverse('spotify_artists'), {'q': 'chase'}).json()
        self.assertEqual(data['results'], fake)
        self.assertTrue(data['enabled'])

    def test_album_search_points_at_the_matching_artist_in_this_catalog(self):
        fake = [{'id': 'al1', 'title': 'Discovery', 'artist': 'daft punk', 'main_artist': 'daft punk', 'date': '2001-03-12',
                 'image': '', 'total_tracks': 14, 'kind': 'album'},
                {'id': 'al2', 'title': 'Other', 'artist': 'Unknown Band', 'main_artist': 'Unknown Band', 'date': '2020',
                 'image': '', 'total_tracks': 1, 'kind': 'single'}]
        with self.mock.patch('music.spotify.search_albums', return_value=fake):
            results = self.client.get(reverse('spotify_albums'), {'q': 'disc'}).json()['results']
        self.assertEqual(results[0]['artist_id'], self.artist.pk)       # "daft punk" matches "Daft Punk" ignoring case
        self.assertIsNone(results[1]['artist_id'])

    def test_empty_query_asks_spotify_nothing(self):
        with self.mock.patch('music.spotify.search_artists') as search:
            self.assertEqual(self.client.get(reverse('spotify_artists'), {'q': '  '}).json()['results'], [])
        search.assert_not_called()

    def test_spotify_trouble_is_reported_not_crashed(self):
        from . import spotify
        with self.mock.patch('music.spotify.search_artists', side_effect=spotify.SpotifyError('Spotify answered 429')):
            response = self.client.get(reverse('spotify_artists'), {'q': 'x'})
        self.assertEqual(response.status_code, 502)
        self.assertIn('429', response.json()['error'])

    @override_settings(SPOTIFY_CLIENT_ID='', SPOTIFY_CLIENT_SECRET='')
    def test_without_keys_the_box_is_hidden_and_endpoints_say_so(self):
        for url in (reverse('artist_create'), reverse('album_create')):
            self.assertNotContains(self.client.get(url), 'sp-search')
        response = self.client.get(reverse('spotify_artists'), {'q': 'x'})
        self.assertEqual((response.status_code, response.json()['enabled']), (404, False))

    def test_with_keys_the_box_shows_on_new_forms_but_not_on_edit(self):
        self.assertContains(self.client.get(reverse('artist_create')), 'Fill in from Spotify')
        self.assertContains(self.client.get(reverse('album_create')), 'Fill in from Spotify')
        self.assertNotContains(self.client.get(reverse('artist_update', args=[self.artist.pk])), 'sp-search')
        self.assertNotContains(self.client.get(reverse('album_update', args=[self.album.pk])), 'sp-search')

    def test_new_artist_form_can_be_prefilled_from_the_link(self):
        self.assertContains(self.client.get(reverse('artist_create'), {'name': 'Brand New Band'}), 'value="Brand New Band"')

    def test_saving_an_artist_downloads_the_picked_spotify_photo(self):
        with self.mock.patch('music.spotify.download_image', return_value=_fake_jpeg()) as download:
            self.client.post(reverse('artist_create'), {'name': 'Chase Atlantic', 'bio': '', 'spotify_image': 'https://i.scdn.co/image/abc'})
        download.assert_called_once_with('https://i.scdn.co/image/abc')
        artist = Artist.objects.get(name='Chase Atlantic')
        self.assertTrue(artist.image.name.startswith('artists/chase-atlantic'))
        self.assertTrue(artist.accent_color.startswith('#'))               # the page colour was worked out from it
        artist.image.delete(save=False)

    def test_an_uploaded_file_beats_the_spotify_photo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload = SimpleUploadedFile('mine.jpg', _fake_jpeg(), content_type='image/jpeg')
        with self.mock.patch('music.spotify.download_image') as download:
            self.client.post(reverse('artist_create'), {'name': 'Own Photo', 'bio': '', 'image': upload,
                                                        'spotify_image': 'https://i.scdn.co/image/abc'})
        download.assert_not_called()
        Artist.objects.get(name='Own Photo').image.delete(save=False)

    def test_a_picture_from_another_site_is_refused(self):
        response = self.client.post(reverse('artist_create'), {'name': 'Sneaky', 'bio': '', 'spotify_image': 'https://evil.example.com/x.jpg'})
        self.assertEqual(response.status_code, 200)                         # the form is shown again with an error
        self.assertFalse(Artist.objects.filter(name='Sneaky').exists())

    def test_a_failed_picture_download_still_saves_the_artist_with_a_warning(self):
        from . import spotify
        with self.mock.patch('music.spotify.download_image', side_effect=spotify.SpotifyError('Could not download the picture')):
            response = self.client.post(reverse('artist_create'), {'name': 'No Photo', 'bio': '', 'spotify_image': 'https://i.scdn.co/x'}, follow=True)
        self.assertTrue(Artist.objects.filter(name='No Photo').exists())
        self.assertContains(response, 'Spotify picture could not be added')

    def _album_post(self, **extra):
        data = {'title': 'PHASES', 'artist': self.artist.pk, 'release_date': '2019-06-28', 'spotify_album_id': 'AbC123xyz0987',
                'import_tracks': 'on'}
        data.update(extra)
        return self.client.post(reverse('album_create'), data, follow=True)

    DETAILS = {'tracks': [{'number': 1, 'title': 'INTRO', 'seconds': 122, 'artist': ''},
                          {'number': 2, 'title': 'ANGELS', 'seconds': 258, 'artist': ''}]}

    def test_saving_an_album_adds_the_song_list(self):
        with self.mock.patch('music.spotify.album_details', return_value=self.DETAILS):
            response = self._album_post()
        album = Album.objects.get(title='PHASES')
        self.assertEqual([(t.track_number, t.title, t.duration_seconds) for t in album.tracks.all().order_by('track_number')],
                         [(1, 'INTRO', 122), (2, 'ANGELS', 258)])
        self.assertContains(response, 'Added 2 songs from Spotify')

    def test_unticking_the_box_skips_the_song_list(self):
        with self.mock.patch('music.spotify.album_details', return_value=self.DETAILS) as details:
            data = {'title': 'No Songs', 'artist': self.artist.pk, 'release_date': '2019-06-28', 'spotify_album_id': 'AbC123xyz0987'}
            self.client.post(reverse('album_create'), data)                    # import_tracks left out = unticked
        details.assert_not_called()
        self.assertEqual(Album.objects.get(title='No Songs').tracks.count(), 0)

    def test_importing_never_doubles_existing_track_numbers(self):
        from . import imports
        album = Album.objects.create(title='X', artist=self.artist, release_date=datetime.date(2020, 1, 1))
        Track.objects.create(album=album, title='Mine', track_number=1, duration=datetime.timedelta(minutes=1))
        added = imports.add_album_tracks(album, self.DETAILS['tracks'])
        self.assertEqual(added, 1)
        self.assertEqual(album.tracks.get(track_number=1).title, 'Mine')

    def test_a_failed_song_list_still_saves_the_album_with_a_warning(self):
        from . import spotify
        with self.mock.patch('music.spotify.album_details', side_effect=spotify.SpotifyError('Could not reach Spotify')):
            response = self._album_post(title='Offline')
        self.assertTrue(Album.objects.filter(title='Offline').exists())
        self.assertContains(response, 'song list could not be added')

    def test_a_bad_album_id_is_rejected(self):
        response = self.client.post(reverse('album_create'), {'title': 'Bad', 'artist': self.artist.pk, 'release_date': '2019-06-28',
                                                              'spotify_album_id': '../../etc/passwd'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Album.objects.filter(title='Bad').exists())

    def test_saving_an_album_downloads_the_cover(self):
        with self.mock.patch('music.spotify.download_image', return_value=_fake_jpeg()):
            self.client.post(reverse('album_create'), {'title': 'Covered', 'artist': self.artist.pk, 'release_date': '2019-06-28',
                                                       'spotify_image': 'https://i.scdn.co/image/c'})
        album = Album.objects.get(title='Covered')
        self.assertTrue(album.cover.name.startswith('covers/covered'))
        album.cover.delete(save=False)


class ArtistCrudRequirementTests(BaseTestCase):
    """Requirement: Artist management (CRUD): create (name, bio, image), list, detail (bio, albums), update, delete."""

    def setUp(self):
        import tempfile
        self._media = tempfile.TemporaryDirectory()
        override = override_settings(MEDIA_ROOT=self._media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._media.cleanup)
        self.login()

    # ---- create
    def test_create_with_name_bio_and_image(self):
        response = self.client.post(reverse('artist_create'), {'name': 'Air', 'bio': 'French band.', 'image': _jpeg((200, 60, 60))})
        artist = Artist.objects.get(name='Air')
        self.assertRedirects(response, artist.get_absolute_url())
        self.assertEqual(artist.bio, 'French band.')
        self.assertTrue(artist.image.name.startswith('artists/'))
        self.assertTrue(artist.image.storage.exists(artist.image.name))             # the file really was stored
        self.assertTrue(artist.accent_color.startswith('#'))
        self.assertContains(self.client.get(artist.get_absolute_url()), artist.image.url)

    def test_bio_and_image_are_optional_but_the_name_is_required(self):
        self.client.post(reverse('artist_create'), {'name': 'Only A Name', 'bio': ''})
        artist = Artist.objects.get(name='Only A Name')
        self.assertEqual((artist.bio, bool(artist.image)), ('', False))
        response = self.client.post(reverse('artist_create'), {'name': '', 'bio': 'no name'})
        self.assertContains(response, 'This field is required')
        self.assertFalse(Artist.objects.filter(bio='no name').exists())

    def test_a_file_that_is_not_an_image_is_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake = SimpleUploadedFile('virus.jpg', b'this is not a picture', content_type='image/jpeg')
        response = self.client.post(reverse('artist_create'), {'name': 'Bad Upload', 'bio': '', 'image': fake})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Artist.objects.filter(name='Bad Upload').exists())

    def test_the_form_has_the_three_fields(self):
        html = self.client.get(reverse('artist_create')).content.decode()
        for field in ('name="name"', 'name="bio"', 'name="image"', 'enctype="multipart/form-data"'):
            self.assertIn(field, html)

    # ---- list
    def test_the_list_shows_every_artist_with_a_link_and_a_new_artist_button(self):
        other = Artist.objects.create(name='Justice')
        response = self.client.get(reverse('artist_list'))
        for artist in (self.artist, other):
            self.assertContains(response, artist.name)
            self.assertContains(response, f'href="{artist.get_absolute_url()}"')
        self.assertContains(response, reverse('artist_create'))

    def test_an_empty_list_says_so(self):
        Artist.objects.all().delete()
        self.assertContains(self.client.get(reverse('artist_list')), 'No artists yet.')

    # ---- detail
    def test_detail_shows_the_bio_and_only_this_artists_albums(self):
        other = Artist.objects.create(name='Justice')
        Album.objects.create(title='Cross', artist=other, release_date=datetime.date(2007, 6, 11))
        html = self.client.get(self.artist.get_absolute_url()).content.decode()
        self.assertIn('Daft Punk', html)
        self.assertIn('French duo', html)                                           # the bio
        self.assertIn('Discovery', html)                                            # their album ...
        self.assertIn(f'href="{self.album.get_absolute_url()}"', html)              # ... linking to it
        self.assertNotIn('Cross', html)                                             # not another artist's
        for link in (reverse('artist_update', args=[self.artist.pk]), reverse('artist_delete', args=[self.artist.pk])):
            self.assertIn(link, html)

    def test_detail_of_an_artist_with_no_albums_or_bio_still_works(self):
        lone = Artist.objects.create(name='Lonely')
        html = self.client.get(lone.get_absolute_url()).content.decode()
        self.assertIn('No albums yet.', html)
        self.assertNotIn('<h2>About</h2>', html)
        self.assertEqual(self.client.get(reverse('artist_detail', args=[99999])).status_code, 404)

    # ---- update
    def test_update_changes_the_details_and_keeps_the_image_when_none_is_uploaded(self):
        self.client.post(reverse('artist_create'), {'name': 'Air', 'bio': 'old', 'image': _jpeg((200, 60, 60))})
        artist = Artist.objects.get(name='Air')
        first_image = artist.image.name
        self.client.post(reverse('artist_update', args=[artist.pk]), {'name': 'AIR (band)', 'bio': 'new bio'})
        artist.refresh_from_db()
        self.assertEqual((artist.name, artist.bio, artist.image.name), ('AIR (band)', 'new bio', first_image))

    def test_update_can_replace_or_clear_the_image(self):
        self.client.post(reverse('artist_create'), {'name': 'Air', 'bio': '', 'image': _jpeg((200, 60, 60))})
        artist = Artist.objects.get(name='Air')
        old = artist.image.name
        self.client.post(reverse('artist_update', args=[artist.pk]), {'name': 'Air', 'bio': '', 'image': _jpeg((60, 60, 200))})
        artist.refresh_from_db()
        self.assertNotEqual(artist.image.name, old)                                  # a new picture
        self.client.post(reverse('artist_update', args=[artist.pk]), {'name': 'Air', 'bio': '', 'image-clear': 'on'})
        artist.refresh_from_db()
        self.assertFalse(artist.image)                                               # cleared

    def test_update_refuses_a_blank_name(self):
        response = self.client.post(reverse('artist_update', args=[self.artist.pk]), {'name': '', 'bio': 'x'})
        self.assertContains(response, 'This field is required')
        self.artist.refresh_from_db()
        self.assertEqual(self.artist.name, 'Daft Punk')

    # ---- delete (with confirmation)
    def test_delete_asks_for_confirmation_first_and_deletes_only_on_yes(self):
        page = self.client.get(reverse('artist_delete', args=[self.artist.pk]))
        self.assertContains(page, 'Delete "Daft Punk"?')                              # the name is in the question
        self.assertContains(page, 'Yes, delete')
        self.assertContains(page, 'Cancel')
        self.assertContains(page, 'albums and tracks will be deleted too')            # warns about what else goes
        self.assertTrue(Artist.objects.filter(pk=self.artist.pk).exists())            # visiting the page deletes nothing
        response = self.client.post(reverse('artist_delete', args=[self.artist.pk]))
        self.assertRedirects(response, reverse('artist_list'))
        self.assertFalse(Artist.objects.filter(pk=self.artist.pk).exists())

    def test_delete_removes_their_albums_and_tracks_but_nobody_elses(self):
        other = Artist.objects.create(name='Justice')
        album = Album.objects.create(title='Cross', artist=other, release_date=datetime.date(2007, 6, 11))
        Track.objects.create(album=album, title='D.A.N.C.E.', track_number=1, duration=datetime.timedelta(minutes=4))
        self.client.post(reverse('artist_delete', args=[self.artist.pk]))
        self.assertEqual(list(Artist.objects.values_list('name', flat=True)), ['Justice'])
        self.assertEqual(list(Album.objects.values_list('title', flat=True)), ['Cross'])
        self.assertEqual(list(Track.objects.values_list('title', flat=True)), ['D.A.N.C.E.'])

    def test_the_delete_button_on_the_detail_page_opens_the_popup(self):
        html = self.client.get(self.artist.get_absolute_url()).content.decode()
        self.assertIn(f'href="{reverse("artist_delete", args=[self.artist.pk])}" data-confirm-delete data-name="Daft Punk"', html)
        self.assertIn('<dialog id="confirm-dialog"', html)

    def test_deleting_an_artist_that_does_not_exist_is_a_404(self):
        self.assertEqual(self.client.post(reverse('artist_delete', args=[99999])).status_code, 404)


class ArtistBioDisplayTests(BaseTestCase):
    """The About text on the artist page: only a short preview with "See more", and the Wikipedia credit kept out of
    the text (as a small line under it)."""

    def setUp(self):
        self.login()

    def test_the_bio_is_clamped_with_a_see_more_button(self):
        html = self.client.get(self.artist.get_absolute_url()).content.decode()
        self.assertIn('class="bio-text is-clamped"', html)
        self.assertIn('id="artist-bio-more"', html)
        self.assertIn('See more', html)

    def test_the_preview_is_two_lines(self):
        css = (settings.BASE_DIR / 'static' / 'css' / 'style.css').read_text(encoding='utf-8')
        self.assertIn('-webkit-line-clamp: 2', css.split('.bio-text.is-clamped')[1].split('}')[0])

    def test_the_credit_is_a_separate_small_line_not_part_of_the_bio(self):
        Artist.objects.filter(pk=self.artist.pk).update(bio='French duo.', bio_source='https://en.wikipedia.org/wiki/Daft_Punk')
        html = self.client.get(self.artist.get_absolute_url()).content.decode()
        self.assertIn('French duo.', html)
        self.assertNotIn('Source: Wikipedia', html)
        self.assertIn('Bio from <a href="https://en.wikipedia.org/wiki/Daft_Punk"', html)
        self.assertIn('CC BY-SA 4.0', html)

    def test_no_credit_line_for_a_bio_you_wrote_yourself(self):
        self.assertNotIn('Bio from', self.client.get(self.artist.get_absolute_url()).content.decode())

    def test_the_credit_is_saved_from_the_form_but_only_for_wikipedia_and_only_with_a_bio(self):
        wiki = 'https://en.wikipedia.org/wiki/Air_(band)'
        self.client.post(reverse('artist_create'), {'name': 'Air', 'bio': 'French band.', 'bio_source': wiki})
        self.assertEqual(Artist.objects.get(name='Air').bio_source, wiki)
        self.client.post(reverse('artist_create'), {'name': 'Evil', 'bio': 'x', 'bio_source': 'https://evil.example.com/page'})
        self.assertEqual(Artist.objects.get(name='Evil').bio_source, '')            # not Wikipedia: dropped
        self.client.post(reverse('artist_create'), {'name': 'Nobio', 'bio': '', 'bio_source': wiki})
        self.assertEqual(Artist.objects.get(name='Nobio').bio_source, '')           # no bio left: nothing to credit

    def test_editing_keeps_the_credit_through_the_hidden_field(self):
        wiki = 'https://en.wikipedia.org/wiki/Daft_Punk'
        Artist.objects.filter(pk=self.artist.pk).update(bio_source=wiki)
        html = self.client.get(reverse('artist_update', args=[self.artist.pk])).content.decode()
        self.assertIn(f'name="bio_source" value="{wiki}"', html)

    def test_the_migration_moves_old_credit_lines_out_of_existing_bios(self):
        from importlib import import_module
        from django.apps import apps
        old = 'A band.\n\nSource: Wikipedia (https://en.wikipedia.org/wiki/Ben%26Ben), CC BY-SA 4.0.'
        artist = Artist.objects.create(name='Ben&Ben', bio=old)
        import_module('music.migrations.0007_move_wikipedia_credit_out_of_bios').credit_to_its_own_field(apps, None)
        artist.refresh_from_db()
        self.assertEqual((artist.bio, artist.bio_source), ('A band.', 'https://en.wikipedia.org/wiki/Ben%26Ben'))


class CancelLinkTests(BaseTestCase):
    """Cancel on a "new ..." form goes back to the page the form was opened from."""

    def setUp(self):
        self.login()

    def cancel_for(self, url, **headers):
        response = self.client.get(url, **headers)
        return response.context['cancel_url']

    def test_from_the_albums_page_it_goes_back_to_the_albums_page(self):
        self.assertEqual(self.cancel_for(reverse('album_create'), HTTP_REFERER='http://testserver/albums/'), '/albums/')

    def test_from_the_home_page_it_goes_back_home(self):
        self.assertEqual(self.cancel_for(reverse('album_create'), HTTP_REFERER='http://testserver/'), '/')

    def test_from_an_artist_page_it_goes_back_to_that_artist(self):
        url = reverse('album_create') + f'?artist={self.artist.pk}'
        self.assertEqual(self.cancel_for(url, HTTP_REFERER=f'http://testserver{self.artist.get_absolute_url()}'), self.artist.get_absolute_url())

    def test_each_form_has_its_own_fallback_when_there_is_no_referer(self):
        self.assertEqual(self.cancel_for(reverse('album_create')), reverse('album_list'))
        self.assertEqual(self.cancel_for(reverse('artist_create')), reverse('artist_list'))
        self.assertEqual(self.cancel_for(reverse('playlist_create')), reverse('playlist_list'))

    def test_a_referer_from_another_site_is_ignored(self):
        self.assertEqual(self.cancel_for(reverse('album_create'), HTTP_REFERER='https://evil.example.com/'), reverse('album_list'))

    def test_the_form_itself_is_never_the_cancel_target(self):
        self.assertEqual(self.cancel_for(reverse('album_create'), HTTP_REFERER='http://testserver/albums/new/'), reverse('album_list'))

    def test_the_cancel_link_and_a_hidden_next_field_are_in_the_page(self):
        html = self.client.get(reverse('album_create'), HTTP_REFERER='http://testserver/albums/').content.decode()
        self.assertIn('<input type="hidden" name="next" value="/albums/">', html)
        self.assertRegex(html, r'href="/albums/">Cancel</a>')

    def test_after_a_mistake_the_form_remembers_where_to_cancel_to(self):
        response = self.client.post(reverse('album_create'), {'title': '', 'artist': '', 'release_date': '', 'next': '/artists/'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cancel_url'], '/artists/')
        self.assertRegex(response.content.decode(), r'href="/artists/">Cancel</a>')

    def test_a_next_value_pointing_at_another_site_is_ignored(self):
        response = self.client.post(reverse('album_create'), {'title': '', 'artist': '', 'release_date': '', 'next': 'https://evil.example.com/'})
        self.assertEqual(response.context['cancel_url'], reverse('album_list'))

    def test_edit_forms_still_cancel_to_the_item_itself(self):
        html = self.client.get(reverse('album_update', args=[self.album.pk])).content.decode()
        self.assertRegex(html, rf'href="{self.album.get_absolute_url()}">Cancel</a>')


class ToastTests(BaseTestCase):
    """Notifications are popup bubbles that disappear by themselves (static/js/toast.js)."""

    def read(self, *parts):
        return (settings.BASE_DIR.joinpath(*parts)).read_text(encoding='utf-8')

    def test_every_page_loads_the_toast_script_and_marks_the_page_as_js_capable(self):
        for url, login in ((reverse('home'), True), (reverse('login'), False)):
            if login:
                self.login()
            else:
                self.client.logout()
            html = self.client.get(url).content.decode()
            self.assertIn("document.documentElement.classList.add('js')", html, url)
            self.assertIn('js/toast.js', html, url)
            self.assertLess(html.index('js/toast.js'), html.index('js/player.js') if 'js/player.js' in html else len(html))

    def test_messages_are_still_in_the_page_for_visitors_without_javascript(self):
        self.login()
        response = self.client.post(reverse('playlist_partner_add', args=[self.playlist.pk]), {'username': 'nobody-here'}, follow=True)
        self.assertContains(response, '<ul class="messages">')
        self.assertContains(response, 'There is no user named')
        self.assertContains(response, '<li class="error">')              # the kind the bubble is coloured by

    def test_the_bubble_lasts_about_two_seconds_and_errors_a_bit_longer(self):
        js = self.read('static', 'js', 'toast.js')
        self.assertIn('DEFAULT_MS = 2200', js)
        self.assertIn('error: 3800', js)
        self.assertIn('window.Toast = { show: show, scan: scan }', js)

    def test_the_plain_list_is_hidden_when_javascript_runs_and_bubbles_are_styled(self):
        css = self.read('static', 'css', 'style.css')
        self.assertIn('.js ul.messages { display: none; }', css)
        for rule in ('.toasts {', '.toast-success::before', '.toast-error::before', '.toast.is-on'):
            self.assertIn(rule, css)

    def test_page_changes_and_the_playlist_menu_use_the_same_bubbles(self):
        self.assertIn('window.Toast.scan()', self.read('static', 'js', 'nav.js'))           # messages arriving with a new page
        menu = self.read('static', 'js', 'pl_menu.js')
        self.assertIn('window.Toast.show', menu)
        self.assertNotIn("className = 'toast'", menu)                                        # no second, separate bubble


class ArtistPageAlbumGridTests(BaseTestCase):
    """On phones the albums on an artist's page sit two per row, like the Albums page (not one huge card each)."""

    def css(self):
        return (settings.BASE_DIR / 'static' / 'css' / 'style.css').read_text(encoding='utf-8')

    def test_the_albums_are_in_the_detail_scroll_area_the_stylesheet_targets(self):
        self.login()
        html = self.client.get(self.artist.get_absolute_url()).content.decode()
        self.assertIn('class="detail-scroll"', html)
        self.assertIn('class="grid', html.split('class="detail-scroll"')[1])          # the album cards grid is inside it

    def test_phones_get_two_columns_and_tablets_three_like_the_albums_page(self):
        css = self.css()
        phone = css.split('@media (max-width: 560px) {\n  .detail-scroll .grid')[1].split('}')[0]
        self.assertIn('repeat(2, minmax(0, 1fr))', phone)
        self.assertIn('@media (max-width: 900px) { .detail-scroll .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }', css)
        # the Albums page uses the very same column counts
        self.assertIn('@media (max-width: 560px) { .list-scroll .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }', css)

    def test_long_album_names_wrap_instead_of_stretching_the_card(self):
        phone = self.css().split('@media (max-width: 560px) {\n  .detail-scroll .grid')[1].split('\n}\n')[0]
        self.assertIn('-webkit-line-clamp: 2', phone)


class ArtistPickerTests(BaseTestCase):
    """The nicer Artist dropdown on the album form (static/js/artist_picker.js)."""

    def setUp(self):
        self.login()

    def test_the_select_is_marked_for_the_picker_and_options_carry_the_artists_photo(self):
        Artist.objects.filter(pk=self.artist.pk).update(image='artists/daft.jpg')
        html = self.client.get(reverse('album_create')).content.decode()
        self.assertIn('data-artist-picker', html)
        self.assertIn(f'data-new-url="{reverse("artist_create")}"', html)
        self.assertRegex(html, r'<option value="%d" data-image="[^"]*artists/daft\.jpg"' % self.artist.pk)
        self.assertIn('js/artist_picker.js', html)

    def test_it_is_still_a_normal_dropdown_that_submits_the_chosen_artist(self):
        response = self.client.post(reverse('album_create'), {'title': 'New LP', 'artist': self.artist.pk, 'release_date': '2020-01-01'})
        self.assertEqual(Album.objects.get(title='New LP').artist, self.artist)
        self.assertEqual(response.status_code, 302)


class WikipediaBioTests(BaseTestCase):
    """The short artist bio the "Fill in from Spotify" box takes from Wikipedia (Wikipedia's answers are faked here)."""

    def setUp(self):
        from unittest import mock
        from django.core.cache import cache
        from . import wikipedia
        cache.clear()
        self.mock, self.wiki = mock, wikipedia

    @staticmethod
    def reply(*pages, redirects=()):
        return {'query': {'redirects': [{'from': a, 'to': b} for a, b in redirects],
                          'pages': {str(i if 'missing' not in p else -1 - i): p for i, p in enumerate(pages, start=1)}}}

    BAND = {'title': 'Chase Atlantic', 'extract': 'Chase Atlantic is an Australian alternative R&B band formed in Cairns in 2014.'}

    def lookup(self, name, payload):
        with self.mock.patch.object(self.wiki, '_get', return_value=payload):
            return self.wiki.artist_bio(name)

    def test_a_musical_page_with_the_same_title_is_used_and_credited(self):
        found = self.lookup('Chase Atlantic', self.reply(self.BAND))
        self.assertIn('Australian alternative R&B band', found['bio'])
        self.assertEqual(found['url'], 'https://en.wikipedia.org/wiki/Chase_Atlantic')
        self.assertNotIn('Source:', found['bio'])                     # the credit is kept apart from the text

    def test_a_non_musical_page_is_skipped_for_the_singer_page(self):
        football = {'title': 'Malcolm Todd', 'extract': 'Malcolm Todd (born 1970) is a retired English footballer.'}
        singer = {'title': 'Malcolm Todd (singer)', 'extract': 'Malcolm Todd is an American singer and songwriter.'}
        found = self.lookup('Malcolm Todd', self.reply(football, singer))
        self.assertEqual(found['title'], 'Malcolm Todd (singer)')

    def test_disambiguation_pages_are_never_used(self):
        page = dict(self.BAND, pageprops={'disambiguation': ''})
        self.assertIsNone(self.lookup('Chase Atlantic', self.reply(page)))

    def test_a_page_with_a_different_name_is_rejected(self):
        other = {'title': 'Chase Atlantis', 'extract': 'Chase Atlantis is a band.'}
        self.assertIsNone(self.lookup('Chase Atlantic', self.reply(other)))

    def test_redirects_and_accents_are_followed(self):
        page = {'title': 'Beyoncé', 'extract': 'Beyoncé is an American singer, songwriter and businesswoman.'}
        found = self.lookup('Beyonce', self.reply(page, redirects=[('Beyonce', 'Beyoncé')]))
        self.assertEqual(found['title'], 'Beyoncé')

    def test_missing_pages_give_no_bio(self):
        self.assertIsNone(self.lookup('Nobody Known', self.reply({'title': 'Nobody Known', 'missing': ''})))

    def test_long_intros_are_cut_at_a_sentence_end(self):
        long = ' '.join(f'Sentence number {n} about the band and its music.' for n in range(40))
        page = {'title': 'Chase Atlantic', 'extract': 'Chase Atlantic is a band. ' + long}
        bio = self.lookup('Chase Atlantic', self.reply(page))['bio']
        self.assertLessEqual(len(bio), 700)
        self.assertTrue(bio.endswith('.'))

    def test_a_network_error_gives_nothing_and_is_not_remembered(self):
        with self.mock.patch.object(self.wiki, '_get', side_effect=OSError('offline')):
            self.assertIsNone(self.wiki.artist_bio('Chase Atlantic'))
        self.assertIsNotNone(self.lookup('Chase Atlantic', self.reply(self.BAND)))       # the next try works

    def test_answers_are_remembered_so_wikipedia_is_not_asked_twice(self):
        with self.mock.patch.object(self.wiki, '_get', return_value=self.reply(self.BAND)) as get:
            self.wiki.artist_bio('Chase Atlantic')
            self.wiki.artist_bio('chase atlantic')
        self.assertEqual(get.call_count, 1)

    def test_the_endpoint_needs_login_and_never_errors(self):
        url = reverse('artist_bio')
        self.assertEqual(self.client.get(url, {'name': 'x'}).status_code, 302)
        self.login()
        self.assertEqual(self.client.get(url, {'name': ''}).json(), {'bio': '', 'source': ''})
        with self.mock.patch.object(self.wiki, '_get', side_effect=OSError('offline')):
            self.assertEqual(self.client.get(url, {'name': 'Chase Atlantic'}).json(), {'bio': '', 'source': ''})
        with self.mock.patch.object(self.wiki, '_get', return_value=self.reply(self.BAND)):
            data = self.client.get(url, {'name': 'Chase Atlantic'}).json()
        self.assertIn('Australian', data['bio'])
        self.assertNotIn('Source:', data['bio'])
        self.assertEqual(data['source'], 'https://en.wikipedia.org/wiki/Chase_Atlantic')

    def test_the_new_artist_form_passes_the_bio_address_to_the_box(self):
        self.login()
        with override_settings(**KEYS):
            html = self.client.get(reverse('artist_create')).content.decode()
        self.assertIn(f'data-bio-url="{reverse("artist_bio")}"', html)


class PlaylistPartnerTests(BaseTestCase):
    """The creator (alice) can invite a partner (bob): he may edit the playlist and add / remove its songs, but only
    alice can delete it or change partners."""

    def setUp(self):
        self.carol = User.objects.create_user('carol', password='pw-carol-123')
        self.add_url = reverse('playlist_partner_add', args=[self.playlist.pk])
        self.make_bob_partner = lambda: PlaylistPartner.objects.create(playlist=self.playlist, user=self.bob)

    # ---- inviting and removing
    def test_creator_adds_a_partner_by_username_ignoring_case(self):
        self.login()
        self.client.post(self.add_url, {'username': 'BOB'})
        self.assertTrue(self.playlist.is_partner(self.bob))
        self.assertIn(self.bob, self.playlist.partners.all())

    def test_bad_names_add_nobody(self):
        self.login()
        for name, text in (('nobody-here', 'no user named'), ('', 'Type the username'), ('alice', 'already own')):
            response = self.client.post(self.add_url, {'username': name}, follow=True)
            self.assertContains(response, text)
        self.make_bob_partner()
        self.assertContains(self.client.post(self.add_url, {'username': 'bob'}, follow=True), 'already a partner')
        self.assertEqual(PlaylistPartner.objects.count(), 1)

    def test_only_the_creator_manages_partners(self):
        self.make_bob_partner()
        for who in ('bob', 'carol'):
            self.client.logout()
            self.login(who)
            self.assertEqual(self.client.post(self.add_url, {'username': 'carol'}).status_code, 404, who)
            self.assertEqual(self.client.post(reverse('playlist_partner_remove', args=[self.playlist.pk, self.bob.pk])).status_code
                             if who == 'carol' else 302, 404 if who == 'carol' else 302)
        self.assertFalse(self.playlist.is_partner(self.carol))
        self.assertTrue(self.playlist.is_partner(self.bob))

    def test_creator_removes_a_partner_and_access_goes_with_it(self):
        self.make_bob_partner()
        self.login()
        self.client.post(reverse('playlist_partner_remove', args=[self.playlist.pk, self.bob.pk]))
        self.assertFalse(self.playlist.is_partner(self.bob))
        self.client.logout()
        self.login('bob')
        self.assertEqual(self.client.get(reverse('playlist_update', args=[self.playlist.pk])).status_code, 404)

    def test_a_partner_can_leave_but_not_remove_someone_else(self):
        self.make_bob_partner()
        PlaylistPartner.objects.create(playlist=self.playlist, user=self.carol)
        self.login('bob')
        self.assertEqual(self.client.post(reverse('playlist_partner_remove', args=[self.playlist.pk, self.carol.pk])).status_code, 404)
        response = self.client.post(reverse('playlist_partner_remove', args=[self.playlist.pk, self.bob.pk]))
        self.assertRedirects(response, reverse('playlist_list'))
        self.assertFalse(self.playlist.is_partner(self.bob))
        self.assertTrue(self.playlist.is_partner(self.carol))

    # ---- what a partner may do
    def test_a_partner_can_edit_the_playlist_details(self):
        self.make_bob_partner()
        self.login('bob')
        self.assertEqual(self.client.get(reverse('playlist_update', args=[self.playlist.pk])).status_code, 200)
        self.client.post(reverse('playlist_update', args=[self.playlist.pk]), {'name': 'Renamed by Bob', 'description': 'hi'})
        self.playlist.refresh_from_db()
        self.assertEqual(self.playlist.name, 'Renamed by Bob')
        self.assertEqual(self.playlist.owner, self.alice)                # still alice's

    def test_a_partner_can_add_and_remove_songs(self):
        self.make_bob_partner()
        self.login('bob')
        self.client.post(reverse('playlist_add_track', args=[self.track.pk]), {'playlist': self.playlist.pk})
        self.assertEqual(PlaylistTrack.objects.filter(playlist=self.playlist).count(), 1)
        self.client.post(reverse('playlist_remove_track', args=[self.playlist.pk, self.track.pk]))
        self.assertEqual(PlaylistTrack.objects.filter(playlist=self.playlist).count(), 0)

    def test_a_partner_cannot_delete_the_playlist(self):
        self.make_bob_partner()
        self.login('bob')
        self.assertEqual(self.client.get(reverse('playlist_delete', args=[self.playlist.pk])).status_code, 404)
        self.client.post(reverse('playlist_delete', args=[self.playlist.pk]))
        self.assertTrue(Playlist.objects.filter(pk=self.playlist.pk).exists())

    def test_someone_who_is_not_a_partner_still_cannot_change_anything(self):
        self.make_bob_partner()
        self.login('carol')
        self.assertEqual(self.client.get(reverse('playlist_update', args=[self.playlist.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('playlist_add_track', args=[self.track.pk]), {'playlist': self.playlist.pk}).status_code, 404)
        self.assertEqual(self.client.post(reverse('playlist_remove_track', args=[self.playlist.pk, self.track.pk])).status_code, 404)

    # ---- what each person sees
    def test_the_playlist_page_shows_the_right_controls_to_each_person(self):
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)
        self.make_bob_partner()
        self.login()
        owner = self.client.get(self.playlist.get_absolute_url()).content.decode()
        for shown in ('Add partner', 'Delete playlist', 'Edit playlist', 'Remove partner' if False else 'Remove bob'):
            self.assertIn(shown, owner)
        self.client.logout()
        self.login('bob')
        partner = self.client.get(self.playlist.get_absolute_url()).content.decode()
        self.assertIn('Edit playlist', partner)
        self.assertIn('Remove', partner)                                    # songs can be removed
        self.assertIn('Leave', partner)
        for hidden in ('Delete playlist', 'Add partner', '+ Playlist'):
            self.assertNotIn(hidden, partner)
        self.client.logout()
        self.login('carol')
        stranger = self.client.get(self.playlist.get_absolute_url()).content.decode()
        for hidden in ('Edit playlist', 'Delete playlist', 'Add partner', 'Leave'):
            self.assertNotIn(hidden, stranger)

    def test_the_add_partner_box_sits_in_the_button_row_next_to_edit_and_delete(self):
        self.login()
        html = self.client.get(self.playlist.get_absolute_url()).content.decode()
        buttons = html.split('<div class="actions">')[1].split('</div>')[0]          # the Edit / Delete row
        for expected in ('Edit playlist', 'Delete playlist', 'class="partner-add"', 'Add partner'):
            self.assertIn(expected, buttons)
        self.assertEqual(html.count('class="partner-add"'), 1)                     # and it is no longer under "Partners"
        self.assertLess(html.index('class="partner-add"'), html.index('<h2>Partners</h2>'))

    def test_the_partner_playlist_shows_up_where_the_partners_own_playlists_do(self):
        self.make_bob_partner()
        self.login('bob')
        home = self.client.get(reverse('home')).content.decode()
        self.assertIn("partner on alice's", home)
        self.assertNotIn('Shared by others', home)                          # it is not listed as someone else's
        listing = self.client.get(reverse('playlist_list'))
        self.assertEqual([p.name for p in listing.context['shared_with_me']], ['Favourites'])
        self.assertEqual(listing.context['others'], [])
        self.assertContains(listing, 'Shared with you')

    def test_the_plus_playlist_menu_includes_playlists_you_partner_on(self):
        Playlist.objects.create(owner=self.bob, name='Bobs own')
        self.make_bob_partner()
        self.login('bob')
        html = self.client.get(self.album.get_absolute_url()).content.decode()
        self.assertIn('Bobs own', html)
        self.assertIn('Favourites', html)
        self.assertIn("alice's", html)                                       # tells whose it is
        self.assertEqual(self.client.post(reverse('playlist_add_track', args=[self.track.pk]),
                                          {'playlist': self.playlist.pk}, HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()['created'], True)

    def test_deleting_a_user_removes_their_partnerships(self):
        self.make_bob_partner()
        self.bob.delete()
        self.assertEqual(PlaylistPartner.objects.count(), 0)


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

    def test_list_shows_own_playlists_and_everyone_elses_in_a_separate_section(self):
        Playlist.objects.create(owner=self.bob, name='Bobs mix')
        self.login()
        response = self.client.get(reverse('playlist_list'))
        self.assertEqual([p.name for p in response.context['mine']], ['Favourites'])
        self.assertEqual([p.name for p in response.context['others']], ['Bobs mix'])
        self.assertContains(response, 'Shared by others')
        self.assertContains(response, 'by bob')

    def test_everyone_can_view_a_playlist_but_only_its_creator_can_edit_or_delete_it(self):
        self.login('bob')
        self.assertEqual(self.client.get(reverse('playlist_detail', args=[self.playlist.pk])).status_code, 200)
        for name in ('playlist_update', 'playlist_delete'):
            url = reverse(name, args=[self.playlist.pk])
            self.assertEqual(self.client.get(url).status_code, 404, name)
        self.client.post(reverse('playlist_update', args=[self.playlist.pk]), {'name': 'hacked'})
        self.client.post(reverse('playlist_delete', args=[self.playlist.pk]))
        self.playlist.refresh_from_db()
        self.assertEqual(self.playlist.name, 'Favourites')

    def test_other_peoples_playlist_page_has_no_edit_controls(self):
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)
        self.login('bob')
        Playlist.objects.create(owner=self.bob, name='Bobs own')            # bob has a playlist to copy songs into
        html = self.client.get(self.playlist.get_absolute_url()).content.decode()
        self.assertIn('One More Time', html)
        self.assertIn('by alice', html)
        for hidden in ('Edit playlist', 'Delete playlist', 'Remove'):
            self.assertNotIn(hidden, html)
        self.assertIn('+ Playlist', html)                                  # but a song can be copied to his own playlist
        self.assertIn('Bobs own', html)
        self.assertNotIn('Favourites</span>', html)                        # alice's playlist is not in bob's menu

    def test_owner_sees_the_edit_controls_and_no_add_menu(self):
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)
        self.login()
        html = self.client.get(self.playlist.get_absolute_url()).content.decode()
        for shown in ('Edit playlist', 'Delete playlist', 'Remove'):
            self.assertIn(shown, html)
        self.assertNotIn('+ Playlist', html)

    def test_nobody_else_can_remove_songs_or_add_to_someone_elses_playlist(self):
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)
        self.login('bob')
        self.assertEqual(self.client.post(reverse('playlist_remove_track', args=[self.playlist.pk, self.track.pk])).status_code, 404)
        self.assertEqual(PlaylistTrack.objects.count(), 1)
        other = Track.objects.create(album=self.album, title='Other', track_number=2, duration=datetime.timedelta(minutes=3))
        self.assertEqual(self.client.post(reverse('playlist_add_track', args=[other.pk]), {'playlist': self.playlist.pk}).status_code, 404)

    def test_plus_playlist_menu_ticks_playlists_that_already_hold_the_song(self):
        second = Playlist.objects.create(owner=self.alice, name='Road trip')
        PlaylistTrack.objects.create(playlist=self.playlist, track=self.track)
        self.login()
        html = self.client.get(self.album.get_absolute_url()).content.decode()
        self.assertIn('class="pl-details"', html)
        self.assertIn('Add to playlist', html)
        self.assertRegex(html, r'class="pl-item is-in"[^>]*disabled')      # Favourites already has it
        self.assertIn(f'name="playlist" value="{second.pk}" class="pl-item"', html)
        self.assertIn(reverse('playlist_create'), html)                    # "+ New playlist" shortcut

    def test_adding_from_the_menu_answers_json_for_the_page_script(self):
        self.login()
        url = reverse('playlist_add_track', args=[self.track.pk])
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        first = self.client.post(url, {'playlist': self.playlist.pk}, **headers).json()
        again = self.client.post(url, {'playlist': self.playlist.pk}, **headers).json()
        self.assertEqual(first, {'created': True, 'playlist': 'Favourites', 'track': 'One More Time'})
        self.assertFalse(again['created'])
        self.assertEqual(PlaylistTrack.objects.count(), 1)

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

    def test_someone_elses_playlist_can_be_opened_and_is_listed_under_shared(self):
        theirs = Playlist.objects.create(owner=self.bob, name='Bobs mix')
        PlaylistTrack.objects.create(playlist=theirs, track=self.track)
        data = self.client.get(reverse('home_playlist_tracks', args=[theirs.pk])).json()
        self.assertIn('One More Time', data['tracks'])
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('Shared by others', html)
        self.assertIn('Playlist &middot; bob &middot; 1 song<', html)
        self.assertLess(html.index('Favourites'), html.index('Shared by others'))   # own playlists come first

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


class LikedSongsDesignTests(BaseTestCase):
    """Liked Songs: card page like a playlist, and a pinned row at the top of the home Playlists panel."""

    def setUp(self):
        self.login()
        Like.objects.create(user=self.alice, track=self.track)

    def test_page_uses_the_card_layout_with_a_count(self):
        response = self.client.get(reverse('liked_songs'))
        self.assertContains(response, 'list-card is-detail')
        self.assertContains(response, 'liked-cover')
        self.assertContains(response, '1 song<')
        self.assertContains(response, 'One More Time')
        self.assertContains(response, f'--accent:{LIKED_COLOR}')

    def test_empty_page_explains_how_to_like_a_song(self):
        Like.objects.all().delete()
        response = self.client.get(reverse('liked_songs'))
        self.assertContains(response, "You haven't liked any songs yet")
        self.assertContains(response, '0 songs')

    def test_home_pins_liked_songs_above_the_playlists(self):
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('data-kind="liked"', html)
        self.assertIn('Playlist &middot; 1 song<', html)
        self.assertLess(html.index('data-kind="liked"'), html.index('data-kind="playlist"'))
        self.assertIn(f'data-liked-url="{reverse("home_liked_tracks")}"', html)

    def test_clicking_it_returns_the_liked_tracks_with_a_purple_tint(self):
        data = self.client.get(reverse('home_liked_tracks')).json()
        self.assertIn('One More Time', data['tracks'])
        self.assertNotIn('+ Add track', data['tracks'])
        self.assertIn('--tracks-panel:#', data['theme'])
        self.assertIn(LIKED_COLOR, data['theme'])

    def test_only_this_users_likes_are_shown(self):
        other = Track.objects.create(album=self.album, title='Secret Song', track_number=2,
                                     duration=datetime.timedelta(minutes=3))
        Like.objects.create(user=self.bob, track=other)
        data = self.client.get(reverse('home_liked_tracks')).json()
        self.assertNotIn('Secret Song', data['tracks'])

    def test_selection_is_remembered_and_replaced_by_the_next_pick(self):
        self.client.get(reverse('home_liked_tracks'))
        response = self.client.get(reverse('home'))
        self.assertTrue(response.context['selected_liked'])
        self.assertContains(response, 'lib-row is-selected')
        self.client.get(reverse('home_album_tracks', args=[self.album.pk]))      # an album takes over
        response = self.client.get(reverse('home'))
        self.assertFalse(response.context['selected_liked'])
        self.assertEqual(response.context['selected_album'], self.album)
        self.client.get(reverse('home_liked_tracks'))                            # liked takes the album's place
        response = self.client.get(reverse('home'))
        self.assertTrue(response.context['selected_liked'])
        self.assertIsNone(response.context['selected_album'])

    def test_picking_a_playlist_replaces_liked_songs(self):
        self.client.get(reverse('home_liked_tracks'))
        self.client.get(reverse('home_playlist_tracks', args=[self.playlist.pk]))
        response = self.client.get(reverse('home'))
        self.assertFalse(response.context['selected_liked'])
        self.assertEqual(response.context['selected_playlist'], self.playlist)


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
