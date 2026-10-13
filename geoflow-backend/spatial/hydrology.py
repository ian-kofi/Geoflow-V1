"""Terrain hydrology from a DEM: depression filling, D8 flow, flow accumulation,
stream extraction and HAND (Height Above Nearest Drainage).

HAND is the height of each cell above the river cell it drains into. Cells a
few metres above their river are the ones that flood first, which makes HAND
the standard terrain predictor for flood susceptibility (Rennó et al. 2008;
Nobre et al. 2011). Pure numpy/scipy, no hydrology library needed.
"""
import heapq
import math

import numpy as np
from scipy import ndimage

from .common import InputError

# D8 neighbour offsets (row, col)
OFFSETS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
MAX_CELLS = 12_000_000


def fill_depressions(dem):
    """Priority-flood depression filling with an epsilon gradient (Barnes et al. 2014).

    Every cell gets a strictly downhill path to the map edge (or a no-data hole),
    so water never gets stuck in pits or on perfectly flat ground.
    """
    height, width = dem.shape
    z = np.where(np.isfinite(dem), dem, np.nan).astype(np.float64).ravel()
    valid = np.isfinite(z)
    closed = ~valid
    # Seeds: valid cells on the map edge or next to no-data (water can leave there).
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
                z[n] = math.nextafter(elevation, up)   # raise pits/flats just above their spill point
            heapq.heappush(heap, (z[n], n))
    return z.reshape(height, width)


def flow_directions(filled, dx, dy):
    """D8: index of the steepest downhill neighbour for every cell (-1 = drains off the map)."""
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
    """Number of cells draining through each cell (including itself)."""
    accumulation = np.where(np.isfinite(filled.ravel()), 1.0, 0.0)
    order = np.argsort(filled.ravel(), kind="stable")[::-1]   # highest first: upstream before downstream
    order = order[np.isfinite(filled.ravel()[order])]
    targets = downstream[order]
    for cell, target in zip(order.tolist(), targets.tolist()):
        if target >= 0:
            accumulation[target] += accumulation[cell]
    return accumulation.reshape(filled.shape)


BURN_DEPTH_M = 10.0


def height_above_drainage(dem, dx, dy, min_area_km2=1.0, rivers=None, derive_streams=True):
    """Returns (hand, streams, details). `dem` is a 2-D array in metres on a projected grid.

    `rivers` is an optional boolean mask of known river cells (e.g. mapped rivers). Rivers
    worked out from the DEM alone miss big rivers whose catchment lies mostly outside the
    area (York's Ouse drains ~3,300 km² upstream), so known rivers are added to them: they
    are carved into the DEM ("stream burning") so flow reaches them, and HAND is measured
    on the uncarved ground. With `derive_streams` False only the known rivers count.
    """
    if dem.size > MAX_CELLS:
        raise InputError(f"The DEM is too large for hydrology ({dem.size:,} cells). Cut it to a smaller outline first.")
    if not np.isfinite(dem).any():
        raise InputError("The DEM has no valid heights.")

    valid = np.isfinite(dem)
    mapped = rivers & valid if rivers is not None else np.zeros(dem.shape, dtype=bool)
    filled = fill_depressions(dem)                           # true ground, for measuring heights
    routed = fill_depressions(np.where(mapped, dem - BURN_DEPTH_M, dem)) if mapped.any() else filled
    downstream = flow_directions(routed, dx, dy)
    accumulation = flow_accumulation(routed, downstream)

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

    # Follow every flow path down to its first river cell by pointer jumping:
    # each step doubles the distance followed, so long paths take ~log2(n) steps.
    index = np.arange(filled.size)
    target = np.where(streams.ravel() | (downstream < 0), index, downstream)
    for _ in range(64):
        jumped = target[target]
        if np.array_equal(jumped, target):
            break
        target = jumped

    flat = filled.ravel()
    reached_river = streams.ravel()[target]
    # Cells whose water leaves the map before meeting a river are measured from where it leaves.
    hand = np.clip((flat - flat[target]).reshape(dem.shape), 0, None)
    hand[~np.isfinite(dem)] = np.nan
    details = {
        "Rivers": river_note,
        "Measured from the map edge": (f"{100 * float(np.mean(~reached_river[np.isfinite(flat)])):.1f}% of cells "
                                       "(their water leaves the area before reaching a river)"),
    }
    return hand.astype(np.float32), streams, details
