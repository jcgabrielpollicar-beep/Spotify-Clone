from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def playlist_has(context, track, playlist):
    """True when `playlist` already holds `track` (the page's view put the (track, playlist) pairs in the context)."""
    return (track.pk, playlist.pk) in context.get('playlist_pairs', ())
