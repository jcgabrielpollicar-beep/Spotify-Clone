import re

from django.db import migrations

# bios filled in from Wikipedia used to end with "\n\nSource: Wikipedia (<url>), CC BY-SA 4.0."
CREDIT = re.compile(r'\s*\n\s*Source: Wikipedia \((https?://\S+?)\), CC BY-SA 4\.0\.?\s*$')


def credit_to_its_own_field(apps, schema_editor):
    Artist = apps.get_model('music', 'Artist')
    for artist in Artist.objects.filter(bio__contains='Source: Wikipedia'):
        match = CREDIT.search(artist.bio)
        if match:
            artist.bio_source = match.group(1)
            artist.bio = artist.bio[:match.start()].rstrip()
            artist.save(update_fields=['bio', 'bio_source'])


def credit_back_into_the_bio(apps, schema_editor):
    Artist = apps.get_model('music', 'Artist')
    for artist in Artist.objects.exclude(bio_source=''):
        artist.bio = f'{artist.bio}\n\nSource: Wikipedia ({artist.bio_source}), CC BY-SA 4.0.'
        artist.bio_source = ''
        artist.save(update_fields=['bio', 'bio_source'])


class Migration(migrations.Migration):

    dependencies = [
        ('music', '0006_artist_bio_source'),
    ]

    operations = [
        migrations.RunPython(credit_to_its_own_field, credit_back_into_the_bio),
    ]
