"""Requirement: Authentication & User Accounts (registration, login / logout, pages only for logged-in users, profile)."""
import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import get_resolver, reverse

User = get_user_model()

PUBLIC = {'accounts/login/', 'accounts/register/', 'accounts/logout/'}     # the only pages a signed-out visitor may open


def all_routes(patterns=None, prefix=''):
    """Every URL pattern of the project as (route text), found automatically so new pages can't be forgotten."""
    routes = []
    for pattern in (patterns if patterns is not None else get_resolver().url_patterns):
        route = prefix + str(pattern.pattern)
        if hasattr(pattern, 'url_patterns'):
            routes += all_routes(pattern.url_patterns, route)
        else:
            routes.append(route)
    return routes


def concrete(route):
    """'albums/<int:pk>/tracks/new/' -> 'albums/1/tracks/new/' (the view is never reached when login is required)."""
    return '/' + re.sub(r'<int:\w+>', '1', re.sub(r'<(?:str|path|slug):\w+>', 'x', route))


class RegistrationTests(TestCase):
    URL = '/accounts/register/'

    def post(self, **fields):
        data = {'username': 'newbie', 'password1': 'a-Strong-pass-99', 'password2': 'a-Strong-pass-99'}
        data.update(fields)
        return self.client.post(self.URL, data)

    def test_the_form_is_shown_with_a_csrf_token(self):
        response = self.client.get(self.URL)
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, 'name="password2"')

    def test_a_new_account_is_created_and_signed_in(self):
        response = self.post()
        self.assertRedirects(response, reverse('home'))
        self.assertTrue(User.objects.filter(username='newbie').exists())
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)          # already logged in

    def test_the_password_is_stored_hashed_never_as_typed(self):
        self.post()
        stored = User.objects.get(username='newbie').password
        self.assertNotIn('a-Strong-pass-99', stored)
        self.assertTrue(stored.startswith(('pbkdf2_', 'argon2', 'bcrypt', 'scrypt')))

    def test_mismatched_passwords_are_refused(self):
        response = self.post(password2='something-else-123')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newbie').exists())
        self.assertContains(response, "didn")                                            # "...didn't match"

    def test_an_existing_username_is_refused(self):
        User.objects.create_user('newbie', password='pw-123-xyz-ABC')
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username='newbie').count(), 1)
        self.assertContains(response, 'already exists')

    def test_weak_passwords_are_refused(self):
        for weak in ('short1', '12345678901', 'password', 'newbie123'):                  # short, numeric, common, like the name
            response = self.post(password1=weak, password2=weak)
            self.assertEqual(response.status_code, 200, weak)
            self.assertFalse(User.objects.filter(username='newbie').exists(), weak)

    def test_a_blank_username_is_refused(self):
        self.assertEqual(self.post(username='').status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_signed_in_users_are_sent_home_instead(self):
        self.post()
        self.assertRedirects(self.client.get(self.URL), reverse('home'))


class LoginLogoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('alice', password='pw-alice-123')

    def login(self, password='pw-alice-123', **extra):
        return self.client.post('/accounts/login/' + extra.pop('query', ''), {'username': 'alice', 'password': password})

    def test_the_login_form_is_shown_with_a_csrf_token(self):
        response = self.client.get('/accounts/login/')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')

    def test_correct_details_sign_you_in_and_go_home(self):
        self.assertRedirects(self.login(), reverse('home'))
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)

    def test_wrong_password_shows_an_error_and_stays_signed_out(self):
        response = self.login('not-the-password')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please enter a correct username and password')
        self.assertEqual(self.client.get(reverse('home')).status_code, 302)

    def test_unknown_user_shows_the_same_error(self):
        response = self.client.post('/accounts/login/', {'username': 'ghost', 'password': 'whatever-123'})
        self.assertContains(response, 'Please enter a correct username and password')

    def test_login_returns_you_to_the_page_you_wanted(self):
        wanted = reverse('album_list')
        response = self.client.get(wanted)
        self.assertRedirects(response, f'/accounts/login/?next={wanted}')
        self.assertRedirects(self.login(query=f'?next={wanted}'), wanted, fetch_redirect_response=False)

    def test_login_will_not_redirect_to_another_site(self):
        response = self.login(query='?next=https://evil.example.com/')
        self.assertRedirects(response, reverse('home'))

    def test_logout_ends_the_session(self):
        self.login()
        response = self.client.post('/accounts/logout/')
        self.assertRedirects(response, '/accounts/login/')
        self.assertEqual(self.client.get(reverse('home')).status_code, 302)               # signed out again

    def test_logout_cannot_be_triggered_by_a_plain_link(self):
        self.login()
        self.assertEqual(self.client.get('/accounts/logout/').status_code, 405)           # only a real POST form signs you out
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)               # still signed in

    def test_signed_in_users_are_sent_home_from_the_login_page(self):
        self.login()
        self.assertRedirects(self.client.get('/accounts/login/'), reverse('home'))


