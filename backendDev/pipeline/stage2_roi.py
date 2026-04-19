"""
Stage 2: ROI Extraction

Isolates the specimen boundary using a convex-hull approach so that dark pit
regions INSIDE the specimen are retained in the mask rather than treated as
background.

Strategy
--------
1. Gaussian blur + Otsu threshold → coarse bright/dark classification.
2. Morphological closing to bridge tiny surface gaps and produce a clean
   bright blob representing the specimen.
3. Exclude the scale bar corner from the closed mask before contour detection
   so the scale bar never contaminates the specimen shape.
4. Find the largest remaining bright connected component; compute its convex
   hull and fill it completely.  The filled hull is the specimen mask — dark
   pits inside the boundary are now INCLUDED.
5. Classify every dark connected component inside the hull:
     edge_pit    — touches the hull boundary (hole edge, mounting resin, etc.)
     surface_pit — fully interior to the hull (candidate corrosion pits)
6. Return the hull mask, a bounding-box crop, dimension + classification
   metadata, and a colour-coded debug image.

Returns
-------
specimen_mask : ndarray uint8   255 = inside hull (includes dark pits), 0 = outside
specimen_crop : ndarray BGR     rectangular bounding-box crop, non-hull pixels blacked out
roi_dims      : dict
    width_px, height_px, width_um, height_um
    edge_pits     — list of {mask, area_px, bbox}  (hole-edge dark regions)
    surface_pits  — list of {mask, area_px, bbox}  (interior dark regions)
debug_vis     : ndarray BGR     colour-coded diagnostic image
"""

import cv2
import numpy as np

from pipeline.config import (
    USE_CLAHE, CLAHE_CLIP_LIMIT, CLAHE_TILE_GRID_SIZE,
    MASK_FILL_LOW_THRESHOLD, MASK_FILL_HIGH_THRESHOLD,
    ROI_SAT_V_THRESHOLD, ROI_SAT_MAX_FRACTION,
    ROI_GRID_HIGH_FILL, ROI_GRID_LOW_FILL,
    ROI_MIN_DIM_FRACTION,
    ROI_INCOMPLETE_LOW_FILL,
    CONTRAST_SWEEP_ENABLED, CONTRAST_SWEEP_GAMMAS,
    EDGE_OVERLAP_THRESHOLD,
)
from pipeline.pipeline_flags import (
    PipelineFlag,
    MASK_ROI_INCOMPLETE, MASK_COVERAGE_LOW, MASK_COVERAGE_HIGH,
    SEVERITY_ERROR, SEVERITY_WARNING,
)


# ---------------------------------------------------------------------------
# Tuneable constants
# ---------------------------------------------------------------------------

# Gaussian blur kernel applied before Otsu thresholding.
BLUR_KERNEL_SIZE = 15

# Morphological closing kernel to fill small surface gaps in the bright mask.
CLOSE_KERNEL_SIZE = 15

# Scale bar exclusion zone: bottom-right corner of the image.
# Excluded region = rightmost 32 % × bottommost 20 %.
SCALEBAR_X_FRACTION = 0.68   # exclusion starts at 68 % across
SCALEBAR_Y_FRACTION = 0.80   # exclusion starts at 80 % down

# Dark regions smaller than this (px²) are treated as noise and skipped.
MIN_DARK_REGION_AREA_PX = 10

# The hull boundary is dilated by this many pixels before checking whether a
# dark region "touches" it.  Catches pits that are adjacent to the boundary
# without being literally on the 1-px-thick edge line.
HULL_BOUNDARY_DILATION_PX = 5

# Secondary centroid test threshold (µm²).
# For candidates with area ≥ this value, also check whether the centroid
# falls inside the boundary zone.  If the centroid is interior the candidate
# is reclassified as surface_pit regardless of overlap fraction.
# Matches LARGE_PIT_AREA_UM2 in stage3_pit_detection.py.
LARGE_PIT_AREA_UM2_EDGE_CLASSIFY = 2000.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_image(image_input):
    """Return a BGR uint8 ndarray from a file path or an existing array."""
    if isinstance(image_input, str):
        image = cv2.imread(image_input)
        if image is None:
            raise FileNotFoundError(f"Cannot load image: {image_input}")
        return image
    return image_input.copy()


