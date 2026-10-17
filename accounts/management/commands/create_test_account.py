"""Makes (or resets) a ready-to-use account for people who are only testing the site, so they don't have to register.

    python manage.py create_test_account

It is an ordinary account: not staff, not a superuser, so it cannot open the Django admin. Running it again is
harmless; it just sets the password back. Because the login is public knowledge, delete the account
(python manage.py create_test_account --delete) when the testing is over.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

USERNAME = 'admin'
PASSWORD = 'admin123'


class Command(BaseCommand):
    help = 'Create the shared test account (username "admin") so testers can log in without registering.'

    def add_arguments(self, parser):
        parser.add_argument('--delete', action='store_true', help='remove the test account instead')

    def handle(self, *args, **options):
        User = get_user_model()
        if options['delete']:
            deleted, _ = User.objects.filter(username=USERNAME, is_staff=False, is_superuser=False).delete()
            self.stdout.write('Test account removed.' if deleted else 'No test account to remove.')
            return

        user, created = User.objects.get_or_create(username=USERNAME)
        if user.is_staff or user.is_superuser:
            self.stderr.write(f'"{USERNAME}" already exists as a staff/superuser account, so it was left alone.')
            return
        user.set_password(PASSWORD)
        user.save()
        self.stdout.write(f'Test account {"created" if created else "reset"}: username "{USERNAME}", password "{PASSWORD}".')
