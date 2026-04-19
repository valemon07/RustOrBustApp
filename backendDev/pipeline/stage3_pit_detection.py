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

from pipeline.config import EDGE_OVERLAP_THRESHOLD, EDGE_BUFFER_UM


# ---------------------------------------------------------------------------
# Tuneable constants
# ---------------------------------------------------------------------------

CLAHE_CLIP_LIMIT  = 3.0
CLAHE_TILE_GRID   = (8, 8)
BLUR_KERNEL_SIZE  = 5

MIN_PIT_AREA_UM2               = 10.0       # R1 — absolute floor (sub-resolution noise)
MAX_PIT_AREA_UM2_SURFACE       = 500_000.0  # R2 — interior pits: raised from 150 k → 500 k
                                            #      (2026-04-17) to admit very large coalesced
                                            #      surface corrosion zones.  Diagnostic data
                                            #      shows genuine surface pits reaching
                                            #      200–250 k µm² on severely corroded specimens
                                            #      (e.g. CR3-9_9-side_pit005: 245 618 µm²).
                                            #      Reclassified pits already use 500 k µm²;
                                            #      aligning surface pits to the same ceiling
                                            #      is safe because the hull mask excludes all
                                            #      background regions, and R3/R7 remain active
                                            #      guards against scratches.
MAX_PIT_AREA_UM2_EDGE          = 150_000.0  # R2 — edge pits: raised ceiling; edge pits
                                            #      wrap the curved hole boundary and can
                                            #      span much larger areas than interior pits.
                                            #      Calibrated against largest observed real
                                            #      edge pit (53,602 µm²) with ~3× headroom.
MAX_PIT_AREA_UM2_RECLASSIFIED  = 500_000.0  # R2 — reclassified pits (edge→surface): higher
                                            #      ceiling because reclassification already
                                            #      confirmed the pit is spatially interior
                                            #      (area-fraction or centroid test).  Very
                                            #      large coalesced corrosion zones that
                                            #      originate at the hole edge but extend
                                            #      deep into the surface can exceed 150 k µm².
                                            #      Calibrated against largest observed real
                                            #      coalesced pit (~297 k µm²) with ~1.7×
                                            #      headroom.
MAX_PIT_AREA_UM2_SURFACE_COARSE = 5_000_000.0 # R2 — raised surface ceiling at overview scale
                                             #      (scale ≥ R3_SCALE_BREAKPOINT_HIGH = 4.0 µm/px).
                                             #      At ~4.2 µm/px genuine coalesced corrosion
                                             #      forms connected regions up to ~2.3 M µm²;
                                             #      the fine-scale 500 k ceiling incorrectly
                                             #      rejects all of them.  This higher ceiling
                                             #      is safe at overview scale because:
                                             #        (a) the hull mask excludes all background,
                                             #        (b) R3/R7/R8 remain active guards,
                                             #        (c) background-leakage artifacts at
                                             #            scale 8–11 µm/px measure 14–22 M µm²
                                             #            and still exceed this ceiling.
                                             #      Calibrated against the largest confirmed
                                             #      genuine overview pit (~2.3 M µm²) with
                                             #      ~2× headroom.
MAX_ASPECT_RATIO               = 8.0        # R3 — polishing scratch (small/medium pits)
MAX_ASPECT_RATIO_LARGE_PIT     = 14.0       # R3 — relaxed for large pits (≥ LARGE_PIT_AREA_UM2)
                                            #      Large real pits can be elongated crevices
                                            #      or coalesced damage; raised from 12→14 to
                                            #      recover confirmed interior pits at ~14 aspect
                                            #      that are dark and irregular (not scratches).
MIN_CIRCULARITY                = 0.08       # R4 — interior pits only; edge pits are exempt
                                            #      because their contours wrap the curved hole
                                            #      boundary, giving inherently low circularity
                                            #      regardless of pit quality.
MIN_CIRCULARITY_LARGE_PIT      = 0.005      # R4 — relaxed for large pits (≥ LARGE_PIT_AREA_UM2)
                                            #      Large real corrosion damage can be
                                            #      very irregular — multi-lobed, branching
                                            #      pit clusters have circularity << 0.04.
                                            #      Safe to lower because R3 (aspect ≤ 14)
                                            #      and R7 (darkness) remain active guards:
                                            #      a scratch barely passing R3 has theoretical
                                            #      minimum circularity ≈ π/14 ≈ 0.224,
                                            #      well above this floor.
                                            #      Diagnostic data shows genuine large pits
                                            #      reaching circ ≈ 0.005–0.009 on severely
                                            #      corroded specimens (CR3-8, CR3-9).
                                            #      Lowered from 0.04 → 0.01 → 0.005 (2026-04-17).
MIN_CIRCULARITY_FINE           = 0.12       # R4 — tighter floor for small pits at fine scale
                                            #      (< R4_SCALE_BREAKPOINT µm/px).  At fine scale
                                            #      real pits are well-resolved and appear rounder;
                                            #      noise features (grain-boundary patches, scratch-
                                            #      intersection blobs) tend to have circularity
                                            #      0.05–0.10 and are caught by this higher floor.
