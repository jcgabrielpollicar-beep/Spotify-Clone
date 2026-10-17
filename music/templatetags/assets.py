import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def asset(path):
    """Like {% static %}, but adds ?v=<file modified time> to the URL.

    The dev server sends no cache rules for static files, so a browser may keep using an old CSS or JS
    file for hours after it changed (new page, old script = things silently stop working). With the
    modified time in the URL, the browser downloads the file again as soon as it changes.
    """
    url = static(path)
    found = finders.find(path)
    if isinstance(found, (list, tuple)):
        found = found[0] if found else None
    if found:
        try:
            url += f'?v={int(os.path.getmtime(found))}'
        except OSError:
            pass
    return url
