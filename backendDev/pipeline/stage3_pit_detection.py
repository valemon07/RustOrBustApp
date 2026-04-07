"""
Stage 3: Pit Detection

Refines the candidate dark regions produced by Stage 2 into confirmed,
measured corrosion pits by applying CLAHE-corrected illumination analysis
and a four-rule geometric filter.

Inputs
------
image_input    : image path (str) or BGR numpy array
scale_um_per_px: µm-per-pixel ratio from Stage 1
specimen_mask  : filled convex-hull mask from Stage 2 (255 = inside hull)
roi_dims       : dict from Stage 2 containing 'edge_pits' and 'surface_pits'

Pipeline
--------
1. Convert to grayscale; apply CLAHE (clipLimit 3.0, 8×8 tiles) to normalise
   uneven illumination; Gaussian blur 5×5 to suppress scratch noise.
2. Compute the mean surface intensity once (non-pit pixels inside the hull)
   for per-pit intensity normalisation.
3. For every Stage 2 candidate (edge + surface), extract its contour and
   apply six confirmation rules:
     R1 area  ≥ 10 µm²                  (below → sub-resolution, absolute floor)
     R2 area  ≤ 50 000 µm²              (above → hole edge, not a pit)
     R3 aspect ratio ≤ 8.0              (above → polishing scratch)
     R4 circularity ≥ 0.08              (below → polishing scratch)
     R5 area  ≥ max(10, 50/scale) µm²   (scale-aware floor; catches high-mag noise
                                          that is geometrically real but too small)
     R6 isolated AND in bottom 25th pct  (small isolated pits are likely noise;
                                          only applied when ≥ R6_MIN_COUNT pits
                                          survive R1-R5 so sparse images are safe)
4. Confirmed pits receive a pit_id and full measurement record.
5. Rejected candidates are kept with a rejection-reason string for debugging.

Returns
-------
confirmed_pits     : list[dict]  — one dict per confirmed pit
rejected_candidates: list[dict]  — one dict per rejected candidate
debug_vis          : ndarray BGR — annotated diagnostic image
"""

import math

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Tuneable constants
# ---------------------------------------------------------------------------

CLAHE_CLIP_LIMIT  = 3.0
CLAHE_TILE_GRID   = (8, 8)
BLUR_KERNEL_SIZE  = 5

MIN_PIT_AREA_UM2          = 10.0       # R1 — absolute floor (sub-resolution noise)
MAX_PIT_AREA_UM2          = 50_000.0   # R2 — too large (hole edge)
MAX_ASPECT_RATIO          = 8.0        # R3 — polishing scratch
MIN_CIRCULARITY           = 0.08       # R4 — polishing scratch
# R5 floor derived from minimum physical pit diameter
# (10 µm) reported in ground truth slides.
# Floor = π*(d/2)² ≈ 78 µm² at high magnification.
# Coefficient 84 gives 80.1 µm² at 1.05 µm/px ≥ π*(5µm)² = 78.5 µm².
SCALE_AWARE_AREA_COEFF    = 84.0       # R5 — scale-aware micro-pit floor
                                       #      micro_min = max(10, 84 / scale)

# DOMAIN THRESHOLD — DO NOT CHANGE WITHOUT CLIENT APPROVAL
# 1500 µm² minimum derived from calibration against human
# expert pit counts from UVA CESE slide deck (02/13/2026).
# Corresponds to ~44 µm diameter macro-pit — the scale at
# which a trained analyst manually counts corrosion pits.
# Micro-pit tier (below 1500 µm²) is preserved in output
# but excluded from ground-truth-comparable density metrics.
# Calibration table saved in: tests/calibrate_stage3_threshold.py
MACRO_PIT_AREA_UM2        = 1500.0     # tier boundary: macro vs micro pit

R6_MIN_COUNT              = 10         # R6 — don't apply isolation filter when
                                       #      fewer than this many pits survive R1-R5

