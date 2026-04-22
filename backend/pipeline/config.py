"""
Pipeline configuration and manual overrides.

Edit this file to tune global thresholds or supply manual values for
images where automatic detection fails.
"""

# ---------------------------------------------------------------------------
# Manual scale overrides
# ---------------------------------------------------------------------------
# For images where OCR fails or the bar label is misread, supply the correct
# scale bar label value in micrometres (µm) — NOT µm/px.
# The pipeline divides this value by the detected bar width in pixels to get
# the µm/px scale factor, just as it would with a successful OCR read.
#
# Key   : filename stem (no directory, no extension), e.g. "some_image"
# Value : the µm label printed on the scale bar, e.g. 150.0
#
MANUAL_SCALE_OVERRIDES: dict[str, float] = {
    # CR3-3 ci-side (cross-section, high-mag): 30 µm scale bar
    "cr3-3_ci-side006":   30.0,
    "cr3-3_ci-side008":   30.0,
    "cr3-3_ci-side009":   30.0,
    "cr3-3_ci-side010":   30.0,
    # CR3-3 ci-side darkfield overview: 120 µm scale bar
    "cr3-3_ci-side_DF001": 120.0,
    "cr3-3_ci-side_DF002": 120.0,

    #values asked for from the Claude Debug
    "CR3-1_1-side_pit_BF007": 60.0,
    "CR3-1_1-side_pit_DF001": 60.0,
    "CR3-7_c-side_BF009": 300.0,
    "CR3-8_c8-side_pit002": 150.0,
    "cr3-1_initiation_pit_birdseye_view004": 500.0,
    "cr3-3_3-side001": 30.0,
    "cr3-3_3-side_DF001": 120.0,
    "cr3-7_7_side_overview001": 1000.0,
    "cr3-9_c_side_overview001": 1000.0,
}

# ---------------------------------------------------------------------------
# Stage 2 preprocessing
# ---------------------------------------------------------------------------
# CLAHE (Contrast Limited Adaptive Histogram Equalization) corrects non-uniform
# illumination before Otsu thresholding.  Set to False to skip the step.
USE_CLAHE: bool = True
CLAHE_CLIP_LIMIT: float = 2.0          # at high-mag; scaled down at overview
CLAHE_TILE_GRID_SIZE: tuple[int, int] = (8, 8)

# ---------------------------------------------------------------------------
# Contrast sweep retry (Stage 2)
# ---------------------------------------------------------------------------
# When a mask is flagged as poor (roi_incomplete or mask_warning), Stage 2 is
# re-run with gamma-corrected versions of the image. The best-scoring result
# is used. Set to False to disable and always use the single-pass result.
CONTRAST_SWEEP_ENABLED: bool = True
# gamma < 1.0 → darkens image (corrects overexposure / saturation bleed)
# gamma > 1.0 → brightens image (corrects underexposure / low coverage)
# Darkening values listed first — saturation bleed is the more common issue.
CONTRAST_SWEEP_GAMMAS: list[float] = [0.5, 1.0, 2.0, 3.0]

# Mask fill-ratio quality thresholds.
# fill_ratio = hull_mask_pixels / bounding_box_pixels
# Values outside [LOW, HIGH] receive a warning flag in the CSV.
MASK_FILL_LOW_THRESHOLD: float  = 0.02   # nearly empty → segmentation likely failed
MASK_FILL_HIGH_THRESHOLD: float = 0.97   # nearly full bbox → background may be included

# ---------------------------------------------------------------------------
# MASK_ROI_INCOMPLETE flag thresholds (Stage 2)
# ---------------------------------------------------------------------------
# Check 1 — saturation bleed: fraction of hull pixels with HSV-V > this value
ROI_SAT_V_THRESHOLD: int   = 240
ROI_SAT_MAX_FRACTION: float = 0.60   # >60% overexposed pixels → flag

# Check 2 — spatial uniformity: 3×3 grid fill ratio thresholds
ROI_GRID_HIGH_FILL: float = 0.70   # cell is "full"
ROI_GRID_LOW_FILL:  float = 0.25   # adjacent cell is "empty" → concentration detected

# Check 3 (removed) — boundary_clipping was retired: specimens legitimately
# extend beyond the microscope field of view in any direction.

# Check 4 — narrow ROI: minimum fraction of full image dimension
ROI_MIN_DIM_FRACTION: float = 0.25

# Check 5 — low fill ratio that also raises MASK_ROI_INCOMPLETE
ROI_INCOMPLETE_LOW_FILL: float = 0.04

# ---------------------------------------------------------------------------
# Edge classification
# ---------------------------------------------------------------------------
# Fraction of a candidate's pixel area that must overlap the hull boundary
# buffer zone for the candidate to be classified as an edge pit.
# Shared by Stage 2 (initial classification) and Stage 3 (reclassification
# safety net).  Change here propagates to both stages automatically.
EDGE_OVERLAP_THRESHOLD: float = 0.60

# Physical width of the hull boundary buffer zone in µm.
# Converted to pixels at runtime: edge_buffer_px = round(EDGE_BUFFER_UM / scale).
# None = fall back to the pixel-based constant HULL_BOUNDARY_DILATION_PX (5 px)
# defined in stage2_roi and stage3_pit_detection, preserving pre-2026-04-16 behavior.
# Override per image via data/image_overrides.json: {"stem": {"edge_buffer_um": N}}.
EDGE_BUFFER_UM: float | None = None

# ---------------------------------------------------------------------------
# Pipeline operating scale range
# ---------------------------------------------------------------------------
# Images whose detected scale factor falls outside this range cannot be
# processed reliably.  Stage 1 is still run so the actual scale is recorded,
# then the pipeline short-circuits and returns a SCALE_OUT_OF_RANGE error row.
#
# Known image types in the dataset and their approximate scales:
#   Overview images   : ~4.20 µm/px  (1000 µm scale bar)
#   High-mag images   : ~1.05 µm/px  (150 µm scale bar)
#   CR3-3 cross-section: 0.08–0.26 µm/px — outside the supported range
#
PIPELINE_SCALE_MIN_UM_PX: float = 0.5    # µm/px — below this the image is too high-mag
PIPELINE_SCALE_MAX_UM_PX: float = 10.0   # µm/px — above this the image is too low-mag

# ---------------------------------------------------------------------------
# Excluded specimens
# ---------------------------------------------------------------------------
# Specimen IDs whose images should be skipped entirely by the standard
# pipeline.  These are intentional close-up / non-standard captures that
# fall outside the pipeline's scale range and cannot be meaningfully
# processed by the pit-counting logic.
#
# CR3-3: all images are extreme high-magnification cross-sections
# (0.08–0.26 µm/px vs the pipeline's 0.5–10.0 µm/px operating range).
# Including them would produce misleading density numbers.
#
EXCLUDED_SPECIMENS: set[str] = {
    "CR3-3",
}

# ---------------------------------------------------------------------------
# Images with no scale bar
# ---------------------------------------------------------------------------
# Stems of images confirmed to have no embedded scale bar.
# These are skipped cleanly with reason=no_scale_bar_found instead of
# raising an exception.
#
NO_SCALE_BAR_IMAGES: set[str] = {
    "cr3-1_initiation_pit_birdseye_view001",
    "cr3-1_initiation_pit_sideview001",
    "cr3-1_initiation_pit_sideview002",
}
