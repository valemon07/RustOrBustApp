"""
Stage 4: Density Calculation

Converts confirmed pit measurements from Stage 3 into three density
metrics and a spatial zone analysis.

Inputs
------
confirmed_pits  : list[dict] from Stage 3
roi_dims        : dict from Stage 2  (width_px, height_px, width_um, height_um)
specimen_mask   : uint8 ndarray from Stage 2 (255 = inside hull)
scale_um_per_px : float from Stage 1
image_input     : original image path or BGR array (for debug visualisation)

Metrics
-------
Metric 1 — Linear density (pits/cm):
    pit_count / (ROI_width_um / 10_000)
    Matches the client's reported format from the slide deck.

Metric 2 — Areal density (pits/mm²):
    pit_count / (ROI_area_um2 / 1_000_000)

Metric 3 — Coverage fraction (%):
    sum(pit_area_px) / specimen_mask_nonzero_px  * 100

All three metrics are computed twice:
    macro tier  : pit_tier == "macro" (area ≥ 1500 µm²)  — matches GT counts
    full set    : all confirmed pits regardless of tier    — complete record

Within each tier, metrics are also broken down by pit_type (surface / edge).

# DOMAIN THRESHOLD — DO NOT CHANGE WITHOUT CLIENT APPROVAL
# 1500 µm² minimum derived from calibration against human
# expert pit counts from UVA CESE slide deck (02/13/2026).
# Corresponds to ~44 µm diameter macro-pit — the scale at
# which a trained analyst manually counts corrosion pits.
# Micro-pit tier (below 1500 µm²) is preserved in output
# but excluded from ground-truth-comparable density metrics.
# Calibration table saved in: tests/calibrate_stage3_threshold.py

Spatial analysis
----------------
The specimen bounding box is divided into a 5×5 grid.
Each confirmed pit is assigned to a zone by centroid.
The grid counts are returned as a 5×5 numpy array.
The hotspot zone (row, col) has the highest pit count.
"""

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRID_ROWS = 5
GRID_COLS = 5

# Mirror Stage 2's scale-bar exclusion fractions for debug rendering.
SCALEBAR_X_FRACTION = 0.68
SCALEBAR_Y_FRACTION = 0.80


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_image(image_input):
    if isinstance(image_input, str):
        image = cv2.imread(image_input)
        if image is None:
            raise FileNotFoundError(f"Cannot load image: {image_input}")
        return image
    return image_input.copy()


def _linear_density(pit_count, roi_width_um):
    """Pits per centimetre along the ROI width dimension."""
    if roi_width_um <= 0:
        return 0.0
    return pit_count / (roi_width_um / 10_000.0)


def _areal_density(pit_count, roi_width_um, roi_height_um):
    """Pits per mm² over the ROI bounding-box area."""
    area_um2 = roi_width_um * roi_height_um
    if area_um2 <= 0:
        return 0.0
    return pit_count / (area_um2 / 1_000_000.0)


def _coverage_fraction(pits, specimen_mask):
    """Total pit pixel area as a percentage of the specimen mask area."""
    specimen_px = int(np.count_nonzero(specimen_mask))
    if specimen_px == 0:
        return 0.0
    pit_px = sum(p["area_px"] for p in pits)
    return 100.0 * pit_px / specimen_px


