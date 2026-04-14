"""
Test — Stage 4: Density Calculation (compatibility smoke-test)

Runs Stages 1 → 2 → 3 → 4 on CR3-7 using the full pipeline interface.
"""

import os
import sys

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage1_scale_bar    import detect_scale_bar
from pipeline.stage2_roi          import extract_roi
from pipeline.stage3_pit_detection import detect_pits
from pipeline.stage4_density      import calculate_density

SAMPLE_IMAGE = os.path.join(os.path.dirname(__file__), "..", "data", "raw",
                             "CR3-7 c-side BF002.jpg")
DEBUG_OUT = os.path.join(os.path.dirname(__file__), "..", "outputs", "debug",
                         "debug_stage4_density.png")


def main():
    if not os.path.exists(SAMPLE_IMAGE):
        print("FAIL — sample image not found:", SAMPLE_IMAGE)
        sys.exit(1)

    try:
        scale_um_per_px, _, _       = detect_scale_bar(SAMPLE_IMAGE)
        specimen_mask, _, roi_dims, _ = extract_roi(SAMPLE_IMAGE, scale_um_per_px)
        confirmed_pits, _, _         = detect_pits(
            SAMPLE_IMAGE, scale_um_per_px, specimen_mask, roi_dims
        )
        density_metrics, zone_grid, hotspot_zone, debug_vis = calculate_density(
            SAMPLE_IMAGE, confirmed_pits, roi_dims, specimen_mask, scale_um_per_px
        )
    except NotImplementedError as exc:
        print(f"FAIL — {exc}")
        sys.exit(1)

    cv2.imwrite(DEBUG_OUT, debug_vis)
    print("PASS — density metrics:")
    for key, value in density_metrics.items():
        print(f"         {key}: {value}")
    print(f"       hotspot zone: {hotspot_zone}")
    print(f"       debug visualisation saved to {DEBUG_OUT}")


if __name__ == "__main__":
    main()