R4_SCALE_BREAKPOINT            = 1.5        # µm/px; below this, MIN_CIRCULARITY_FINE applies
MEDIUM_PIT_AREA_UM2_FINE       = 400.0      # R4 — at fine scale (< R4_SCALE_BREAKPOINT),
                                            #      pits with area ≥ this threshold use
                                            #      MIN_CIRCULARITY_MEDIUM_FINE (0.03) instead of
                                            #      the strict MIN_CIRCULARITY_FINE (0.12).
                                            #      The strict 0.12 floor was calibrated for
                                            #      small noise features (grain-boundary patches,
                                            #      scratch blobs) that are typically < 400 µm².
                                            #      Pits above 400 µm² at fine scale are real
                                            #      features whose contours may be inflated by
                                            #      the hull boundary or genuine morphological
                                            #      complexity — the lower floor applies.
MIN_CIRCULARITY_MEDIUM_FINE    = 0.03       # R4 — floor for medium pits at fine scale
                                            #      (area ≥ MEDIUM_PIT_AREA_UM2_FINE AND
                                            #      scale < R4_SCALE_BREAKPOINT).
                                            #      Diagnostic data shows BF005's largest
                                            #      surface pit (633 µm²) has circ=0.0321;
                                            #      the standard 0.08 floor incorrectly rejects
                                            #      it.  Lowered to 0.03 to admit genuinely
                                            #      complex medium pits at extreme fine scale
                                            #      (0.15 µm/px) that are outside the normal
                                            #      operating range.  R7 (darkness ≤ 0.85)
                                            #      and R3 (aspect ≤ 8) remain active guards.
MAX_INTENSITY_RATIO            = 0.85       # R7 — surface pits only: darkness confirmation.
                                            #      Tightened from 0.92 → 0.85 because
                                            #      confirmed real pits never exceed 0.69,
                                            #      and 0.92 was passing bright surface
                                            #      scratches as pits. Regions at ≥ 85 % of
                                            #      the surface mean are not meaningfully dark.
                                            #      Edge pits are exempt because their
                                            #      illumination mixes specimen surface with
                                            #      background at the hole boundary.
# R5 floor derived from minimum physical pit diameter
# (10 µm) reported in ground truth slides.
# Floor = π*(d/2)² ≈ 78 µm² at high magnification.
# Coefficient 84 gives 80.1 µm² at 1.05 µm/px ≥ π*(5µm)² = 78.5 µm².
SCALE_AWARE_AREA_COEFF    = 84.0       # R5 — scale-aware micro-pit floor
                                       #      scale_min = max(10, 84 / scale)
R5_PHYSICAL_MIN_AREA_UM2  = 78.5       # R5 — hard physical floor: π × (5 µm)² = 78.5 µm²
                                       #      Enforces the 10 µm minimum pit diameter at ALL
                                       #      scales.  Without this, the formula
                                       #      max(84/scale, 15×scale²) hits a valley of ~47 µm²
                                       #      at scale ≈ 1.77 µm/px — below the physical min.
R5_FORMULA_CAP_UM2        = 200.0      # R5 — upper cap on the SCALE_AWARE_AREA_COEFF / scale
                                       #      term.  The formula was calibrated for the normal
                                       #      operating range (0.5–4.2 µm/px); at very fine
                                       #      scales outside this range (e.g. 0.15 µm/px) it
                                       #      grows to ~543 µm² — nearly 7× the physical min —
                                       #      and incorrectly rejects real pits.  Capping at
                                       #      200 µm² (≈ 2.5× physical min) prevents this while
                                       #      leaving the formula unchanged across the expected
                                       #      scale range (at 0.5 µm/px the term is 168 µm²,
                                       #      still below 200 µm², so only truly out-of-range
                                       #      images are affected).
MIN_PIXEL_COUNT           = 15         # R5 — pixel-count floor, fine/medium scale
                                       #      (scale < R5_COARSE_BREAKPOINT)
                                       #        15 px × (1.05 µm/px)² = 16.5 µm²  (fine)
                                       #        15 px × (3.1 µm/px)²  = 144 µm²   (medium)
                                       #      dominated by the coefficient term at fine scale.
MIN_PIXEL_COUNT_COARSE    = 25         # R5 — tighter pixel-count floor at coarse scale
                                       #      (scale ≥ R5_COARSE_BREAKPOINT).
                                       #      At coarse scale polishing scratches merge into
                                       #      compact dark zones large enough to pass the
                                       #      fine-scale floor.  Raising to 25 px pushes the
                                       #      floor up without disrupting fine-scale detection:
                                       #        25 px × (4.2 µm/px)² = 441 µm²   (4.2 µm/px)
                                       #        25 px × (6.0 µm/px)² = 900 µm²   (6.0 µm/px)