def _build_zone_grid(confirmed_pits, roi_dims):
    """
    Assign each confirmed pit to a cell in a GRID_ROWS×GRID_COLS grid
    based on its centroid within the specimen bounding box.

    The bounding box is taken from roi_dims (width_px, height_px) but we
    need the top-left corner, which we derive from the confirmed pit
    centroids themselves (min x, min y across all pits as a rough origin).
    We use the roi_dims width/height to define cell sizes.

    Returns
    -------
    zone_grid    : ndarray (GRID_ROWS × GRID_COLS) of int counts
    hotspot_zone : (row, col) of highest count
    """
    zone_grid = np.zeros((GRID_ROWS, GRID_COLS), dtype=int)

    if not confirmed_pits:
        return zone_grid, (0, 0)

    all_x = [p["centroid_x_px"] for p in confirmed_pits]
    all_y = [p["centroid_y_px"] for p in confirmed_pits]

    # Use the ROI bounding box dimensions for cell sizing.
    # We anchor at the minimum observed centroid coordinate so the grid
    # always covers the actual pit distribution.
    x_min = min(all_x)
    y_min = min(all_y)
    x_span = roi_dims["width_px"]
    y_span = roi_dims["height_px"]

    cell_w = x_span / GRID_COLS
    cell_h = y_span / GRID_ROWS

    for pit in confirmed_pits:
        # Normalise centroid relative to the ROI top-left anchor.
        rel_x = pit["centroid_x_px"] - x_min
        rel_y = pit["centroid_y_px"] - y_min

        col = int(rel_x / cell_w)
        row = int(rel_y / cell_h)
        # Clamp to grid bounds (edge pits may sit exactly on the boundary).
        col = min(col, GRID_COLS - 1)
        row = min(row, GRID_ROWS - 1)

        zone_grid[row, col] += 1

    hotspot = tuple(int(idx) for idx in np.unravel_index(
        zone_grid.argmax(), zone_grid.shape
    ))
    return zone_grid, hotspot