def apply_gamma(image_bgr: np.ndarray, gamma: float) -> np.ndarray:
    """Gamma-correct a BGR uint8 image via a 256-entry LUT.

    gamma < 1.0 → darkens (compresses highlights / corrects overexposure)
    gamma > 1.0 → brightens (lifts shadows / corrects underexposure)
    gamma == 1.0 → returns a copy with no change
    """
    if gamma == 1.0:
        return image_bgr.copy()
    inv_gamma = 1.0 / gamma
    lut = np.array(
        [((i / 255.0) ** inv_gamma) * 255.0 for i in range(256)],
        dtype=np.uint8,
    )
    return cv2.LUT(image_bgr, lut)


def extract_roi_contrast_sweep(
    image_input,
    scale_um_per_px: float = 1.0,
    gamma_values: list[float] | None = None,
    edge_buffer_px: int | None = None,
    morph_open_kernel_px: int | None = None,
):
    """Run extract_roi with each gamma; return the result with the largest mask area.

    Tries every gamma in gamma_values (which should include 1.0 for the original
    image). The winner is whichever gamma produces the largest hull pixel count
    (mask_fill_ratio × bounding_box_area). More coverage is always better.

    The returned roi_dims dict gains two extra keys:
      contrast_gamma_used   (float) — gamma that produced the largest hull
      contrast_gammas_tried (int)   — total gammas attempted
    """
    if gamma_values is None:
        gamma_values = CONTRAST_SWEEP_GAMMAS

    base_image = _load_image(image_input)

    def _hull_px(rd: dict) -> float:
        """Estimated hull pixel count = bbox_area × fill_ratio."""
        return rd.get("width_px", 0) * rd.get("height_px", 0) * rd.get("mask_fill_ratio", 0.0)

    def _run(gamma: float):
        return extract_roi(apply_gamma(base_image, gamma), scale_um_per_px,
                           edge_buffer_px=edge_buffer_px,
                           morph_open_kernel_px=morph_open_kernel_px)

    best_result  = None
    best_hull    = -1.0
    best_gamma   = 1.0
    gammas_tried = 0

    for gamma in gamma_values:
        gammas_tried += 1
        try:
            candidate = _run(gamma)
        except Exception:
            # Extreme gammas can collapse contrast so badly that no bright
            # region survives thresholding — treat as a failed attempt.
            continue
        _, _, cdims, _ = candidate
        hull = _hull_px(cdims)
        if hull > best_hull:
            best_hull   = hull
            best_result = candidate
            best_gamma  = gamma

    # Fallback: if all gammas failed (extreme edge case), run baseline.
    if best_result is None:
        best_result = _run(1.0)
        best_gamma  = 1.0

    hull_mask, specimen_crop, roi_dims, debug_vis = best_result
    roi_dims["contrast_gamma_used"]   = best_gamma
    roi_dims["contrast_gammas_tried"] = gammas_tried
    return hull_mask, specimen_crop, roi_dims, debug_vis