R5_COARSE_BREAKPOINT      = 4.0        # µm/px; above this, MIN_PIXEL_COUNT_COARSE applies
LARGE_PIT_AREA_UM2        = 2000.0     # R3/R4 — area threshold above which relaxed
                                       #      aspect / circularity limits apply.
                                       #      Chosen to be above the macro tier (1500 µm²)
                                       #      so only genuine macro-scale features get
                                       #      the relaxed limits.

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
R6_ISOLATION_DISTANCE_UM  = 200.0      # R6 — physical isolation radius in µm.
                                       #      A pit with no neighbour within this distance
                                       #      is considered isolated.  Expressed in µm so
                                       #      the test is scale-invariant (was previously
                                       #      a fixed 200 px, which meant 840 µm at 4.2
                                       #      µm/px — effectively disabling R6 at coarse
                                       #      scale).  Convert to px at run time:
                                       #        threshold_px = 200 µm / scale_um_per_px

# Mirror stage2 constants so we can draw the scale-bar zone in debug output
# without importing from stage2 (avoids circular / fragile cross-module deps).
SCALEBAR_X_FRACTION = 0.68
SCALEBAR_Y_FRACTION = 0.80

# Mirror stage2 boundary-zone constant so Stage 3 can recompute it without
# importing from stage2.  Must stay in sync with stage2_roi.HULL_BOUNDARY_DILATION_PX.
HULL_BOUNDARY_DILATION_PX = 5

# Edge-to-surface reclassification threshold.
# Imported from config as EDGE_OVERLAP_THRESHOLD (0.60) — single source of truth
# shared with Stage 2's initial classification.
# An edge candidate is reclassified as a surface pit when the fraction of its
# area that falls inside the boundary zone is < EDGE_OVERLAP_THRESHOLD, i.e.
# the majority of the pit is interior.
# For large pits (≥ LARGE_PIT_AREA_UM2) a centroid test is also applied.

# R8 — dominant-orientation scratch rejection
# A surface candidate is rejected as a scratch segment when its major axis
# is within R8_ANGLE_TOLERANCE_DEG of the dominant surface-texture direction,
# is elongated (aspect > R8_MIN_ASPECT_RATIO), and is small (< R8_MAX_AREA_UM2).
# R8 is skipped entirely when the orientation entropy exceeds
# R8_ORIENTATION_ENTROPY_MAX — this indicates isotropic texture (no dominant
# scratch direction) and avoids false rejections on pit-only images.
R8_ANGLE_TOLERANCE_DEG     = 15.0    # ±15° alignment window; raise to ~20° if under-rejecting
R8_MIN_ASPECT_RATIO        = 3.0     # only applied to elongated candidates
R8_MAX_AREA_UM2_FINE       = 3000.0  # scratch cap for scale < 1.5 µm/px: fine-scale scratch
                                     # segments are small; reduce cap to catch more of them
                                     # before they grow to 5 k µm²
R8_MAX_AREA_UM2_MEDIUM     = 5000.0  # scratch cap for 1.5 ≤ scale < 4.0 µm/px (original value)
R8_MAX_AREA_UM2_COARSE     = 15000.0 # scratch cap for scale ≥ 4.0 µm/px: at coarse scale,
                                     # entire scratch-zone clusters merge into single large
                                     # elongated blobs (5 k–20 k µm²); raise cap to catch them
R8_SCALE_BREAKPOINT        = 1.5     # µm/px boundary between fine and medium R8 cap
                                     # (medium/coarse boundary reuses R3_SCALE_BREAKPOINT_HIGH)
R8_ORIENTATION_ENTROPY_MAX = 2.5     # bits; above this, skip R8 (isotropic texture)

# R3 scale-adaptive ceiling for small/medium pits (area < LARGE_PIT_AREA_UM2).
# Large pits always use MAX_ASPECT_RATIO_LARGE_PIT = 12.0 regardless of scale.
# For small pits at low magnification (high µm/px) scratch segments look like
# short elongated blobs — tighten the ceiling to suppress them.
R3_SCALE_BREAKPOINT_LOW    = 2.0    # µm/px; below this, use standard fine ceiling (8.0)
R3_SCALE_BREAKPOINT_HIGH   = 4.0    # µm/px; above this, apply the coarse ceiling
MAX_ASPECT_RATIO_MEDIUM    = 6.5    # R3 ceiling for 2.0 ≤ scale < 4.0 µm/px, small pits
                                    # Medium scale: scratch remnants more elongated than
                                    # at fine scale; tighten from 8.0 without going to 5.0.
MAX_ASPECT_RATIO_COARSE    = 5.0    # R3 ceiling for scale ≥ 4 µm/px, small pits

# R7 scale-adaptive darkness threshold (surface pits only).
# At low magnification real pits integrate more shadow → appear darker, so we
# can afford a tighter threshold without losing real pits.
R7_SCALE_BREAKPOINT_LOW    = 2.0    # µm/px; below this, use the standard 0.85
R7_SCALE_BREAKPOINT_HIGH   = 4.0    # µm/px; above this, use the coarse threshold
MAX_INTENSITY_RATIO_COARSE = 0.78   # tighter than 0.85; scratch segments are brighter


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


