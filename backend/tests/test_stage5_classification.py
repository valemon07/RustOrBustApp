"""
Test — Stage 5: Classification

Runs Stages 1–5 in sequence, prints the classification result, and saves the
debug summary card to outputs/debug/.
"""

import os
import sys

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline.stage1_scale_bar import detect_scale_bar
from backend.pipeline.stage2_roi import extract_roi
from backend.pipeline.stage3_pit_detection import detect_pits
from backend.pipeline.stage4_density import calculate_density
from backend.pipeline.stage5_classification import classify_specimen

SAMPLE_IMAGE = os.path.join(os.path.dirname(__file__), "..", "data", "raw",
                            "CR3-7 c-side BF002.jpg")
DEBUG_OUT = os.path.join(os.path.dirname(__file__), "..", "outputs", "debug",
                         "debug_stage5_classification.png")


def main():
    if not os.path.exists(SAMPLE_IMAGE):
        print("FAIL — sample image not found:", SAMPLE_IMAGE)
        sys.exit(1)

    try:
        scale_um_per_px, _, _ = detect_scale_bar(SAMPLE_IMAGE)
        roi_mask, _ = extract_roi(SAMPLE_IMAGE)
        pit_contours, _, _, _ = detect_pits(SAMPLE_IMAGE, roi_mask)
        metrics, _ = calculate_density(pit_contours, roi_mask, scale_um_per_px)
        classification, debug_vis = classify_specimen(metrics)
    except NotImplementedError as exc:
        print(f"FAIL — {exc}")
        sys.exit(1)

    cv2.imwrite(DEBUG_OUT, debug_vis)
    print(f"PASS — classification: {classification}")
    print(f"       debug visualisation saved to {DEBUG_OUT}")


if __name__ == "__main__":
    main()
