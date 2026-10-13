"""Shared plot helpers.

Uses matplotlib's object-oriented Figure API instead of pyplot: pyplot keeps
global state and is not thread-safe, and FastAPI runs several nodes in
parallel worker threads.
"""
import os
import time

from matplotlib.figure import Figure

BACKGROUND = "#0b0f1a"

# One palette shared by layer previews, the compositor and the frontend map.
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
    """Creates a figure whose aspect ratio matches the data extent."""
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
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", pad_inches=0.1,
                facecolor="none" if transparent else fig.get_facecolor(),
                transparent=transparent, format=fmt)


def plot_tolerance(total_bounds, pixels=3000):
    """Simplification tolerance (in data units) that is invisible at the output size."""
    minx, miny, maxx, maxy = total_bounds
    return max(maxx - minx, maxy - miny) / pixels


def is_fresh(output_path, source_path):
    """True if output exists and is newer than its source (so it can be reused)."""
    return (os.path.exists(output_path) and os.path.exists(source_path)
            and os.path.getmtime(output_path) >= os.path.getmtime(source_path))


def atomic_write_bytes(path, content):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{time.time_ns()}.part"
    with open(tmp, "wb") as f:
        f.write(content)
    os.replace(tmp, path)
