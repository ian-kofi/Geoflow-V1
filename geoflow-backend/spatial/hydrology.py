"""Working out how water flows over the ground, for the Height Above River (HAND) node.

The steps, in order:
    1. fill_depressions     fill in hollows so water can always flow downhill to the edge
    2. flow_directions      for each cell, which neighbour its water flows to
    3. flow_accumulation    how many cells drain through each cell
    4. rivers               cells that enough land drains into, plus any mapped rivers
    5. HAND                 how high each cell sits above the river its water reaches

HAND matters for flooding: land a few metres above its river floods first, so it's the
standard terrain measure for flood risk (Rennó et al. 2008, Nobre et al. 2011). Everything
here is plain numpy and scipy, with no hydrology library needed.

Heights are in metres on a grid measured in metres. Cells are numbered row by row, so cell i
is at row i // width and column i % width.
"""
import heapq
import math
import os

import numpy as np
from scipy import ndimage

from .common import InputError

# The eight neighbours of a cell, as (row step, column step). Water can flow to any of them,
# which is why this is called the "D8" method.
OFFSETS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
# Biggest grid we'll process. Smaller on low memory servers, such as the free demo.
MAX_CELLS = 3_000_000 if os.environ.get("GEOFLOW_LOW_MEMORY") == "1" else 12_000_000


