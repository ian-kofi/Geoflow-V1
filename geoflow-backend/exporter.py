"""Finished-map JPEG export: title, the map picture, north arrow, scale bar and colour key."""
import io
import math
from datetime import date

from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

PAGE = (255, 255, 255)
TEXT = (30, 30, 30)
MUTED = (110, 110, 110)
MARGIN = 48
MAX_MAP_WIDTH = 2000
MIN_PAGE_WIDTH = 1000


def _font(size, bold=False):
    path = font_manager.findfont(font_manager.FontProperties(family="DejaVu Sans", weight="bold" if bold else "normal"))
    return ImageFont.truetype(path, size)


def _hex(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _fmt(value):
    if value is None:
        return "–"
    magnitude = abs(value)
    if magnitude != 0 and (magnitude < 0.01 or magnitude >= 100000):
        return f"{value:.1e}"
    return f"{value:,.2f}".rstrip("0").rstrip(".") if magnitude < 100 else f"{value:,.0f}"


def _nice_distance(max_km):
    """Largest 1/2/5×10ⁿ distance that fits."""
    exponent = math.floor(math.log10(max_km))
    for step in (5, 2, 1):
        if step * 10 ** exponent <= max_km:
            return step * 10 ** exponent
    return 10 ** exponent


def _text_width(draw, text, font):
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _legend_height(legend):
    if not legend or legend.get("type") == "rgb":
        return 0
    if legend.get("type") == "categorical":
        return 34 + 30 * len(legend.get("classes", []))
    return 90


def _draw_legend(draw, legend, x, y, width):
    title_font, font = _font(20, bold=True), _font(18)
    unit = f" {legend.get('unit')}" if legend.get("unit") else ""
    if legend.get("label"):
        draw.text((x, y), str(legend["label"]), font=title_font, fill=TEXT)
    y += 32
    if legend.get("type") == "categorical":
        for cat in legend.get("classes", []):
            draw.rectangle([x, y + 2, x + 22, y + 22], fill=_hex(cat["color"]), outline=(180, 180, 180))
            share = f"   {cat['percent']}% of area" if cat.get("percent") is not None else ""
            draw.text((x + 34, y), f"{cat['label']}{share}", font=font, fill=TEXT)
            y += 30
        return
    colours = [_hex(c) for c in legend.get("colors", [])] or [(0, 0, 0), (255, 255, 255)]
    bar_w, bar_h = min(width, 520), 22
    for i in range(bar_w):
        t = i / max(bar_w - 1, 1) * (len(colours) - 1)
        a, b = colours[int(t)], colours[min(int(t) + 1, len(colours) - 1)]
        f = t - int(t)
        draw.line([(x + i, y), (x + i, y + bar_h)], fill=tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3)))
    draw.rectangle([x, y, x + bar_w, y + bar_h], outline=(170, 170, 170))
    low, high = f"{_fmt(legend.get('min'))}{unit}", f"{_fmt(legend.get('max'))}{unit}"
    draw.text((x, y + bar_h + 6), low, font=font, fill=MUTED)
    draw.text((x + bar_w - _text_width(draw, high, font), y + bar_h + 6), high, font=font, fill=MUTED)


def _draw_north_arrow(draw, x, y):
    draw.polygon([(x, y), (x - 14, y + 34), (x, y + 26), (x + 14, y + 34)], fill=TEXT)
    draw.text((x, y + 40), "N", font=_font(18, bold=True), fill=TEXT, anchor="mt")


def _draw_scale_bar(draw, bounds, map_box):
    """bounds = [south, north, west, east] of the picture (Web Mercator image)."""
    south, north, west, east = bounds
    left, top, right, bottom = map_box
    km_per_px = (east - west) * 111.32 * math.cos(math.radians((south + north) / 2)) / max(right - left, 1)
    if km_per_px <= 0:
        return
    distance = _nice_distance(km_per_px * (right - left) * 0.25)
    length = distance / km_per_px
    x, y = left + 16, bottom - 30
    draw.rectangle([x - 8, y - 26, x + length + 8 + 60, y + 14], fill=(255, 255, 255))
    draw.rectangle([x, y, x + length, y + 8], fill=TEXT)
    draw.rectangle([x + length / 2, y, x + length, y + 8], fill=(255, 255, 255), outline=TEXT)
    label = f"{distance:g} km" if distance >= 1 else f"{distance * 1000:g} m"
    draw.text((x, y - 22), label, font=_font(16), fill=TEXT)


def export_jpeg(image_path, title, subtitle="", legend=None, bounds=None, quality=92):
    picture = Image.open(image_path).convert("RGBA")
    if picture.width > MAX_MAP_WIDTH:
        picture = picture.resize((MAX_MAP_WIDTH, round(picture.height * MAX_MAP_WIDTH / picture.width)), Image.LANCZOS)
    flattened = Image.new("RGBA", picture.size, PAGE + (255,))
    flattened.alpha_composite(picture)

    width = max(picture.width + 2 * MARGIN, MIN_PAGE_WIDTH)
    title_font, sub_font, foot_font = _font(40, bold=True), _font(22), _font(16)
    header = MARGIN + 52 + (34 if subtitle else 0) + 20
    legend_h = _legend_height(legend)
    height = header + picture.height + 24 + (legend_h + 16 if legend_h else 0) + 40 + MARGIN

    page = Image.new("RGB", (width, height), PAGE)
    draw = ImageDraw.Draw(page)
    draw.text((MARGIN, MARGIN), title, font=title_font, fill=TEXT)
    if subtitle:
        draw.text((MARGIN, MARGIN + 54), subtitle, font=sub_font, fill=MUTED)

    map_x = (width - picture.width) // 2
    page.paste(flattened.convert("RGB"), (map_x, header))
    map_box = (map_x, header, map_x + picture.width, header + picture.height)
    draw.rectangle([map_box[0] - 1, map_box[1] - 1, map_box[2], map_box[3]], outline=(200, 200, 200))
    _draw_north_arrow(draw, map_box[2] - 34, map_box[1] + 14)
    if bounds and len(bounds) == 4:
        _draw_scale_bar(draw, [float(v) for v in bounds], map_box)

    y = map_box[3] + 24
    if legend_h:
        _draw_legend(draw, legend, MARGIN, y, width - 2 * MARGIN)
        y += legend_h + 16
    footer = f"Made with GeoFlow · {date.today():%d %B %Y}"
    draw.text((MARGIN, y + 8), footer, font=foot_font, fill=MUTED)

    buffer = io.BytesIO()
    page.save(buffer, "JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
