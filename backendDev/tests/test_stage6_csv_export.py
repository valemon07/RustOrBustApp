"""
Test — Stage 6: CSV Export

Runs the full pipeline on the sample image and writes the result row to
outputs/csv/results.csv.
"""

import os
import sys

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage1_scale_bar import detect_scale_bar
from pipeline.stage2_roi import extract_roi
from pipeline.stage3_pit_detection import detect_pits
from pipeline.stage4_density import calculate_density
from pipeline.stage5_classification import classify_specimen
from pipeline.stage6_csv_export import export_row

SAMPLE_IMAGE = os.path.join(os.path.dirname(__file__), "..", "data", "raw",
                            "CR3-7 c-side BF002.jpg")
CSV_OUT = os.path.join(os.path.dirname(__file__), "..", "outputs", "csv",
                       "results.csv")


def main():
    if not os.path.exists(SAMPLE_IMAGE):
        print("FAIL — sample image not found:", SAMPLE_IMAGE)
        sys.exit(1)

    try:
        scale_um_per_px, _ = detect_scale_bar(SAMPLE_IMAGE)
        roi_mask, _ = extract_roi(SAMPLE_IMAGE)
        pit_contours, _ = detect_pits(SAMPLE_IMAGE, roi_mask)
        metrics, _ = calculate_density(pit_contours, roi_mask, scale_um_per_px)
        classification, _ = classify_specimen(metrics)

        row_data = {
            "filename": os.path.basename(SAMPLE_IMAGE),
            "sample_id": "CR3-7",
            "scale_um_per_px": scale_um_per_px,
            "pit_count": metrics["pit_count"],
            "pit_density_per_cm2": metrics["pit_density_per_cm2"],
            "classification": classification,
            "mean_pit_width_um": metrics["mean_pit_width_um"],
            "max_pit_width_um": metrics["max_pit_width_um"],
        }

        export_row(row_data, CSV_OUT)
    except NotImplementedError as exc:
        print(f"FAIL — {exc}")
        sys.exit(1)

    print(f"PASS — row written to {CSV_OUT}")


if __name__ == "__main__":
    main()