def fill_depressions(dem):
    """Fills hollows in the ground so water from every cell can flow off the map.

    This is the "priority flood" method (Barnes et al. 2014). It works inwards from the edge
    of the map, always handling the lowest cell it has reached so far. Any cell lower than
    the one it was reached from is a hollow, so it's raised to just above that level. Cells are
    raised by the smallest possible amount each time, so even filled flat areas still slope
    very slightly towards the way out and water never gets stuck.

    Cells next to holes in the data count as edges too, since water can leave there.
    """
    height, width = dem.shape
    z = np.where(np.isfinite(dem), dem, np.nan).astype(np.float64).ravel()
    valid = np.isfinite(z)
    closed = ~valid
    # Start from the cells where water can leave: the map edge and the edges of any holes.
    grid_valid = valid.reshape(height, width)
    edge = np.zeros((height, width), dtype=bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    near_nodata = ndimage.binary_dilation(~grid_valid, structure=np.ones((3, 3), dtype=bool))
    seeds = np.flatnonzero((grid_valid & (edge | near_nodata)).ravel())

    heap = [(z[i], i) for i in seeds]
    heapq.heapify(heap)
    closed[seeds] = True
    offsets = [(dr * width + dc, dr, dc) for dr, dc in OFFSETS]
    up = math.inf
    while heap:
        elevation, i = heapq.heappop(heap)
        r, c = divmod(i, width)
        for delta, dr, dc in offsets:
            rr, cc = r + dr, c + dc
            if rr < 0 or rr >= height or cc < 0 or cc >= width:
                continue
            n = i + delta
            if closed[n]:
                continue
            closed[n] = True
            if z[n] <= elevation:
                z[n] = math.nextafter(elevation, up)   # raise it a hair above the level water would spill from
            heapq.heappush(heap, (z[n], n))
    return z.reshape(height, width)


def flow_directions(filled, dx, dy):
    """For every cell, the number of the neighbour its water flows to: the steepest way downhill.

    dx and dy are the cell width and height in metres, needed because diagonal neighbours are
    further away. A value of -1 means the water flows off the map from that cell.
    """
    height, width = filled.shape
    padded = np.pad(filled, 1, constant_values=np.nan)
    best_drop = np.zeros_like(filled)
    target = np.full(filled.shape, -1, dtype=np.int64)
    rows, cols = np.indices(filled.shape)
    flat_index = rows * width + cols
    diagonal = math.hypot(np.mean(dx), dy)
    for dr, dc in OFFSETS:
        neighbour = padded[1 + dr:1 + dr + height, 1 + dc:1 + dc + width]
        distance = diagonal if dr and dc else (dy if dr else np.mean(dx))
        with np.errstate(invalid="ignore"):
            drop = (filled - neighbour) / distance
        better = np.isfinite(drop) & (drop > best_drop)
        best_drop = np.where(better, drop, best_drop)
        target = np.where(better, flat_index + dr * width + dc, target)
    target[~np.isfinite(filled)] = -1
    return target.ravel()


def flow_accumulation(filled, downstream):
    """How many cells drain through each cell, counting itself. Big numbers mean a river.

    Cells are visited from highest to lowest, so every cell has collected everything from
    upstream before it passes its total on downhill.
    """
    accumulation = np.where(np.isfinite(filled.ravel()), 1.0, 0.0)
    order = np.argsort(filled.ravel(), kind="stable")[::-1]
    order = order[np.isfinite(filled.ravel()[order])]
    targets = downstream[order]
    for cell, target in zip(order.tolist(), targets.tolist()):
        if target >= 0:
            accumulation[target] += accumulation[cell]
    return accumulation.reshape(filled.shape)


BURN_DEPTH_M = 10.0   # how deep mapped rivers are cut into the ground so water finds them


def height_above_drainage(dem, dx, dy, min_area_km2=1.0, rivers=None, derive_streams=True):
    """Works out HAND: how many metres each cell sits above the river its water flows into.

    dem             2D grid of heights in metres
    dx, dy          cell width and height in metres
    min_area_km2    a cell counts as a river once at least this much land drains through it
    rivers          optional True and False grid of known river cells, such as rivers from
                    OpenStreetMap
    derive_streams  if False, only the known rivers count

    Why known rivers help: rivers traced from the heights alone can only see the land inside
    the map. York's River Ouse drains about 3,300 km², nearly all of it upstream outside the
    city, so inside the city it looks like a small stream. Mapped rivers are cut into the ground
    (called "stream burning") so the flow finds them, and heights are still measured on the
    ground as it really is.

    Returns the HAND grid, the river cells, and a few notes for the node's details panel.
    """
    if dem.size > MAX_CELLS:
        raise InputError(f"The DEM is too large for hydrology ({dem.size:,} cells). Cut it to a smaller outline first.")
    if not np.isfinite(dem).any():
        raise InputError("The DEM has no valid heights.")

    valid = np.isfinite(dem)
    mapped = rivers & valid if rivers is not None else np.zeros(dem.shape, dtype=bool)
    filled = fill_depressions(dem)                           # the real ground, for measuring heights
    # The ground with mapped rivers cut in, used only to work out where water flows
    routed = fill_depressions(np.where(mapped, dem - BURN_DEPTH_M, dem)) if mapped.any() else filled
    downstream = flow_directions(routed, dx, dy)
    accumulation = flow_accumulation(routed, downstream)

    # Turn the river size from km² into a number of cells
    cell_km2 = float(np.mean(dx) * dy) / 1e6
    threshold_cells = max(min_area_km2 / cell_km2, 10)
    derive_streams = derive_streams or not mapped.any()
    streams = ((accumulation >= threshold_cells) & valid) | mapped if derive_streams else mapped
    if not streams.any():
        raise InputError(f"No rivers draining at least {min_area_km2:g} km² inside this area. "
                         "Lower 'Smallest river' or use a larger outline.")
    notes = [f"draining ≥ {min_area_km2:g} km²"] if derive_streams else []
    if mapped.any():
        notes.append("the connected river map, carved into the terrain")
    river_note = " plus ".join(notes).capitalize() + f" ({int(streams.sum()):,} river cells)"
    if rivers is not None and not mapped.any():
        river_note += "; the connected rivers don't cross this area"

    # Find the river cell each cell drains into. Following every path one step at a time would
    # be slow, so instead each cell repeatedly jumps to wherever its target points. Every round
    # doubles how far along the path we've got, so even very long paths take only a few dozen
    # rounds. River cells and cells at the map edge point to themselves, so they stay put.
    index = np.arange(filled.size)
    target = np.where(streams.ravel() | (downstream < 0), index, downstream)
    for _ in range(64):
        jumped = target[target]
        if np.array_equal(jumped, target):
            break
        target = jumped

    flat = filled.ravel()
    reached_river = streams.ravel()[target]
    # If a cell's water leaves the map before reaching a river, its height is measured from
    # the point where the water leaves.
    hand = np.clip((flat - flat[target]).reshape(dem.shape), 0, None)
    hand[~np.isfinite(dem)] = np.nan
    details = {
        "Rivers": river_note,
        "Measured from the map edge": (f"{100 * float(np.mean(~reached_river[np.isfinite(flat)])):.1f}% of cells "
                                       "(their water leaves the area before reaching a river)"),
    }
    return hand.astype(np.float32), streams, details
