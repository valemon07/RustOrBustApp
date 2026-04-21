"""
Pipeline flag definitions.

Flags are raised during processing to indicate quality issues with individual
images.  They do NOT abort the pipeline — results are always returned so
researchers can decide how to handle flagged images.

Severity levels
---------------
"warning"  — result is usable but should be reviewed before publication.
"error"    — result should NOT be used for scientific conclusions without
             re-imaging or manual review.

Usage
-----
    from pipeline.pipeline_flags import PipelineFlag, MASK_ROI_INCOMPLETE

    flags: list[PipelineFlag] = []
    if <condition>:
        flags.append(PipelineFlag(
            name=MASK_ROI_INCOMPLETE,
            severity=SEVERITY_ERROR,
            detail="saturation_bleed: 18.3% of ROI pixels overexposed",
        ))
"""

from dataclasses import dataclass


@dataclass
class PipelineFlag:
    name: str
    severity: str
    detail: str

    def to_dict(self) -> dict:
        return {"name": self.name, "severity": self.severity, "detail": self.detail}


# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------
SEVERITY_WARNING = "warning"
SEVERITY_ERROR   = "error"
SEVERITY_INFO    = "info"

# ---------------------------------------------------------------------------
# Flag name constants
# ---------------------------------------------------------------------------

# Stage 2 — ROI/mask quality
MASK_ROI_INCOMPLETE = "MASK_ROI_INCOMPLETE"
"""
The Stage 2 ROI failed to capture the full analyzable specimen surface.
Results from this image should not be used for scientific conclusions without
re-imaging or manual review.

Triggered by ANY of:
  saturation_bleed      — >60% of hull pixels have HSV-V > 240 (overexposed)
  spatial_uniformity    — mask concentrated in one grid cell while adjacent
                          cell is nearly empty (partial specimen capture)
  narrow_roi            — ROI width or height < 25% of the full image dimension
  low_fill_ratio        — hull pixels / bbox area < 0.04
"""

# Stage 2 — ROI/mask coverage
MASK_COVERAGE_LOW = "MASK_COVERAGE_LOW"
"""mask_fill_ratio < MASK_FILL_LOW_THRESHOLD — ROI segmentation almost certainly failed."""

MASK_COVERAGE_HIGH = "MASK_COVERAGE_HIGH"
"""mask_fill_ratio > MASK_FILL_HIGH_THRESHOLD (0.97) — nearly the entire bounding box is mask;
background pixels almost certainly included. Note: fill ratios of 0.85–0.97 are expected
and healthy when the contrast sweep maximises coverage."""

# Geometry
ROI_TOO_SMALL = "ROI_TOO_SMALL"
"""roi_width_um or roi_height_um < 200 µm — specimen capture too small for reliable analysis."""

# Stage 2 — contrast correction
CONTRAST_CORRECTION_STRONG = "CONTRAST_CORRECTION_STRONG"
"""contrast_gamma_used ≥ 3.0 — extreme brightening was needed to get a usable mask;
image is likely severely underexposed. gamma=0.5 (darkening) and gamma=2.0 (moderate
brightening) are normal sweep outcomes and do not trigger this flag."""

# Stage 3 — pit detection quality
ZERO_MACRO_PITS = "ZERO_MACRO_PITS"
"""No macro pits (area ≥ 1500 µm²) confirmed — either no corrosion present or detection failure."""

HIGH_EDGE_PIT_RATIO = "HIGH_EDGE_PIT_RATIO"
"""Edge pits exceed 50% of full_pit_count — boundary may be misclassified as pits."""

HIGH_REJECTION_RATE = "HIGH_REJECTION_RATE"
"""Total rejected candidates > 5× confirmed pits AND confirmed < 5 — over-filtering suspected."""

RULE_DOMINATED_REJECTION = "RULE_DOMINATED_REJECTION"
"""A single rule responsible for > 70% of all rejections AND rejection count > 20.
Useful for threshold diagnostics; does not indicate the result is unusable."""

# Stage 1 — scale calibration
SCALE_OUT_OF_RANGE = "SCALE_OUT_OF_RANGE"
"""
The detected scale factor is outside the pipeline's supported operating range
(0.5–10.0 µm/px).  Results cannot be computed.

Action required: retake this image at a different magnification so the scale
falls within the supported range.
"""

# Dataset-level flags (computed after all images run)
DENSITY_OUTLIER_HIGH = "DENSITY_OUTLIER_HIGH"
"""macro_density_per_cm > mean + 3σ of successful images — statistical outlier, verify manually."""

DENSITY_OUTLIER_LOW = "DENSITY_OUTLIER_LOW"
"""macro_density_per_cm < mean - 3σ of successful images (and non-zero) — statistical outlier."""

# ---------------------------------------------------------------------------
# Canonical severity for each flag name
# ---------------------------------------------------------------------------
FLAG_SEVERITY: dict = {
    SCALE_OUT_OF_RANGE:           SEVERITY_ERROR,
    MASK_ROI_INCOMPLETE:          SEVERITY_ERROR,
    MASK_COVERAGE_LOW:            SEVERITY_ERROR,
    MASK_COVERAGE_HIGH:           SEVERITY_WARNING,
    ROI_TOO_SMALL:                SEVERITY_ERROR,
    CONTRAST_CORRECTION_STRONG:   SEVERITY_WARNING,
    ZERO_MACRO_PITS:              SEVERITY_WARNING,
    HIGH_EDGE_PIT_RATIO:          SEVERITY_WARNING,
    HIGH_REJECTION_RATE:          SEVERITY_WARNING,
    RULE_DOMINATED_REJECTION:     SEVERITY_INFO,
    DENSITY_OUTLIER_HIGH:         SEVERITY_WARNING,
    DENSITY_OUTLIER_LOW:          SEVERITY_WARNING,
}