def _largest_bright_contour(binary_mask):
    """
    Return the external contour of the largest bright connected component
    in binary_mask.

    Raises RuntimeError if no components are found.
    """
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary_mask, connectivity=8
    )
    if num_labels < 2:
        raise RuntimeError(
            "No bright regions found after thresholding and scale-bar exclusion."
        )

    # Label 0 is background; skip it.
    largest_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    largest_component = (labels == largest_label).astype(np.uint8) * 255

    contours, _ = cv2.findContours(
        largest_component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        raise RuntimeError("findContours returned nothing for the largest bright region.")

    return max(contours, key=cv2.contourArea)


def _fill_convex_hull(contour, img_h, img_w):
    """
    Compute the convex hull of contour and fill it into a binary mask.

    Returns
    -------
    hull_mask   : ndarray uint8  (255 inside hull, 0 outside)
    hull_points : ndarray        convex hull point array (for drawing)
    """
    hull_points = cv2.convexHull(contour)
    hull_mask = np.zeros((img_h, img_w), dtype=np.uint8)
    cv2.drawContours(hull_mask, [hull_points], -1, 255, thickness=cv2.FILLED)
    return hull_mask, hull_points


def _classify_dark_regions(hull_mask, otsu_mask,
                            scale_um_per_px: float = 1.0,
                            edge_buffer_px: int | None = None,
                            morph_open_kernel_px: int | None = None):
    """
    Find every dark connected component inside hull_mask and classify it.

    Classification rule
    -------------------
    A dark region is an **edge_pit** when the fraction of its pixels that
    overlap the hull boundary buffer zone is ≥ EDGE_OVERLAP_THRESHOLD
    (0.60), i.e. the majority of the candidate lies within the boundary buffer.
    Otherwise it is a **surface_pit** (predominantly interior to the hull).

    For large candidates (area ≥ LARGE_PIT_AREA_UM2_EDGE_CLASSIFY µm²), a
    secondary centroid test also reclassifies the candidate as surface_pit if
    the centroid falls outside the boundary zone, regardless of overlap fraction.
    This catches finger-like pits that originate at the edge but extend deep
    into the interior.

    Parameters
    ----------
    hull_mask           : uint8 binary mask, 255 = inside hull
    otsu_mask           : uint8 binary mask, 255 = bright (Otsu output)
    scale_um_per_px     : float, µm per pixel — used for the large-pit area test
    edge_buffer_px      : int or None — boundary dilation radius in pixels.
                          None falls back to HULL_BOUNDARY_DILATION_PX (5 px).
                          Pass the value computed from config.EDGE_BUFFER_UM or a
                          per-image override for scale-invariant control.
    morph_open_kernel_px: int or None — if > 0, apply morphological opening to the
                          dark region mask before connected-component extraction.
                          The structuring element is an ellipse of diameter
                          (2*morph_open_kernel_px + 1).  Opening removes dark
                          features whose inscribed-circle radius is smaller than
                          morph_open_kernel_px — primarily thin scratch artifacts —
                          while preserving rounder pit-like blobs.  None / 0
                          disables the operation (default, preserves existing
                          behaviour).  Exposed as a per-image user override via
                          image_overrides.json → frontend.

    Returns
    -------
    edge_pits, surface_pits : lists of dicts
        Each dict: {mask, area_px, bbox, edge_overlap_fraction}
    """
    # Dark pixels that are inside the hull.
    inside_hull_dark = cv2.bitwise_and(
        cv2.bitwise_not(otsu_mask),
        hull_mask
    )

    # Optional morphological opening: removes thin scratch artifacts whose
    # inscribed-circle radius is smaller than morph_open_kernel_px pixels.
    # Applied BEFORE connected-component extraction so no fragmented scratch
    # blobs are passed to Stage 3.  Disabled by default (None / 0).
    if morph_open_kernel_px and morph_open_kernel_px > 0:
        k = morph_open_kernel_px * 2 + 1
        open_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (k, k)
        )
        inside_hull_dark = cv2.morphologyEx(
            inside_hull_dark, cv2.MORPH_OPEN, open_kernel
        )

    # Hull boundary: the outermost ring of hull pixels.
    eroded_hull = cv2.erode(
        hull_mask,
        np.ones((3, 3), np.uint8),
        iterations=1
    )
    hull_boundary = hull_mask - eroded_hull

    # Dilate the boundary to create a proximity zone.
    _buf     = edge_buffer_px if edge_buffer_px is not None else HULL_BOUNDARY_DILATION_PX
    dil_size = _buf * 2 + 1
    boundary_zone = cv2.dilate(
        hull_boundary,
        np.ones((dil_size, dil_size), np.uint8),
        iterations=1
    )

    # Label all dark regions inside the hull.
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        inside_hull_dark, connectivity=8
    )

    edge_pits    = []
    surface_pits = []

    for label_id in range(1, num_labels):
        area = int(stats[label_id, cv2.CC_STAT_AREA])
        if area < MIN_DARK_REGION_AREA_PX:
            continue

        region_mask = (labels == label_id).astype(np.uint8) * 255

        # Area-overlap fraction test: classify as edge only when the majority
        # of the candidate's pixels fall inside the boundary buffer zone.
        overlap_px        = int(np.count_nonzero(cv2.bitwise_and(region_mask, boundary_zone)))
        edge_overlap_frac = overlap_px / area   # area > 0 guaranteed by MIN_DARK_REGION_AREA_PX
        is_edge           = edge_overlap_frac >= EDGE_OVERLAP_THRESHOLD

        # Secondary centroid test for large pits: if the centroid falls outside
        # the boundary zone the pit is predominantly interior regardless of the
        # overlap fraction.
        if is_edge:
            area_um2 = area * (scale_um_per_px ** 2)
            if area_um2 >= LARGE_PIT_AREA_UM2_EDGE_CLASSIFY:
                moments = cv2.moments(region_mask.astype(np.float32))
                if moments["m00"] > 0:
                    cx = int(moments["m10"] / moments["m00"])
                    cy = int(moments["m01"] / moments["m00"])
                    if (0 <= cy < boundary_zone.shape[0]
                            and 0 <= cx < boundary_zone.shape[1]
                            and boundary_zone[cy, cx] == 0):
                        is_edge = False   # centroid is interior → surface

        entry = {
            "mask":                  region_mask,
            "area_px":               area,
            "bbox":                  (
                int(stats[label_id, cv2.CC_STAT_LEFT]),
                int(stats[label_id, cv2.CC_STAT_TOP]),
                int(stats[label_id, cv2.CC_STAT_WIDTH]),
                int(stats[label_id, cv2.CC_STAT_HEIGHT]),
            ),
            "edge_overlap_fraction": round(edge_overlap_frac, 4),
        }

        if is_edge:
            edge_pits.append(entry)
        else:
            surface_pits.append(entry)

    return edge_pits, surface_pits


