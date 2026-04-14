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