def _build_debug_vis(image, confirmed_pits, density_metrics,
                     zone_grid, hotspot_zone, roi_dims,
                     scale_um_per_px, specimen_mask):
    """
    Produce the heatmap + pit overlay debug image.

    Overlay layers (bottom to top):
    1. Original image
    2. Semi-transparent heatmap cells (green → yellow → red by density)
    3. Hotspot cell highlighted with a white border
    4. 5×5 white grid lines
    5. Pit centroid dots (green = surface, red = edge)
    6. Summary text
    7. Scale-bar zone blue border
    """
    debug_vis = image.copy()
    img_h, img_w = image.shape[:2]

    # --- Derive grid geometry from ROI bounding box ----------------------
    if confirmed_pits:
        all_x = [p["centroid_x_px"] for p in confirmed_pits]
        all_y = [p["centroid_y_px"] for p in confirmed_pits]
        x0 = min(all_x)
        y0 = min(all_y)
    else:
        x0, y0 = 0, 0

    box_w = roi_dims["width_px"]
    box_h = roi_dims["height_px"]

    cell_w = box_w / GRID_COLS
    cell_h = box_h / GRID_ROWS

    max_count = int(zone_grid.max()) if zone_grid.max() > 0 else 1

    # --- Heatmap cells ---------------------------------------------------
    heatmap_overlay = debug_vis.copy()
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            count = int(zone_grid[row, col])
            cx0 = int(x0 + col * cell_w)
            cy0 = int(y0 + row * cell_h)
            cx1 = int(x0 + (col + 1) * cell_w)
            cy1 = int(y0 + (row + 1) * cell_h)

            # Normalised density 0→1
            t = count / max_count
            # Green (0,200,0) → Yellow (0,200,200) → Red (0,0,200)
            if t <= 0.5:
                g = 200
                r = int(200 * (t * 2))
                b = 0
            else:
                g = int(200 * (1 - (t - 0.5) * 2))
                r = 200
                b = 0
            colour = (b, g, r)

            if count > 0:
                cv2.rectangle(heatmap_overlay, (cx0, cy0), (cx1, cy1),
                              colour, cv2.FILLED)

    # Blend heatmap with original image
    debug_vis = cv2.addWeighted(debug_vis, 0.6, heatmap_overlay, 0.4, 0)

    # --- Grid lines -------------------------------------------------------
    for col in range(GRID_COLS + 1):
        lx = int(x0 + col * cell_w)
        cv2.line(debug_vis, (lx, int(y0)), (lx, int(y0 + box_h)),
                 (255, 255, 255), 1)
    for row in range(GRID_ROWS + 1):
        ly = int(y0 + row * cell_h)
        cv2.line(debug_vis, (int(x0), ly), (int(x0 + box_w), ly),
                 (255, 255, 255), 1)

    # --- Hotspot highlight ------------------------------------------------
    hr, hc = hotspot_zone
    hx0 = int(x0 + hc * cell_w)
    hy0 = int(y0 + hr * cell_h)
    hx1 = int(x0 + (hc + 1) * cell_w)
    hy1 = int(y0 + (hr + 1) * cell_h)
    cv2.rectangle(debug_vis, (hx0, hy0), (hx1, hy1), (255, 255, 255), 2)

    # --- Pit centroid dots -----------------------------------------------
    for pit in confirmed_pits:
        dot_colour = (0, 200, 0) if pit["pit_type"] == "surface" else (0, 0, 220)
        cv2.circle(debug_vis,
                   (pit["centroid_x_px"], pit["centroid_y_px"]),
                   3, dot_colour, -1)

    # --- Summary text ----------------------------------------------------
    dm = density_metrics
    text_lines = [
        f"Macro: {dm['pit_density_macro_per_cm']:.1f} p/cm  "
        f"n={dm['pit_count_macro']}  cov={dm['pit_coverage_macro_pct']:.2f}%",
        f"Full:  {dm['pit_density_all_per_cm']:.1f} p/cm  "
        f"n={dm['pit_count_all']}  cov={dm['pit_coverage_all_pct']:.2f}%",
        f"hotspot=({hotspot_zone[0]},{hotspot_zone[1]})  "
        f"count={int(zone_grid[hotspot_zone])}  "
        f"scale={scale_um_per_px:.4f}um/px",
    ]
    tx, ty = 10, 28
    for line in text_lines:
        cv2.putText(debug_vis, line, (tx + 1, ty + 1),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(debug_vis, line, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        ty += 22

    # --- Scale-bar zone border -------------------------------------------
    sb_y0 = int(img_h * SCALEBAR_Y_FRACTION)
    sb_x0 = int(img_w * SCALEBAR_X_FRACTION)
    cv2.rectangle(debug_vis, (sb_x0, sb_y0), (img_w - 1, img_h - 1),
                  (255, 0, 0), 2)

    return debug_vis


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_density(image_input, confirmed_pits, roi_dims,
                      specimen_mask, scale_um_per_px):
    """
    Compute density metrics and spatial zone analysis for confirmed pits.

    Parameters
    ----------
    image_input : str or numpy.ndarray
        Path to the image file or a BGR numpy array.
    confirmed_pits : list[dict]
        Output from Stage 3.  Each dict must have keys:
        pit_type ("surface"|"edge"), area_px, centroid_x_px, centroid_y_px.
    roi_dims : dict
        Output from Stage 2.  Must contain width_px, height_px,
        width_um, height_um.
    specimen_mask : numpy.ndarray (uint8)
        Filled convex-hull mask from Stage 2.
    scale_um_per_px : float
        Micrometres per pixel from Stage 1.

    Returns
    -------
    density_metrics : dict
        n_confirmed, n_macro, n_micro, n_surface, n_edge,
        Macro tier (ground-truth-comparable):
          pit_count_macro, pit_density_macro_per_cm,
          areal_macro_per_mm2, pit_coverage_macro_pct
        Full set (complete scientific record):
          pit_count_all, pit_density_all_per_cm,
          linear_surface_per_cm, linear_edge_per_cm,
          areal_all_pits_per_mm2, areal_surface_per_mm2, areal_edge_per_mm2,
          pit_coverage_all_pct, coverage_surface_pct, coverage_edge_pct,
        roi_width_um, roi_height_um, roi_area_um2
    zone_grid : numpy.ndarray (GRID_ROWS × GRID_COLS, int)
        Pit counts per spatial zone.
    hotspot_zone : tuple (row, col)
        Zone with the highest pit count.
    debug_vis : numpy.ndarray (BGR)
        Colour-coded diagnostic image.
    """
    image = _load_image(image_input)

    macro_pits   = [p for p in confirmed_pits if p.get("pit_tier") == "macro"]
    surface_pits = [p for p in confirmed_pits if p["pit_type"] == "surface"]
    edge_pits    = [p for p in confirmed_pits if p["pit_type"] == "edge"]

    roi_width_um  = roi_dims["width_um"]
    roi_height_um = roi_dims["height_um"]
    roi_area_um2  = roi_width_um * roi_height_um

    # --- Macro tier metrics (ground-truth-comparable) ----------------------
    linear_macro = _linear_density(len(macro_pits), roi_width_um)
    areal_macro  = _areal_density(len(macro_pits),  roi_width_um, roi_height_um)
    cov_macro    = _coverage_fraction(macro_pits,   specimen_mask)

    # --- Full-set metrics (complete scientific record) ---------------------
    linear_all     = _linear_density(len(confirmed_pits), roi_width_um)
    linear_surface = _linear_density(len(surface_pits),   roi_width_um)
    linear_edge    = _linear_density(len(edge_pits),      roi_width_um)

    areal_all     = _areal_density(len(confirmed_pits), roi_width_um, roi_height_um)
    areal_surface = _areal_density(len(surface_pits),   roi_width_um, roi_height_um)
    areal_edge    = _areal_density(len(edge_pits),      roi_width_um, roi_height_um)

    cov_all     = _coverage_fraction(confirmed_pits, specimen_mask)
    cov_surface = _coverage_fraction(surface_pits,   specimen_mask)
    cov_edge    = _coverage_fraction(edge_pits,      specimen_mask)

    density_metrics = {
        # Counts
        "n_confirmed":              len(confirmed_pits),
        "n_macro":                  len(macro_pits),
        "n_micro":                  len(confirmed_pits) - len(macro_pits),
        "n_surface":                len(surface_pits),
        "n_edge":                   len(edge_pits),
        # Macro tier — use these for ground-truth comparison
        "pit_count_macro":          len(macro_pits),
        "pit_density_macro_per_cm": round(linear_macro,  2),
        "areal_macro_per_mm2":      round(areal_macro,   4),
        "pit_coverage_macro_pct":   round(cov_macro,     4),
        # Full set — complete scientific record
        "pit_count_all":            len(confirmed_pits),
        "pit_density_all_per_cm":   round(linear_all,    2),
        "linear_surface_per_cm":    round(linear_surface, 2),
        "linear_edge_per_cm":       round(linear_edge,   2),
        "areal_all_pits_per_mm2":   round(areal_all,     4),
        "areal_surface_per_mm2":    round(areal_surface, 4),
        "areal_edge_per_mm2":       round(areal_edge,    4),
        "pit_coverage_all_pct":     round(cov_all,       4),
        "coverage_surface_pct":     round(cov_surface,   4),
        "coverage_edge_pct":        round(cov_edge,      4),
        # ROI geometry
        "roi_width_um":             round(roi_width_um,  2),
        "roi_height_um":            round(roi_height_um, 2),
        "roi_area_um2":             round(roi_area_um2,  2),
    }

    # --- Spatial zone analysis ---------------------------------------------
    # Hotspot detection uses macro pits only so it reflects the same scale
    # as the ground-truth density metric.  A reference grid for all pits is
    # built separately but not used for hotspot selection.
    zone_grid, hotspot_zone = _build_zone_grid(macro_pits, roi_dims)
    zone_grid_all, _        = _build_zone_grid(confirmed_pits, roi_dims)

    # Store the all-pits grid in density_metrics for downstream reference.
    density_metrics["zone_grid_all"] = zone_grid_all

    # --- Debug visualisation -----------------------------------------------
    debug_vis = _build_debug_vis(
        image, confirmed_pits, density_metrics,
        zone_grid, hotspot_zone, roi_dims,
        scale_um_per_px, specimen_mask
    )

    return density_metrics, zone_grid, hotspot_zone, debug_vis
