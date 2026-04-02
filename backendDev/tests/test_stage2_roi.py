"""
Test — Stage 2: ROI Extraction

Loads the sample image, runs extract_roi(), checks the mask looks reasonable,
and saves the debug visualisation to outputs/debug/.
"""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage2_roi import extract_roi

SAMPLE_IMAGE = os.path.join(os.path.dirname(__file__), "..", "data", "raw",
                            "CR3-7 c-side BF002.jpg")
DEBUG_OUT = os.path.join(os.path.dirname(__file__), "..", "outputs", "debug",
                         "debug_stage2_roi.png")


def main():
    if not os.path.exists(SAMPLE_IMAGE):
        print("FAIL — sample image not found:", SAMPLE_IMAGE)
        sys.exit(1)

    try:
        roi_mask, specimen_crop, roi_dims, debug_vis = extract_roi(SAMPLE_IMAGE)
    except NotImplementedError:
        print("FAIL — Stage 2 not yet implemented")
        sys.exit(1)

    nonzero_fraction = np.count_nonzero(roi_mask) / roi_mask.size
    if nonzero_fraction < 0.05 or nonzero_fraction > 0.95:
        print(f"FAIL — ROI mask coverage {nonzero_fraction:.2%} looks wrong "
              f"(expected 5–95% of image)")
        sys.exit(1)

    cv2.imwrite(DEBUG_OUT, debug_vis)
    print(f"PASS — ROI covers {nonzero_fraction:.2%} of image area  "
          f"({roi_dims['width_px']} x {roi_dims['height_px']} px)")
    print(f"       debug visualisation saved to {DEBUG_OUT}")


if __name__ == "__main__":
    main()