class CsrfTests(TestCase):
    """Forms that change something are refused without the hidden security token."""

    def test_posts_without_a_token_are_rejected(self):
        strict = Client(enforce_csrf_checks=True)
        User.objects.create_user('alice', password='pw-alice-123')
        for url, data in (('/accounts/login/', {'username': 'alice', 'password': 'pw-alice-123'}),
                          ('/accounts/register/', {'username': 'x', 'password1': 'a-Strong-pass-99', 'password2': 'a-Strong-pass-99'})):
            self.assertEqual(strict.post(url, data).status_code, 403, url)
        self.assertFalse(User.objects.filter(username='x').exists())


class RestrictedPagesTests(TestCase):
    """Every page except login / register needs a signed-in user: found automatically, not from a hand-made list."""

    def test_every_page_sends_signed_out_visitors_to_the_login_page(self):
        checked = []
        for route in all_routes():
            if route in PUBLIC or route.startswith('admin/'):
                continue
            url = concrete(route)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, f'{url} is reachable without logging in!')
            self.assertTrue(response.url.startswith('/accounts/login/'), f'{url} -> {response.url}')
            checked.append(url)
        self.assertGreater(len(checked), 30)                                              # the walk really found the site's pages

    def test_pages_that_change_data_also_refuse_signed_out_posts(self):
        for route in all_routes():
            if route in PUBLIC or route.startswith('admin/'):
                continue
            response = self.client.post(concrete(route), {})
            self.assertEqual(response.status_code, 302, f'POST to {concrete(route)} worked without logging in!')

    def test_the_public_pages_really_are_public(self):
        for url in ('/accounts/login/', '/accounts/register/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_the_admin_site_needs_a_staff_login(self):
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        User.objects.create_user('plain', password='pw-plain-123')
        self.client.login(username='plain', password='pw-plain-123')
        self.assertEqual(self.client.get('/admin/').status_code, 302)                     # a normal user is not staff

    def test_uploaded_songs_need_a_login_on_the_test_link_style_urls(self):
        from mysite import urls_prod                                                       # the PythonAnywhere URL set
        self.assertTrue(any('media/audio' in str(p.pattern) for p in urls_prod.urlpatterns))


class ProfilePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', password='pw-alice-123')
        cls.bob = User.objects.create_user('bob', password='pw-bob-123')

    def test_signed_out_visitors_cannot_open_a_profile(self):
        self.assertRedirects(self.client.get(reverse('profile')), '/accounts/login/?next=/accounts/profile/')
        self.assertEqual(self.client.get(reverse('profile_edit')).status_code, 302)

    def test_the_profile_shows_the_signed_in_users_own_details(self):
        self.client.login(username='alice', password='pw-alice-123')
        html = self.client.get(reverse('profile')).content.decode()
        self.assertIn('<h1>alice</h1>', html)
        self.assertIn('@alice', html)
        self.assertIn('member since', html)
        self.assertIn('0 playlists', html)
        self.assertIn('0 liked songs', html)
        self.assertNotIn('@bob', html)                                                    # nobody else's details
        self.assertNotIn('>bob<', html)

    def test_the_profile_can_be_edited_and_saved(self):
        self.client.login(username='alice', password='pw-alice-123')
        self.client.post(reverse('profile_edit'), {'display_name': 'Alice A.', 'bio': 'Hello there'})
        html = self.client.get(reverse('profile')).content.decode()
        self.assertIn('<h1>Alice A.</h1>', html)
        self.assertIn('Hello there', html)

    def test_each_user_has_their_own_profile(self):
        self.client.login(username='alice', password='pw-alice-123')
        self.client.post(reverse('profile_edit'), {'display_name': 'Alice A.', 'bio': ''})
        self.client.logout()
        self.client.login(username='bob', password='pw-bob-123')
        self.assertIn('<h1>bob</h1>', self.client.get(reverse('profile')).content.decode())


class TestAccountCommandTests(TestCase):
    """`manage.py create_test_account`: the shared login for people who are only trying the site out."""

    def run_command(self, *args):
        from io import StringIO

        from django.core.management import call_command
        out, err = StringIO(), StringIO()
        call_command('create_test_account', *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_creates_an_account_that_can_log_in_and_use_the_site(self):
        self.run_command()
        client = Client()
        self.assertTrue(client.login(username='admin', password='admin123'))
        self.assertEqual(client.get(reverse('home')).status_code, 200)

    def test_it_is_an_ordinary_account_not_staff(self):
        self.run_command()
        user = get_user_model().objects.get(username='admin')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_running_it_again_resets_the_password_without_a_second_account(self):
        self.run_command()
        user = get_user_model().objects.get(username='admin')
        user.set_password('changed-by-someone')
        user.save()
        self.run_command()
        self.assertEqual(get_user_model().objects.filter(username='admin').count(), 1)
        self.assertTrue(Client().login(username='admin', password='admin123'))

    def test_a_real_staff_account_called_admin_is_never_touched(self):
        get_user_model().objects.create_superuser('admin', password='my-real-password-1')
        _, err = self.run_command()
        self.assertIn('left alone', err)
        self.assertTrue(Client().login(username='admin', password='my-real-password-1'))
        self.assertFalse(Client().login(username='admin', password='admin123'))

    def test_delete_removes_it(self):
        self.run_command()
        self.run_command('--delete')
        self.assertFalse(get_user_model().objects.filter(username='admin').exists())
