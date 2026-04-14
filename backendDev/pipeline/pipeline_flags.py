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
