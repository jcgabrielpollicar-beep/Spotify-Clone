from django.core.management.base import BaseCommand

from music.models import Album, Artist


class Command(BaseCommand):
    help = 'Work out the page colour of every artist photo and album cover (run once after adding the feature, or after replacing images by hand).'

    def handle(self, *args, **options):
        for model, label in ((Artist, 'artist'), (Album, 'album')):
            for obj in model.objects.all():
                color = obj.refresh_accent()
                shown = color or '(no picture / no colour)'
                self.stdout.write(f'{label:7} {str(obj)[:48]:48} {shown}')
        self.stdout.write(self.style.SUCCESS('Done.'))
