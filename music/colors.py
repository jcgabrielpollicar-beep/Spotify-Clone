"""Pick a page colour from a cover image (used for the gradient on album and artist pages).

dominant_color() looks at a small copy of the picture, finds the most prominent *vivid* colour (ignoring
near-black, near-white and grey pixels, which would give muddy results) and tones it so white text stays
readable on top of it. theme_style() turns that colour into the CSS variables the templates use.
"""
import colorsys
import re

from PIL import Image

HEX = re.compile(r'#[0-9a-f]{6}')
MAX_LUMINANCE = 0.20          # keeps white text readable on the colour (contrast about 4.5:1 or better)


def is_hex(value):
    return bool(value) and bool(HEX.fullmatch(value))


def _channel(value):
    value /= 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = rgb
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def to_hex(rgb):
    return '#%02x%02x%02x' % tuple(int(round(max(0, min(255, c)))) for c in rgb)


def from_hex(value):
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def mix(rgb, other, amount):
    """`amount` (0..1) of `other` blended into `rgb`."""
    return tuple(a * (1 - amount) + b * amount for a, b in zip(rgb, other))


def _tone(rgb):
    """Calm the colour down: not neon, not too light, and dark enough for white text."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    s = min(s, 0.72)
    l = min(max(l, 0.24), 0.42)
    tuned = tuple(c * 255 for c in colorsys.hls_to_rgb(h, l, s))
    while luminance(tuned) > MAX_LUMINANCE:
        tuned = tuple(c * 0.94 for c in tuned)
    return tuned


def dominant_color(file_like):
    """'#rrggbb' for an image file (path or open file), or '' if it can't be read."""
    try:
        with Image.open(file_like) as img:
            small = img.convert('RGB')
            small.thumbnail((64, 64))
            pixels = list(small.getdata())
    except Exception:       # not an image, truncated file, missing file ...: just no colour
        return ''
    if not pixels:
        return ''

    bins = {}               # hue bucket -> [weight, r*w, g*w, b*w]
    for r, g, b in pixels:
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if v < 0.18 or s < 0.18:
            continue        # near-black, near-white or grey
        weight = s * (0.4 + v)          # vivid, reasonably bright pixels count more
        slot = bins.setdefault(int(h * 24) % 24, [0.0, 0.0, 0.0, 0.0])
        slot[0] += weight
        slot[1] += r * weight
        slot[2] += g * weight
        slot[3] += b * weight

    if bins:
        weight, r, g, b = max(bins.values(), key=lambda slot: slot[0])
        base = (r / weight, g / weight, b / weight)
    else:                   # a black-and-white cover: use its average grey
        base = tuple(sum(p[i] for p in pixels) / len(pixels) for i in range(3))
    return to_hex(_tone(base))


def panel_vars(prefix, accent):
    """CSS variables for tinted containers (home page panels): '--artist-panel:#..;--artist-inner:#..;' etc.

    Every shade stays dark so the white text on top of it is always readable; only the tint changes.
    """
    if not is_hex(accent):
        return ''
    rgb = from_hex(accent)
    shades = {
        'panel': mix(rgb, (16, 16, 16), 0.82),        # the container itself
        'inner': mix(rgb, (8, 8, 8), 0.88),           # the track the carousels slide in
        'card': mix(rgb, (24, 24, 24), 0.78),         # cards and list rows
        'lift': mix(rgb, (34, 34, 34), 0.68),         # hovered / active card or row
        'hi': mix(rgb, (255, 255, 255), 0.40),        # outline of the selected card
    }
    return ''.join(f'--{prefix}-{name}:{to_hex(color)};' for name, color in shades.items())


def theme_style(accent):
    """Inline CSS variables for <body style="...">, or '' when there is no colour."""
    if not is_hex(accent):
        return ''
    rgb = from_hex(accent)
    black = (0, 0, 0)
    return f'--accent:{accent};--accent-mid:{to_hex(mix(rgb, black, 0.62))};--accent-page:{to_hex(mix(rgb, black, 0.55))};'