def _compute_boundary_zone(specimen_mask, edge_buffer_px: int | None = None):
    """
    Recompute the hull-boundary proximity zone from the filled specimen mask.

    Mirrors the exact computation in stage2_roi._classify_dark_regions so Stage 3
    can measure how much of any candidate overlaps the boundary zone without
    importing from Stage 2.

    Parameters
    ----------
    specimen_mask  : uint8 mask, 255 = inside hull
    edge_buffer_px : dilation radius in pixels.  None falls back to the static
                     HULL_BOUNDARY_DILATION_PX constant (5 px).

    Returns uint8 mask: 255 = within edge_buffer_px pixels of the hull edge.
    """
    _buf     = edge_buffer_px if edge_buffer_px is not None else HULL_BOUNDARY_DILATION_PX
    eroded   = cv2.erode(specimen_mask, np.ones((3, 3), np.uint8), iterations=1)
    hull_boundary = specimen_mask - eroded
    dil_size = _buf * 2 + 1
    return cv2.dilate(
        hull_boundary,
        np.ones((dil_size, dil_size), np.uint8),
        iterations=1,
    )


def _maybe_reclassify_edge(candidate, scale_um_per_px, boundary_zone):
    """
    Return 'surface' if the candidate is predominantly interior to the specimen.

    Reclassification criteria (either is sufficient):
    1. Area-fraction: ≤ EDGE_OVERLAP_THRESHOLD of the candidate's
       pixels overlap the boundary zone.
    2. Centroid: for large pits (≥ LARGE_PIT_AREA_UM2 µm²), the centroid does
       not fall inside the boundary zone.

    Returns 'edge' unchanged when neither criterion is met.
    """
    mask    = candidate["mask"]
    area_px = int(np.count_nonzero(mask))
    if area_px == 0:
        return "edge"

    overlap_px        = int(np.count_nonzero(cv2.bitwise_and(mask, boundary_zone)))
    boundary_fraction = overlap_px / area_px

    if boundary_fraction < EDGE_OVERLAP_THRESHOLD:
        return "surface"

    area_um2 = area_px * (scale_um_per_px ** 2)
    if area_um2 >= LARGE_PIT_AREA_UM2:
        moments = cv2.moments(mask.astype(np.float32))
        if moments["m00"] > 0:
            cx = int(moments["m10"] / moments["m00"])
            cy = int(moments["m01"] / moments["m00"])
            if 0 <= cy < boundary_zone.shape[0] and 0 <= cx < boundary_zone.shape[1]:
                if boundary_zone[cy, cx] == 0:
                    return "surface"

    return "edge"


def _compute_dominant_orientation(gray, specimen_mask):
    """
    Estimate the dominant scratch/grain direction of the specimen surface.

    Method: Sobel gradient orientation histogram on the strongest-gradient
    pixels inside the specimen hull.  Scratches produce gradients perpendicular
    to their length, so scratch_direction = gradient_direction + 90°.

    Returns
    -------
    dominant_angle_deg : float or None
        Dominant texture/scratch direction in [0°, 180°), or None if no
        strong gradients were found inside the specimen.
    entropy_bits : float
        Shannon entropy of the 36-bin (5° per bin) orientation histogram.
        Values above R8_ORIENTATION_ENTROPY_MAX indicate isotropic texture —
        no reliable scratch direction can be identified and R8 should be
        skipped for all candidates in this image.
    """
    sobel_x   = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    sobel_y   = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    magnitude = np.sqrt(sobel_x ** 2 + sobel_y ** 2)

    interior = specimen_mask > 0
    if not np.any(interior):
        return None, float("inf")

    # Use only the top-quartile gradients (suppress noise from flat regions)
    mag_threshold = float(np.percentile(magnitude[interior], 75))
    strong_mask   = interior & (magnitude > mag_threshold)
    if not np.any(strong_mask):
        return None, float("inf")

    # Gradient angle → fold to [0°, 180°) (orientation, not signed direction)
    grad_angle_deg    = np.degrees(np.arctan2(sobel_y, sobel_x)) % 180.0
    # Scratch direction is perpendicular to the dominant gradient direction
    scratch_angle_deg = (grad_angle_deg + 90.0) % 180.0

    angles = scratch_angle_deg[strong_mask]

    # 36-bin histogram: 5° per bin over [0°, 180°)
    n_bins  = 36
    hist, _ = np.histogram(angles, bins=n_bins, range=(0.0, 180.0))
    hist    = hist.astype(np.float64)
    total   = hist.sum()
    if total == 0:
        return None, float("inf")

    hist_norm = hist / total
    with np.errstate(divide="ignore", invalid="ignore"):
        log_p   = np.where(hist_norm > 0, np.log2(hist_norm), 0.0)
        entropy = -float(np.sum(hist_norm * log_p))

    dominant_bin   = int(np.argmax(hist))
    dominant_angle = (dominant_bin + 0.5) * (180.0 / n_bins)   # centre of dominant bin
    return dominant_angle, entropy


