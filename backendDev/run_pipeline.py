"""
run_pipeline.py — Full pipeline runner

Processes every image in data/raw/ through all 6 stages and appends results
to outputs/csv/results.csv.

Usage:
    python run_pipeline.py
    python run_pipeline.py --image "data/raw/some_image.jpg"
"""

import argparse
import glob
import os

from pipeline.stage1_scale_bar import detect_scale_bar
from pipeline.stage2_roi import extract_roi
from pipeline.stage3_pit_detection import detect_pits
from pipeline.stage4_density import calculate_density
from pipeline.stage5_classification import classify_specimen
from pipeline.stage6_csv_export import export_row

RAW_DIR = os.path.join(os.path.dirname(__file__), "data", "raw")
CSV_OUT = os.path.join(os.path.dirname(__file__), "outputs", "csv",
                       "results.csv")


def process_image(image_path):
    """Run all 6 stages on a single image and return the result row dict."""
    scale_um_per_px, _, _ = detect_scale_bar(image_path)
    roi_mask, _ = extract_roi(image_path)
    pit_contours, _, _, _ = detect_pits(image_path, roi_mask)
    metrics, _ = calculate_density(pit_contours, roi_mask, scale_um_per_px)
    classification, _ = classify_specimen(metrics)

    filename = os.path.basename(image_path)
    # Derive sample_id from filename (text before first space or dot)
    sample_id = filename.split(" ")[0].split(".")[0]

    return {
        "filename": filename,
        "sample_id": sample_id,
        "scale_um_per_px": scale_um_per_px,
        "pit_count": metrics["pit_count"],
        "pit_density_per_cm2": metrics["pit_density_per_cm2"],
        "classification": classification,
        "mean_pit_width_um": metrics["mean_pit_width_um"],
        "max_pit_width_um": metrics["max_pit_width_um"],
    }


def main():
    parser = argparse.ArgumentParser(description="Rust or Bust pipeline")
    parser.add_argument("--image", help="Process a single image file")
    args = parser.parse_args()

    if args.image:
        image_paths = [args.image]
    else:
        image_paths = sorted(
            glob.glob(os.path.join(RAW_DIR, "*.jpg")) +
            glob.glob(os.path.join(RAW_DIR, "*.png")) +
            glob.glob(os.path.join(RAW_DIR, "*.tif")) +
            glob.glob(os.path.join(RAW_DIR, "*.tiff"))
        )

    if not image_paths:
        print("No images found in", RAW_DIR)
        return

    for image_path in image_paths:
        print(f"Processing {os.path.basename(image_path)} ...", end=" ",
              flush=True)
        try:
            row_data = process_image(image_path)
            export_row(row_data, CSV_OUT)
            print(f"done — {row_data['classification']} "
                  f"({row_data['pit_count']} pits)")
        except Exception as exc:
            print(f"ERROR — {exc}")

    print(f"\nResults written to {CSV_OUT}")


if __name__ == "__main__":
    main()
