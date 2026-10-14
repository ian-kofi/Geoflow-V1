"""Helpers for drawing preview pictures with matplotlib, plus a couple of small file helpers.

We create Figure objects directly instead of using pyplot. pyplot keeps one shared drawing
state for the whole program, and since the server runs several nodes at once in different
threads, they would draw over each other.
"""
import os
import time

from matplotlib.figure import Figure

BACKGROUND = "#0b0f1a"   # dark navy behind the previews

# Colours for each kind of map feature. The same colours are used in the previews, in
# Combine Layers and on the map in the browser (geoflow-project/src/config.js).
LAYER_COLORS = {
    "roads": "#facc15",
    "highways": "#f97316",
    "railways": "#3baaff",
    "waterways": "#22c55e",
    "rivers": "#0284c7",
    "buildings": "#ef4444",
    "default": "#ffffff",
}
BOUNDARY_EDGE = "#aa3bff"
BOUNDARY_FILL = "#1a2547"


def new_map_figure(total_bounds, longest_side_in=10, facecolor=BACKGROUND, transparent=False):
    """A blank figure the same shape as the area, with no axes or margins.

    total_bounds is (min x, min y, max x, max y). The longest side is `longest_side_in` inches.
    """
    minx, miny, maxx, maxy = total_bounds
    w, h = max(maxx - minx, 1e-9), max(maxy - miny, 1e-9)
    if w >= h:
        size = (longest_side_in, max(2.0, longest_side_in * h / w))
    else:
        size = (max(2.0, longest_side_in * w / h), longest_side_in)
    fig = Figure(figsize=size)
    ax = fig.add_axes([0, 0, 1, 1])
    if not transparent:
        fig.patch.set_facecolor(facecolor)
        ax.set_facecolor(facecolor)
    ax.set_axis_off()
    ax.set_aspect("equal")
    return fig, ax


def save_figure(fig, output_path, dpi=150, transparent=False, fmt=None):
    """Saves the figure, trimmed close to the drawing."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", pad_inches=0.1,
                facecolor="none" if transparent else fig.get_facecolor(),
                transparent=transparent, format=fmt)


def plot_tolerance(total_bounds, pixels=3000):
    """How much shapes can be simplified before drawing without it showing in the picture.

    Simplifying first makes detailed borders much quicker to draw.
    """
    minx, miny, maxx, maxy = total_bounds
    return max(maxx - minx, maxy - miny) / pixels


def is_fresh(output_path, source_path):
    """True if the output exists and is newer than the file it was made from, so it can be reused."""
    return (os.path.exists(output_path) and os.path.exists(source_path)
            and os.path.getmtime(output_path) >= os.path.getmtime(source_path))


def atomic_write_bytes(path, content):
    """Writes a file in one go: to a temporary name first, then renamed.

    If two requests write the same file at once, or the server stops halfway, nobody ever
    reads a half written file.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{time.time_ns()}.part"
    with open(tmp, "wb") as f:
        f.write(content)
    os.replace(tmp, path)