def _process_candidate(candidate, pit_type, scale_um_per_px,
                        gray, mean_surface_intensity,
                        effective_min_area_um2,
                        dominant_orientation=None,
                        thresholds=None):
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
    effective_min_area_um2 : float — max(MIN_PIT_AREA_UM2, SCALE_AWARE_AREA_COEFF/scale, pixel_floor)

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

    # --- Solidity (area / convex hull area) ------------------------------
    hull      = cv2.convexHull(contour)
    hull_area = cv2.contourArea(hull)
    solidity  = area_px / hull_area if hull_area > 0 else 0.0

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

    # --- Centroid and orientation from moments ---------------------------
    moments = cv2.moments(contour)
    if moments["m00"] > 0:
        centroid_x = int(moments["m10"] / moments["m00"])
        centroid_y = int(moments["m01"] / moments["m00"])
        # Major-axis orientation from second-order central moments → [0°, 180°).
        # Compared against dominant_orientation for R8.  Using moments avoids
        # the fitEllipse angle-convention ambiguity (RotatedRect width/height order).
        pit_angle_deg = (0.5 * math.degrees(
            math.atan2(2.0 * moments["mu11"],
                       moments["mu20"] - moments["mu02"])
        )) % 180.0
    else:
        centroid_x    = bx + bw // 2
        centroid_y    = by + bh // 2
        pit_angle_deg = 0.0

    # --- Intensity metrics -----------------------------------------------
    region_pixels   = gray[mask > 0]
    mean_intensity  = float(region_pixels.mean()) if len(region_pixels) > 0 else 0.0
    intensity_ratio = (mean_intensity / mean_surface_intensity
                       if mean_surface_intensity > 0 else 0.0)

    # --- Resolve per-image overrides (or fall back to module constants) -----
    _th = thresholds or {}
    _r3_base = _th.get("r3_max_aspect_ratio",    MAX_ASPECT_RATIO)
    _r4_base = _th.get("r4_min_circularity",     MIN_CIRCULARITY)
    _r7_base = _th.get("r7_max_intensity_ratio", MAX_INTENSITY_RATIO)
    _r8_min  = _th.get("r8_min_aspect_ratio",    R8_MIN_ASPECT_RATIO)

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
    # R2 — area ceiling.  Four tiers:
    #   edge pits                      — 150 k µm²  (wraps curved hole boundary)
    #   surface/reclassified, coarse   — 5 M µm²    (scale ≥ 4.0 µm/px: genuine overview
    #                                                 corrosion reaches ~2.3 M µm²)
    #   reclassified pits, fine scale  — 500 k µm²  (spatially confirmed interior;
    #                                                 large coalesced zones valid at fine scale)
    #   surface pits, fine scale       — 500 k µm²  (standard interior ceiling)
    if pit_type == "edge":
        max_area = MAX_PIT_AREA_UM2_EDGE                  # 150 k — edge pits
    elif scale_um_per_px >= R3_SCALE_BREAKPOINT_HIGH:     # ≥ 4.0 µm/px (overview scale)
        max_area = MAX_PIT_AREA_UM2_SURFACE_COARSE        # 5 M — large coalesced interior pits
    elif candidate.get("reclassified_from_edge"):
        max_area = MAX_PIT_AREA_UM2_RECLASSIFIED          # 500 k — reclassified (fine scale)
    else:
        max_area = MAX_PIT_AREA_UM2_SURFACE               # 500 k — surface pit (fine scale)
    if area_um2 > max_area:
        rejection_reasons.append(
            f"R2:area {area_um2:.0f}µm² > max {max_area:.0f}µm²"
        )
    # R3 — aspect ratio: scale-adaptive ceiling for small/medium pits.
    # ALL edge pits are EXEMPT from R3 entirely.  Pits near the specimen
    # boundary can only grow inward, creating natural elongation that is a
    # geometric artifact of the boundary position — not evidence of a scratch.
    # This is the same rationale for which R4 and R7 are already fully exempt
    # for all edge pits.
    # For large surface pits: use the relaxed 12.0 ceiling (coalesced damage
    # can be elongated without being a scratch).
    # For small pits: tighten to 5.0 at scale > 4 µm/px where scratch segments
    # appear as short elongated blobs indistinguishable from micro-pits at
    # the standard 8.0 ceiling.
    if pit_type != "edge":
        # Scale-adaptive ceiling.  When an override is active, it acts as a
        # uniform cap: min(constant, _r3_base) so the override can only
        # tighten at medium/coarse scales (it can loosen at fine scale).
        # Large pits are never affected by the R3 override — their elongation
        # is genuine coalesced damage, not scratch fragments.
        if area_um2 >= LARGE_PIT_AREA_UM2:
            aspect_ceiling = MAX_ASPECT_RATIO_LARGE_PIT              # 14.0 — coalesced damage
        elif scale_um_per_px >= R3_SCALE_BREAKPOINT_HIGH:            # ≥ 4.0 µm/px
            aspect_ceiling = min(MAX_ASPECT_RATIO_COARSE, _r3_base)  # 5.0 or override
        elif scale_um_per_px >= R3_SCALE_BREAKPOINT_LOW:             # 2.0–4.0 µm/px
            aspect_ceiling = min(MAX_ASPECT_RATIO_MEDIUM, _r3_base)  # 6.5 or override
        else:                                                         # < 2.0 µm/px
            aspect_ceiling = _r3_base                                 # fine scale base
        if aspect_ratio > aspect_ceiling:
            rejection_reasons.append(
                f"R3:aspect {aspect_ratio:.2f} > max {aspect_ceiling}"
            )
    # R4 — circularity: interior pits only.  Edge pits wrap the curved hole
    # boundary and always have low circularity by geometry, not because they
    # are noise.  Applying R4 to edge pits would reject real large pits.
    # Large surface pits can be very irregular; a relaxed floor applies when
    # area ≥ LARGE_PIT_AREA_UM2 to avoid discarding genuine macro damage.
    # R4 override (_r4_base) replaces the standard floor (0.08) and is also
    # applied to the fine-scale tiers proportionally.  The large-pit domain
    # floor (MIN_CIRCULARITY_LARGE_PIT = 0.005) is intentionally NOT affected
    # by the override: it is a domain-calibrated value for genuine macro
    # coalesced damage.  To reject large-pit false positives use R3 or R7
    # overrides, or morph_open_kernel_px in Stage 2.
    if area_um2 >= LARGE_PIT_AREA_UM2:
        circ_floor = MIN_CIRCULARITY_LARGE_PIT           # 0.005 — domain-fixed, not overridden
    elif scale_um_per_px < R4_SCALE_BREAKPOINT:          # < 1.5 µm/px (fine scale)
        if area_um2 >= MEDIUM_PIT_AREA_UM2_FINE:
            circ_floor = MIN_CIRCULARITY_MEDIUM_FINE     # 0.03
        else:
            circ_floor = MIN_CIRCULARITY_FINE            # 0.12
    else:
        circ_floor = _r4_base                            # standard tier: use override
    if pit_type != "edge" and circularity < circ_floor:
        rejection_reasons.append(
            f"R4:circ {circularity:.4f} < min {circ_floor}"
        )
    # R7 — darkness confirmation: scale-adaptive threshold (surface pits only).
    # At fine scale (≤ 2 µm/px) keep the current 0.85 threshold.
    # At coarse scale (≥ 4 µm/px) tighten to 0.78: real pits integrate more
    # shadow into each pixel at low magnification and appear distinctly darker,
    # so candidates near 0.85 at coarse scale are more likely surface texture
    # or scratch remnants than genuine pits.
    # Interpolate linearly between the two breakpoints.
    # Edge pits are exempt — illumination mixes at the hole boundary.
    # _r7_base replaces MAX_INTENSITY_RATIO as the fine-scale ceiling.
    # The coarse end is always ≤ _r7_base (a tighter override also tightens
    # the coarse end; the interpolation cannot exceed the override).
    if scale_um_per_px <= R7_SCALE_BREAKPOINT_LOW:
        r7_threshold = _r7_base
    elif scale_um_per_px >= R7_SCALE_BREAKPOINT_HIGH:
        r7_threshold = min(MAX_INTENSITY_RATIO_COARSE, _r7_base)
    else:
        t = ((scale_um_per_px - R7_SCALE_BREAKPOINT_LOW) /
             (R7_SCALE_BREAKPOINT_HIGH - R7_SCALE_BREAKPOINT_LOW))
        r7_threshold = _r7_base + t * (MAX_INTENSITY_RATIO_COARSE - MAX_INTENSITY_RATIO)
        r7_threshold = min(r7_threshold, _r7_base)   # cap: override always wins at fine end
    if pit_type != "edge" and intensity_ratio >= r7_threshold:
        rejection_reasons.append(
            f"R7:intensity_ratio {intensity_ratio:.4f} >= max {r7_threshold:.3f}"
        )
    # R8 — dominant-orientation scratch rejection (surface pits only).
    # A candidate whose major axis aligns with the dominant surface-grain/scratch
    # direction AND is elongated AND is small is most likely a scratch segment.
    # Three conditions must ALL hold:
    #   (a) major-axis within R8_ANGLE_TOLERANCE_DEG of dominant scratch direction
    #   (b) aspect_ratio > R8_MIN_ASPECT_RATIO  (elongated shape)
    #   (c) area_um2 < r8_area_cap              (large pits exempt; cap is scale-adaptive)
    # Skipped when dominant_orientation is None (isotropic texture, or no clear
    # scratch direction found for this image).
    # Reclassified pits (confirmed interior by spatial test) are also exempt.
    if scale_um_per_px < R8_SCALE_BREAKPOINT:            # < 1.5 µm/px
        r8_area_cap = R8_MAX_AREA_UM2_FINE
    elif scale_um_per_px >= R3_SCALE_BREAKPOINT_HIGH:    # ≥ 4.0 µm/px
        r8_area_cap = R8_MAX_AREA_UM2_COARSE
    else:                                                # 1.5–4.0 µm/px
        r8_area_cap = R8_MAX_AREA_UM2_MEDIUM
    if (pit_type == "surface"
            and not candidate.get("reclassified_from_edge")
            and dominant_orientation is not None
            and aspect_ratio > _r8_min
            and area_um2 < r8_area_cap):
        delta = abs(pit_angle_deg - dominant_orientation)
        delta = min(delta, 180.0 - delta)
        if delta <= R8_ANGLE_TOLERANCE_DEG:
            rejection_reasons.append(
                f"R8:scratch_aligned  angle={pit_angle_deg:.1f}°  "
                f"dominant={dominant_orientation:.1f}°  Δ={delta:.1f}°"
            )

    # Tier assignment: macro = matches human expert scale, micro = sub-expert.
    # Tier is only meaningful when rejection_reasons is empty (i.e. confirmed).
    pit_tier = "macro" if area_um2 >= MACRO_PIT_AREA_UM2 else "micro"

    return {
        "pit_type":              pit_type,
        "pit_tier":              pit_tier,
        "reclassified_from_edge": candidate.get("reclassified_from_edge", False),
        "centroid_x_px":   centroid_x,
        "centroid_y_px":   centroid_y,
        "area_px":         area_px,
        "area_um2":        round(area_um2,       2),
        "width_um":        round(bw * scale_um_per_px, 2),
        "height_um":       round(bh * scale_um_per_px, 2),
        "pit_depth_um":    round(pit_depth_um,   2),
        "aspect_ratio":    round(aspect_ratio,   3),
        "circularity":     round(circularity,    4),
        "solidity":        round(solidity,        4),
        "mean_intensity":  round(mean_intensity, 2),
        "intensity_ratio": round(intensity_ratio, 4),
        "pit_angle_deg":   round(pit_angle_deg,   1),
        "edge_overlap_fraction": round(candidate.get("edge_overlap_fraction", 0.0), 4),
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
    # Colour key:
    #   Green  — confirmed surface pit
    #   Blue   — confirmed edge pit (stays edge after reclassification check)
    #   Orange — reclassified pit (was edge in Stage 2, promoted to surface in Stage 3)
    for pit in confirmed_pits:
        is_macro      = pit.get("pit_tier", "micro") == "macro"
        reclassified  = pit.get("reclassified_from_edge", False)
        if reclassified:
            colour    = (0, 165, 255) if is_macro else (0, 90, 160)   # orange
        elif pit["pit_type"] == "surface":
            colour    = (0, 200, 0)   if is_macro else (0, 110, 0)    # green
        else:
            colour    = (0, 0, 220)   if is_macro else (0, 0, 110)    # blue
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
    n_macro       = sum(1 for p in confirmed_pits if p.get("pit_tier") == "macro")
    n_micro       = sum(1 for p in confirmed_pits if p.get("pit_tier") == "micro")
    n_surface     = sum(1 for p in confirmed_pits if p["pit_type"] == "surface")
    n_edge        = sum(1 for p in confirmed_pits if p["pit_type"] == "edge")
    n_reclassified = sum(1 for p in confirmed_pits if p.get("reclassified_from_edge"))
    text_lines = [
        f"Confirmed: {len(confirmed_pits)}  "
        f"macro={n_macro}  micro={n_micro}",
        f"(surf={n_surface} edge={n_edge} reclass={n_reclassified})  "
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

def detect_pits(image_input, scale_um_per_px, specimen_mask, roi_dims,
                verbose=False, edge_buffer_px=None, overrides=None):
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

    # --- 2b. Resolve per-image rule overrides --------------------------------
    # Overrides allow the frontend to tighten (or loosen) individual rule
    # thresholds on a per-image basis without changing module-level constants.
    # Each override key replaces the base threshold; scale-adaptive logic in
    # _process_candidate then applies on top of the overridden value.
    _ov = overrides or {}
    thresholds = {
        "r3_max_aspect_ratio":    _ov.get("r3_max_aspect_ratio",    MAX_ASPECT_RATIO),
        "r4_min_circularity":     _ov.get("r4_min_circularity",     MIN_CIRCULARITY),
        "r7_max_intensity_ratio": _ov.get("r7_max_intensity_ratio", MAX_INTENSITY_RATIO),
        "r8_min_aspect_ratio":    _ov.get("r8_min_aspect_ratio",    R8_MIN_ASPECT_RATIO),
    }

    # --- 3. Rules R1–R5: per-candidate geometric filters -------------------
    # R5 scale-aware floor: effective minimum grows as magnification increases
    # (smaller µm/px → finer resolution → more noise features resolved).
    # Pixel floor: MIN_PIXEL_COUNT × scale² prevents single-pixel noise blobs
    # from surviving at low magnification (large scale_um_per_px) where the
    # coefficient floor alone collapses to near-zero µm².
    px_count = (MIN_PIXEL_COUNT_COARSE
                if scale_um_per_px >= R5_COARSE_BREAKPOINT
                else MIN_PIXEL_COUNT)
    pixel_floor_um2 = px_count * (scale_um_per_px ** 2)
    effective_min_area_um2 = max(
        MIN_PIT_AREA_UM2,
        R5_PHYSICAL_MIN_AREA_UM2,
        min(SCALE_AWARE_AREA_COEFF / scale_um_per_px, R5_FORMULA_CAP_UM2),
        pixel_floor_um2,
    )

    tagged_candidates = (
        [(c, "edge")    for c in roi_dims["edge_pits"]] +
        [(c, "surface") for c in roi_dims["surface_pits"]]
    )

    # --- Edge-to-surface reclassification ------------------------------------
    # Recompute the hull boundary zone (same logic as Stage 2) and reclassify
    # any edge candidate whose area or centroid is predominantly interior.
    # Reclassified candidates are tagged so the debug vis can show them in orange.
    boundary_zone = _compute_boundary_zone(specimen_mask, edge_buffer_px=edge_buffer_px)
    reclassified_tagged = []
    for candidate, pit_type in tagged_candidates:
        if pit_type == "edge":
            new_type = _maybe_reclassify_edge(
                candidate, scale_um_per_px, boundary_zone
            )
            if new_type == "surface":
                candidate["reclassified_from_edge"] = True
            reclassified_tagged.append((candidate, new_type))
        else:
            reclassified_tagged.append((candidate, pit_type))
    tagged_candidates = reclassified_tagged

    # --- Dominant orientation for R8 scratch filter -----------------------
    # Compute once per image — passed to every candidate so the R8 check
    # can compare the candidate's major-axis angle to the surface grain direction.
    # If the orientation histogram is too isotropic (entropy > threshold),
    # dominant_orientation is set to None and R8 is skipped for all candidates.
    dominant_orientation, r8_entropy = _compute_dominant_orientation(
        gray, specimen_mask
    )
    if r8_entropy > R8_ORIENTATION_ENTROPY_MAX:
        dominant_orientation = None

    passed_r1_r5 = []
    rejected_r1_r5 = []

    for candidate, pit_type in tagged_candidates:
        result = _process_candidate(
            candidate, pit_type, scale_um_per_px, gray,
            mean_surface_intensity, effective_min_area_um2,
            dominant_orientation=dominant_orientation,
            thresholds=thresholds,
        )
        if result["rejection_reasons"]:
            rejected_r1_r5.append(result)
        else:
            passed_r1_r5.append(result)

    # --- Verbose rejection log (R1–R8) -----------------------------------
    if verbose:
        r8_status = (f"{dominant_orientation:.1f}°  entropy={r8_entropy:.2f} bits"
                     if dominant_orientation is not None
                     else f"SKIPPED (entropy={r8_entropy:.2f} > {R8_ORIENTATION_ENTROPY_MAX})")
        rejected_large = sorted(
            [r for r in rejected_r1_r5 if r.get("area_um2", 0) > 0],
            key=lambda r: r.get("area_um2", 0), reverse=True
        )
        print(f"\n  [Stage 3 verbose] scale={scale_um_per_px:.4f} µm/px  "
              f"effective_min={effective_min_area_um2:.1f} µm²  "
              f"candidates={len(tagged_candidates)}  "
              f"passed_R1-R8={len(passed_r1_r5)}  "
              f"rejected_R1-R8={len(rejected_r1_r5)}")
        print(f"  R8 dominant_orientation={r8_status}")
        print(f"\n  Rejected candidates (sorted by area, largest first):\n")
        print(f"  {'#':<4} {'type':<8} {'area_um2':>10} {'aspect':>8} "
              f"{'circ':>8} {'solid':>7} {'int_r':>6}  reason")
        print(f"  {'-'*80}")
        for idx, r in enumerate(rejected_large):
            print(f"  {idx:<4} {r.get('pit_type','?'):<8} "
                  f"{r.get('area_um2', 0):>10.1f} "
                  f"{r.get('aspect_ratio', 0):>8.3f} "
                  f"{r.get('circularity', 0):>8.4f} "
                  f"{r.get('solidity', 0):>7.4f} "
                  f"{r.get('intensity_ratio', 0):>6.3f}  "
                  + "; ".join(r.get("rejection_reasons", ["?"])))
        # Also summarise passed candidates
        if passed_r1_r5:
            areas = [p["area_um2"] for p in passed_r1_r5]
            print(f"\n  Passed R1-R5: {len(passed_r1_r5)} candidates  "
                  f"area range [{min(areas):.1f}, {max(areas):.1f}] µm²")
        print()

    # --- 4. Rule R6: isolation filter -------------------------------------
    # A pit is R6-rejected if it is (a) isolated — no R1-R5 survivor within
    # the neighbour threshold — AND (b) its area falls in the bottom 25th
    # percentile among survivors.
    #
    # Neighbour threshold: R6_ISOLATION_DISTANCE_UM (200 µm) converted to
    # pixels at the current scale.  Using a physical distance ensures R6
    # behaves consistently across magnifications.  A fixed pixel distance
    # (previously 200 px) corresponded to 840 µm at 4.2 µm/px, effectively
    # disabling R6 at coarse scale.
    neighbor_threshold_px_sq = (R6_ISOLATION_DISTANCE_UM / scale_um_per_px) ** 2

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
                if dx * dx + dy * dy <= neighbor_threshold_px_sq:
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

    # --- 6. Rejection summary for downstream flag evaluation -----------------
    _rule_counts = {f"R{i}": 0 for i in range(1, 9)}
    for _r in rejected_candidates:
        for _reason in _r.get("rejection_reasons", []):
            _key = _reason.split(":")[0].strip()
            if _key in _rule_counts:
                _rule_counts[_key] += 1
    rejection_summary = {
        "total_rejected": len(rejected_candidates),
        "per_rule": _rule_counts,
    }

    return confirmed_pits, rejected_candidates, debug_vis, rejection_summary