# ---------------------------------------------------------------------------
# ROI completeness checks
# ---------------------------------------------------------------------------

def _check_roi_completeness(
    image,
    hull_mask,
    x_min, x_max, y_min, y_max,
    img_h, img_w,
    mask_fill_ratio,
):
    """
    Run all five MASK_ROI_INCOMPLETE checks.  Returns a list of
    PipelineFlag objects — empty list means the ROI looks complete.

    The check is CONSERVATIVE: any single failing check raises the flag.
    """
    triggered_details = []

    hull_crop = hull_mask[y_min : y_max + 1, x_min : x_max + 1]
    hull_pixel_count = int(np.count_nonzero(hull_crop))

    # --- Check 1: Saturation bleed ----------------------------------------
    # Count hull pixels that are near-white (high V AND low S).
    # High V alone catches polished metal (gold/yellow = high V, high S).
    # Requiring S < 60 restricts the flag to true camera overexposure (white).
    roi_bgr = image[y_min : y_max + 1, x_min : x_max + 1]
    hsv     = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    v_ch    = hsv[:, :, 2]
    s_ch    = hsv[:, :, 1]
    overexposed = int(np.sum((v_ch > ROI_SAT_V_THRESHOLD) & (s_ch < 60) & (hull_crop > 0)))
    sat_fraction = overexposed / hull_pixel_count if hull_pixel_count > 0 else 0.0
    if sat_fraction > ROI_SAT_MAX_FRACTION:
        triggered_details.append(
            f"saturation_bleed: {sat_fraction * 100:.1f}% of ROI pixels "
            f"near-white (HSV-V > {ROI_SAT_V_THRESHOLD}, S < 60)"
        )

    # --- Check 2: Spatial uniformity (3×3 grid) ---------------------------
    # If any cell has fill_ratio > ROI_GRID_HIGH_FILL and a 4-connected
    # neighbour has fill_ratio < ROI_GRID_LOW_FILL, the mask is unevenly
    # concentrated, suggesting only part of the specimen was captured.
    bbox_h = y_max - y_min + 1
    bbox_w = x_max - x_min + 1
    grid_fills = np.zeros((3, 3), dtype=float)
    for row in range(3):
        r0 = int(row       * bbox_h / 3)
        r1 = int((row + 1) * bbox_h / 3) if row < 2 else bbox_h
        for col in range(3):
            c0   = int(col       * bbox_w / 3)
            c1   = int((col + 1) * bbox_w / 3) if col < 2 else bbox_w
            cell = hull_crop[r0:r1, c0:c1]
            cell_area = cell.size
            grid_fills[row, col] = (
                int(np.count_nonzero(cell)) / cell_area if cell_area > 0 else 0.0
            )

    flagged_pairs = []
    for row in range(3):
        for col in range(3):
            if grid_fills[row, col] > ROI_GRID_HIGH_FILL:
                for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nr, nc = row + dr, col + dc
                    if 0 <= nr < 3 and 0 <= nc < 3:
                        if grid_fills[nr, nc] < ROI_GRID_LOW_FILL:
                            flagged_pairs.append((row, col, nr, nc))
                            break
    if flagged_pairs:
        pair_desc = "; ".join(
            f"cell({r},{c})={grid_fills[r, c]:.2f} adj cell({nr},{nc})={grid_fills[nr, nc]:.2f}"
            for r, c, nr, nc in flagged_pairs[:3]
        )
        triggered_details.append(f"spatial_uniformity: {pair_desc}")

    # --- Check 4: Narrow ROI relative to image ----------------------------
    narrow_dims = []
    min_w = ROI_MIN_DIM_FRACTION * img_w
    min_h = ROI_MIN_DIM_FRACTION * img_h
    if (x_max - x_min + 1) < min_w:
        narrow_dims.append(
            f"width={x_max - x_min + 1}px < {ROI_MIN_DIM_FRACTION * 100:.0f}% "
            f"of image width ({int(min_w)}px)"
        )
    if (y_max - y_min + 1) < min_h:
        narrow_dims.append(
            f"height={y_max - y_min + 1}px < {ROI_MIN_DIM_FRACTION * 100:.0f}% "
            f"of image height ({int(min_h)}px)"
        )
    if narrow_dims:
        triggered_details.append(f"narrow_roi: {'; '.join(narrow_dims)}")

    # --- Check 5: Overall fill ratio below ROI_INCOMPLETE_LOW_FILL --------
    if mask_fill_ratio < ROI_INCOMPLETE_LOW_FILL:
        triggered_details.append(
            f"low_fill_ratio: {mask_fill_ratio:.4f} < {ROI_INCOMPLETE_LOW_FILL}"
        )

    if not triggered_details:
        return []

    return [
        PipelineFlag(
            name=MASK_ROI_INCOMPLETE,
            severity=SEVERITY_ERROR,
            detail="; ".join(triggered_details),
        )
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_roi(image_input, scale_um_per_px=1.0, edge_buffer_px=None,
                morph_open_kernel_px=None):
    """
    Extract the specimen ROI from a darkfield microscopy image.

    Parameters
    ----------
    image_input : str or numpy.ndarray
        Path to the image file or a BGR numpy array.
    scale_um_per_px : float
        Micrometers per pixel from Stage 1.  Defaults to 1.0.

    Returns
    -------
    specimen_mask : ndarray uint8
        Binary mask of the filled convex hull — 255 inside (including pits),
        0 outside.  Same spatial dimensions as the input image.
    specimen_crop : ndarray BGR
        Bounding-box crop of the original image; non-hull pixels are black.
    roi_dims : dict
        ``width_px``, ``height_px`` — bounding-box size in pixels
        ``width_um``, ``height_um`` — same values in micrometres
        ``edge_pits``    — list of dark-region dicts touching the hull boundary
        ``surface_pits`` — list of dark-region dicts fully interior to the hull
    debug_vis : ndarray BGR
        Colour-coded diagnostic image:
          Green outline  — convex hull boundary
          Red fill       — edge_pit candidates
          Yellow fill    — surface_pit candidates
          Blue rectangle — excluded scale-bar zone
          White text     — ROI dimensions and pit counts
    """
    image = _load_image(image_input)
    img_h, img_w = image.shape[:2]

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # --- 0. Optional CLAHE pass to correct non-uniform illumination ---------
    # At overview scale (≥3 µm/px) reduce clip limit proportionally to avoid
    # amplifying grain texture into false pit candidates.
    if USE_CLAHE:
        clip = CLAHE_CLIP_LIMIT
        if scale_um_per_px >= 3.0:
            clip = max(1.0, CLAHE_CLIP_LIMIT * (3.0 / scale_um_per_px))
        clahe = cv2.createCLAHE(
            clipLimit=clip,
            tileGridSize=CLAHE_TILE_GRID_SIZE,
        )
        gray = clahe.apply(gray)

    # --- 1. Gaussian blur + Otsu threshold ----------------------------------
    blurred = cv2.GaussianBlur(
        gray, (BLUR_KERNEL_SIZE, BLUR_KERNEL_SIZE), 0
    )
    _, otsu_mask = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    # --- 2. Morphological closing to fill tiny surface gaps -----------------
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (CLOSE_KERNEL_SIZE, CLOSE_KERNEL_SIZE)
    )
    closed_mask = cv2.morphologyEx(otsu_mask, cv2.MORPH_CLOSE, close_kernel)

    # --- 3. Exclude scale bar zone before contour detection -----------------
    # This prevents the bright scale bar pixels from merging with or distorting
    # the detected specimen shape.
    sb_y0 = int(img_h * SCALEBAR_Y_FRACTION)
    sb_x0 = int(img_w * SCALEBAR_X_FRACTION)
    closed_mask_no_sb = closed_mask.copy()
    closed_mask_no_sb[sb_y0:, sb_x0:] = 0

    # --- 4. Convex hull of the largest bright component --------------------
    main_contour = _largest_bright_contour(closed_mask_no_sb)
    hull_mask, hull_points = _fill_convex_hull(main_contour, img_h, img_w)

    # Also zero out the scale bar zone in the hull mask itself.
    hull_mask[sb_y0:, sb_x0:] = 0

    # --- 5. Classify dark regions inside the hull --------------------------
    # Use the original Otsu mask (not the closed one) so individual pits are
    # not merged together before classification.
    # Also mask out the scale bar zone from the Otsu mask first.
    otsu_no_sb = otsu_mask.copy()
    otsu_no_sb[sb_y0:, sb_x0:] = 255   # treat scale bar region as "bright"

    edge_pits, surface_pits = _classify_dark_regions(
        hull_mask, otsu_no_sb, scale_um_per_px,
        edge_buffer_px=edge_buffer_px,
        morph_open_kernel_px=morph_open_kernel_px,
    )

    # --- 6. Bounding box and crop ------------------------------------------
    nonzero_ys, nonzero_xs = np.where(hull_mask > 0)
    if len(nonzero_xs) == 0:
        raise RuntimeError(
            "Hull mask is empty after scale-bar exclusion. "
            "The specimen may lie entirely within the excluded corner."
        )

    x_min = int(nonzero_xs.min())
    x_max = int(nonzero_xs.max())
    y_min = int(nonzero_ys.min())
    y_max = int(nonzero_ys.max())

    width_px  = x_max - x_min + 1
    height_px = y_max - y_min + 1

    # --- 6b. Mask fill ratio and quality warning ----------------------------
    mask_pixel_count = int(np.count_nonzero(hull_mask))
    roi_area_pixels  = width_px * height_px
    mask_fill_ratio  = mask_pixel_count / roi_area_pixels if roi_area_pixels > 0 else 0.0

    if mask_fill_ratio < MASK_FILL_LOW_THRESHOLD:
        mask_warning = "low_coverage"
    elif mask_fill_ratio > MASK_FILL_HIGH_THRESHOLD:
        mask_warning = "high_coverage"
    else:
        mask_warning = None

    # Coverage flags as structured PipelineFlag objects
    coverage_flags = []
    if mask_fill_ratio < MASK_FILL_LOW_THRESHOLD:
        coverage_flags.append(PipelineFlag(
            name=MASK_COVERAGE_LOW,
            severity=SEVERITY_ERROR,
            detail=f"mask_fill_ratio={mask_fill_ratio:.4f} < threshold {MASK_FILL_LOW_THRESHOLD}",
        ))
    elif mask_fill_ratio > MASK_FILL_HIGH_THRESHOLD:
        coverage_flags.append(PipelineFlag(
            name=MASK_COVERAGE_HIGH,
            severity=SEVERITY_WARNING,
            detail=f"mask_fill_ratio={mask_fill_ratio:.4f} > threshold {MASK_FILL_HIGH_THRESHOLD}",
        ))

    # --- 6c. ROI completeness checks ----------------------------------------
    pipeline_flags = coverage_flags + _check_roi_completeness(
        image, hull_mask,
        x_min, x_max, y_min, y_max,
        img_h, img_w,
        mask_fill_ratio,
    )
    roi_incomplete = any(f.name == MASK_ROI_INCOMPLETE for f in pipeline_flags)

    roi_dims = {
        "width_px":        width_px,
        "height_px":       height_px,
        "width_um":        round(width_px  * scale_um_per_px, 2),
        "height_um":       round(height_px * scale_um_per_px, 2),
        "edge_pits":       edge_pits,
        "surface_pits":    surface_pits,
        "mask_fill_ratio": round(mask_fill_ratio, 4),
        "mask_warning":    mask_warning,
        "pipeline_flags":  pipeline_flags,
        "roi_incomplete":  roi_incomplete,
    }

    # Bounding-box crop with non-hull pixels blacked out.
    masked_image = image.copy()
    masked_image[hull_mask == 0] = 0
    specimen_crop = masked_image[y_min : y_max + 1, x_min : x_max + 1]

    # --- 7. Debug visualisation --------------------------------------------
    # Start from a copy of the original image, blend coloured region overlays,
    # then draw crisp outlines and text on top.

    # Build union masks for the two pit classes.
    edge_union    = np.zeros((img_h, img_w), dtype=np.uint8)
    surface_union = np.zeros((img_h, img_w), dtype=np.uint8)
    for pit in edge_pits:
        edge_union = cv2.bitwise_or(edge_union, pit["mask"])
    for pit in surface_pits:
        surface_union = cv2.bitwise_or(surface_union, pit["mask"])

    # Semi-transparent colour overlay.
    overlay = image.copy()
    overlay[edge_union > 0]    = (0,   0, 200)   # red   — edge_pit
    overlay[surface_union > 0] = (0, 220, 220)   # yellow — surface_pit
    debug_vis = cv2.addWeighted(image, 0.65, overlay, 0.35, 0)

    # Green convex hull outline.
    cv2.drawContours(debug_vis, [hull_points], -1, (0, 200, 0), 2)

    # Blue rectangle: excluded scale-bar zone.
    cv2.rectangle(
        debug_vis,
        (sb_x0, sb_y0), (img_w - 1, img_h - 1),
        (255, 0, 0), 2
    )

    # White text with shadow.
    text_lines = [
        f"ROI: {width_px} x {height_px} px"
        f"  ({roi_dims['width_um']:.0f} x {roi_dims['height_um']:.0f} um)",
        f"edge_pits: {len(edge_pits)}   surface_pits: {len(surface_pits)}",
    ]
    text_x = 10
    text_y = 35
    for line in text_lines:
        cv2.putText(debug_vis, line, (text_x + 1, text_y + 1),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(debug_vis, line, (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        text_y += 30

    return hull_mask, specimen_crop, roi_dims, debug_vis
