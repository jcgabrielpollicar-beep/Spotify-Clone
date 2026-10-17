from django.conf import settings
from django.db import models

from music.models import AccentColorMixin


class Profile(AccentColorMixin):
    """What a person shows about themselves on their profile page: a name, a short bio and a photo.

    Created the first time it is needed (see `for_user`), so existing accounts need nothing done. The page takes
    its colour from the photo (AccentColorMixin works that out, same as album covers).
    """
    accent_source = 'avatar'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    display_name = models.CharField(max_length=60, blank=True, help_text='Shown instead of your username. Optional.')
    bio = models.TextField(max_length=300, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True)

    def __str__(self):
        return f'Profile of {self.user}'

    @classmethod
    def for_user(cls, user):
        profile, _ = cls.objects.get_or_create(user=user)
        return profile

    @property
    def name(self):
        return self.display_name.strip() or self.user.get_username()

    @property
    def initial(self):
        return self.name[:1].upper()