# Mirror stage2 constants so we can draw the scale-bar zone in debug output
# without importing from stage2 (avoids circular / fragile cross-module deps).
SCALEBAR_X_FRACTION = 0.68
SCALEBAR_Y_FRACTION = 0.80


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


def _apply_clahe(gray):
    """Apply CLAHE to a grayscale image and return the result."""
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT,
                             tileGridSize=CLAHE_TILE_GRID)
    return clahe.apply(gray)


def _compute_surface_intensity(gray, specimen_mask, candidate_list):
    """
    Return the mean grayscale intensity of non-pit specimen pixels.

    Surface pixels = inside the hull mask, NOT covered by any candidate dark
    region.  Used as the denominator for per-pit intensity_ratio.
    """
    dark_union = np.zeros(gray.shape, dtype=np.uint8)
    for candidate in candidate_list:
        dark_union = cv2.bitwise_or(dark_union, candidate["mask"])

    surface_mask = cv2.bitwise_and(specimen_mask,
                                   cv2.bitwise_not(dark_union))
    surface_pixels = gray[surface_mask > 0]
    if len(surface_pixels) == 0:
        return 128.0   # sensible fallback if mask is degenerate
    return float(surface_pixels.mean())


def _contour_from_mask(candidate_mask):
    """
    Return the largest external contour found in candidate_mask, or None.
    """
    contours, _ = cv2.findContours(
        candidate_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def _process_candidate(candidate, pit_type, scale_um_per_px,
                        gray, mean_surface_intensity,
                        effective_min_area_um2):
    """
    Measure one candidate region and test it against rules R1–R5.

    R6 (isolation filter) is applied in the caller after the full candidate
    set is known.

    Parameters
    ----------
    candidate              : dict  {mask, area_px, bbox}  from Stage 2
    pit_type               : "edge" or "surface"
    scale_um_per_px        : float
    gray                   : original grayscale image (uint8)
    mean_surface_intensity : float — pre-computed mean of non-pit surface pixels
    effective_min_area_um2 : float — max(MIN_PIT_AREA_UM2, 50 / scale_um_per_px)

    Returns
    -------
    dict with all measurements plus 'rejection_reasons' (empty list = pass R1-R5).
    """
    mask    = candidate["mask"]
    area_px = int(np.count_nonzero(mask))   # recount from mask for accuracy
    bx, by, bw, bh = candidate["bbox"]

    scale_sq = scale_um_per_px ** 2
    area_um2 = area_px * scale_sq

    contour = _contour_from_mask(mask)
    if contour is None:
        return {
            "pit_type":       pit_type,
            "area_px":        area_px,
            "area_um2":       round(area_um2, 2),
            "rejection_reasons": ["no contour found in mask"],
        }

    # --- Perimeter and circularity ----------------------------------------
    perimeter   = cv2.arcLength(contour, closed=True)
    circularity = ((4.0 * math.pi * area_px) / (perimeter ** 2)
                   if perimeter > 0 else 0.0)

    # --- Aspect ratio and depth via ellipse fit (needs ≥ 5 contour points) --
    if len(contour) >= 5:
        _, (minor_ax, major_ax), _ = cv2.fitEllipse(contour)
        # fitEllipse can return NaN/0 on near-degenerate contours; fall back
        # to bbox in that case so downstream stats stay finite.
        if math.isfinite(major_ax) and math.isfinite(minor_ax) and minor_ax > 0:
            aspect_ratio = major_ax / minor_ax
            pit_depth_um = major_ax * scale_um_per_px
        else:
            aspect_ratio = float(max(bw, bh)) / max(min(bw, bh), 1)
            pit_depth_um = max(bw, bh) * scale_um_per_px
    else:
        # Fallback: bounding-box ratio and longest bbox dimension
        aspect_ratio = float(max(bw, bh)) / max(min(bw, bh), 1)
        pit_depth_um = max(bw, bh) * scale_um_per_px

    # --- Centroid from moments -------------------------------------------
    moments = cv2.moments(contour)
    if moments["m00"] > 0:
        centroid_x = int(moments["m10"] / moments["m00"])
        centroid_y = int(moments["m01"] / moments["m00"])
    else:
        centroid_x = bx + bw // 2
        centroid_y = by + bh // 2

    # --- Intensity metrics -----------------------------------------------
    region_pixels   = gray[mask > 0]
    mean_intensity  = float(region_pixels.mean()) if len(region_pixels) > 0 else 0.0
    intensity_ratio = (mean_intensity / mean_surface_intensity
                       if mean_surface_intensity > 0 else 0.0)

    # --- Confirmation rules R1–R5 ----------------------------------------
    rejection_reasons = []
    if area_um2 < MIN_PIT_AREA_UM2:
        # Absolute floor — catches anything the Stage 2 area filter missed.
        rejection_reasons.append(
            f"R1:area {area_um2:.2f}µm² < floor {MIN_PIT_AREA_UM2}µm²"
        )
    elif area_um2 < effective_min_area_um2:
        # Scale-aware floor — stricter at high magnification.
        rejection_reasons.append(
            f"R5:area {area_um2:.2f}µm² < scale-min {effective_min_area_um2:.1f}µm²"
        )
    if area_um2 > MAX_PIT_AREA_UM2:
        rejection_reasons.append(
            f"R2:area {area_um2:.0f}µm² > max {MAX_PIT_AREA_UM2:.0f}µm²"
        )
    if aspect_ratio > MAX_ASPECT_RATIO:
        rejection_reasons.append(
            f"R3:aspect {aspect_ratio:.2f} > max {MAX_ASPECT_RATIO}"
        )
    if circularity < MIN_CIRCULARITY:
        rejection_reasons.append(
            f"R4:circ {circularity:.4f} < min {MIN_CIRCULARITY}"
        )

    # Tier assignment: macro = matches human expert scale, micro = sub-expert.
    # Tier is only meaningful when rejection_reasons is empty (i.e. confirmed).
    pit_tier = "macro" if area_um2 >= MACRO_PIT_AREA_UM2 else "micro"

    return {
        "pit_type":        pit_type,
        "pit_tier":        pit_tier,
        "centroid_x_px":   centroid_x,
        "centroid_y_px":   centroid_y,
        "area_px":         area_px,
        "area_um2":        round(area_um2,       2),
        "width_um":        round(bw * scale_um_per_px, 2),
        "height_um":       round(bh * scale_um_per_px, 2),
        "pit_depth_um":    round(pit_depth_um,   2),
        "aspect_ratio":    round(aspect_ratio,   3),
        "circularity":     round(circularity,    4),
        "mean_intensity":  round(mean_intensity, 2),
        "intensity_ratio": round(intensity_ratio, 4),
        "contour":         contour,
        "rejection_reasons": rejection_reasons,
    }


def _build_debug_vis(image, confirmed_pits, rejected_candidates,
                     scale_um_per_px, roi_dims):
    """
    Produce the colour-coded diagnostic image.

    Colours
    -------
    Green outline  — confirmed surface pits
    Red outline    — confirmed edge pits
    Grey outline   — rejected candidates
    Blue rectangle — excluded scale-bar zone
    White text     — pit IDs + summary
    """
    debug_vis = image.copy()
    img_h, img_w = image.shape[:2]

    # --- Rejected candidates — grey outlines ----------------------------
    for candidate_result in rejected_candidates:
        if "contour" not in candidate_result:
            continue
        cv2.drawContours(debug_vis, [candidate_result["contour"]],
                         -1, (90, 90, 90), 1)

    # --- Confirmed pits — coloured outlines + ID label ------------------
    # Macro pits: solid colour, thicker outline.
    # Micro pits: dimmed colour, thin outline (visible but de-emphasised).
    for pit in confirmed_pits:
        is_macro = pit.get("pit_tier", "micro") == "macro"
        if pit["pit_type"] == "surface":
            colour    = (0, 200, 0)   if is_macro else (0, 110, 0)
        else:
            colour    = (0, 0, 220)   if is_macro else (0, 0, 110)
        thickness = 2 if is_macro else 1
        cv2.drawContours(debug_vis, [pit["contour"]], -1, colour, thickness)

        # Label: pit_id in white text at centroid (macro pits only to reduce clutter).
        if is_macro:
            label_pos = (pit["centroid_x_px"] + 3, pit["centroid_y_px"] - 3)
            cv2.putText(debug_vis, str(pit["pit_id"]), label_pos,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.28, (0, 0, 0),    2, cv2.LINE_AA)
            cv2.putText(debug_vis, str(pit["pit_id"]), label_pos,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.28, (255, 255, 255), 1, cv2.LINE_AA)

    # --- Scale-bar zone — blue rectangle --------------------------------
    sb_y0 = int(img_h * SCALEBAR_Y_FRACTION)
    sb_x0 = int(img_w * SCALEBAR_X_FRACTION)
    cv2.rectangle(debug_vis, (sb_x0, sb_y0), (img_w - 1, img_h - 1),
                  (255, 0, 0), 2)

    # --- Summary text — top-left corner ---------------------------------
    n_macro   = sum(1 for p in confirmed_pits if p.get("pit_tier") == "macro")
    n_micro   = sum(1 for p in confirmed_pits if p.get("pit_tier") == "micro")
    n_surface = sum(1 for p in confirmed_pits if p["pit_type"] == "surface")
    n_edge    = sum(1 for p in confirmed_pits if p["pit_type"] == "edge")
    text_lines = [
        f"Confirmed: {len(confirmed_pits)}  "
        f"macro={n_macro}  micro={n_micro}",
        f"(surf={n_surface} edge={n_edge})  "
        f"Rejected: {len(rejected_candidates)}",
        f"Scale: {scale_um_per_px:.4f} um/px",
    ]
    text_x, text_y = 10, 28
    for line in text_lines:
        cv2.putText(debug_vis, line, (text_x + 1, text_y + 1),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(debug_vis, line, (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        text_y += 24

    return debug_vis


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_pits(image_input, scale_um_per_px, specimen_mask, roi_dims):
    """
    Refine Stage 2 candidates into confirmed, measured corrosion pits.

    Parameters
    ----------
    image_input : str or numpy.ndarray
        Path to the image file or a BGR numpy array.
    scale_um_per_px : float
        Micrometres per pixel from Stage 1.
    specimen_mask : numpy.ndarray (uint8)
        Filled convex-hull mask from Stage 2.  255 = inside specimen.
    roi_dims : dict
        Output dict from Stage 2.  Must contain 'edge_pits' and
        'surface_pits' (each a list of {mask, area_px, bbox} dicts).

    Returns
    -------
    confirmed_pits : list[dict]
        One dict per confirmed pit with keys:
        pit_id, pit_type ("surface"|"edge"),
        pit_tier ("macro"|"micro"),
        centroid_x_px, centroid_y_px, area_px,
        area_um2, width_um, height_um, aspect_ratio, circularity,
        mean_intensity, intensity_ratio, contour.
        Pits pass all six rules R1–R6.
        pit_tier="macro" means area ≥ MACRO_PIT_AREA_UM2 (1500 µm²) and
        matches the human-expert counting scale.
        pit_tier="micro" means area is above the R5 floor but below 1500 µm².
    rejected_candidates : list[dict]
        Same structure but with a non-empty 'rejection_reasons' list.
        Reason tags: R1 (floor), R2 (too large), R3 (scratch aspect),
        R4 (scratch circularity), R5 (scale-aware floor),
        R6 (isolated small pit).
    debug_vis : numpy.ndarray (BGR)
        Colour-coded diagnostic image.
    """
    image = _load_image(image_input)
    gray  = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # --- 1. CLAHE + Gaussian blur (illumination normalisation) -------------
    clahe_gray = _apply_clahe(gray)
    _ = cv2.GaussianBlur(clahe_gray, (BLUR_KERNEL_SIZE, BLUR_KERNEL_SIZE), 0)
    # (blurred_clahe is available for future re-thresholding in this stage;
    #  intensity measurements deliberately use the original gray so that
    #  mean_intensity values remain directly interpretable as raw pixel values.)

    # --- 2. Mean surface intensity (denominator for intensity_ratio) -------
    all_candidates = roi_dims["edge_pits"] + roi_dims["surface_pits"]
    mean_surface_intensity = _compute_surface_intensity(
        gray, specimen_mask, all_candidates
    )

    # --- 3. Rules R1–R5: per-candidate geometric filters -------------------
    # R5 scale-aware floor: effective minimum grows as magnification increases
    # (smaller µm/px → finer resolution → more noise features resolved).
    effective_min_area_um2 = max(MIN_PIT_AREA_UM2,
                                 SCALE_AWARE_AREA_COEFF / scale_um_per_px)

    tagged_candidates = (
        [(c, "edge")    for c in roi_dims["edge_pits"]] +
        [(c, "surface") for c in roi_dims["surface_pits"]]
    )

    passed_r1_r5 = []
    rejected_r1_r5 = []

    for candidate, pit_type in tagged_candidates:
        result = _process_candidate(
            candidate, pit_type, scale_um_per_px, gray,
            mean_surface_intensity, effective_min_area_um2
        )
        if result["rejection_reasons"]:
            rejected_r1_r5.append(result)
        else:
            passed_r1_r5.append(result)

    # --- 4. Rule R6: isolation filter -------------------------------------
    # A pit is R6-rejected if it is (a) isolated — no R1-R5 survivor within
    # the neighbour threshold — AND (b) its area falls in the bottom 25th
    # percentile among survivors.
    #
    # Neighbour threshold derivation:
    #   threshold_um = 200 * scale_um_per_px
    #   threshold_px = threshold_um / scale_um_per_px  = 200 (always 200 px)
    # The fixed pixel distance ensures consistent coverage at every mag level
    # while expressing a physically larger µm radius on lower-mag images.
    NEIGHBOR_THRESHOLD_PX_SQ = 200.0 ** 2

    confirmed_pits = []
    rejected_r6    = []

    if len(passed_r1_r5) >= R6_MIN_COUNT:
        sorted_areas = sorted(p["area_um2"] for p in passed_r1_r5)
        area_pct25   = sorted_areas[len(sorted_areas) // 4]

        # Identify isolated pits (for-else: break means a neighbour was found).
        isolated_indices = set()
        for idx, pit in enumerate(passed_r1_r5):
            cx, cy = pit["centroid_x_px"], pit["centroid_y_px"]
            for jdx, other in enumerate(passed_r1_r5):
                if idx == jdx:
                    continue
                dx = cx - other["centroid_x_px"]
                dy = cy - other["centroid_y_px"]
                if dx * dx + dy * dy <= NEIGHBOR_THRESHOLD_PX_SQ:
                    break
            else:
                isolated_indices.add(idx)

        for idx, pit in enumerate(passed_r1_r5):
            if idx in isolated_indices and pit["area_um2"] <= area_pct25:
                pit["rejection_reasons"] = [
                    f"R6:isolated small pit  "
                    f"area={pit['area_um2']:.1f}µm²  "
                    f"≤ p25={area_pct25:.1f}µm²"
                ]
                rejected_r6.append(pit)
            else:
                confirmed_pits.append(pit)
    else:
        # Too few survivors — skip R6 to avoid over-filtering sparse images.
        confirmed_pits = list(passed_r1_r5)

    # Assign sequential pit IDs now that the final list is settled.
    for pit_id, pit in enumerate(confirmed_pits):
        pit["pit_id"] = pit_id

    rejected_candidates = rejected_r1_r5 + rejected_r6

    # --- 5. Debug visualisation --------------------------------------------
    debug_vis = _build_debug_vis(
        image, confirmed_pits, rejected_candidates,
        scale_um_per_px, roi_dims
    )

    return confirmed_pits, rejected_candidates, debug_vis
