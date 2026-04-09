"""
Visualise All Pits
==================
Runs Stages 1–3 on every in-scope JPEG and saves an annotated image to
outputs/debug/all_pits/<filename>.jpg

Each confirmed pit is drawn and labelled:
  - Macro pits  (area ≥ 1500 µm²):  bright green (surface) / bright blue (edge)
                                     label: "#N  <area>µm²  <depth>µm"
  - Micro pits  (area < 1500 µm²):  dim green / dim blue
                                     label: "#N" only (avoids clutter on dense images)
  - Rejected candidates:             dark grey outline, no label

A legend and per-image stats banner are printed at the top of each image.

Usage
-----
    python tests/visualize_all_pits.py          # all images
    python tests/visualize_all_pits.py BF001    # images whose name contains "BF001"
"""

import glob
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage1_scale_bar     import detect_scale_bar, ScaleBarNotFoundError
from pipeline.stage2_roi           import extract_roi
from pipeline.stage3_pit_detection import detect_pits
from pipeline.config               import (MANUAL_SCALE_OVERRIDES,
                                           NO_SCALE_BAR_IMAGES,
                                           EXCLUDED_SPECIMENS)

ROOT     = os.path.join(os.path.dirname(__file__), "..")
RAW_DIR  = os.path.join(ROOT, "data", "raw")
OUT_DIR  = os.path.join(ROOT, "outputs", "debug", "all_pits")

# Colours (BGR)
MACRO_SURFACE_COL  = (0, 220, 0)
MACRO_EDGE_COL     = (220, 80, 0)
MICRO_SURFACE_COL  = (0, 100, 0)
MICRO_EDGE_COL     = (120, 40, 0)
REJECTED_COL       = (70, 70, 70)
LABEL_SHADOW_COL   = (0, 0, 0)
LABEL_TEXT_COL     = (255, 255, 255)
BANNER_BG_COL      = (30, 30, 30)


def _pit_colour(pit):
    is_macro = pit.get("pit_tier", "micro") == "macro"
    if pit["pit_type"] == "surface":
        return MACRO_SURFACE_COL if is_macro else MICRO_SURFACE_COL
    return MACRO_EDGE_COL if is_macro else MICRO_EDGE_COL


def _put_label(img, text, x, y, font_scale=0.28, thickness=1):
    """Draw a drop-shadow label at (x, y)."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, text, (x + 1, y + 1), font, font_scale,
                LABEL_SHADOW_COL, thickness + 1, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), font, font_scale,
                LABEL_TEXT_COL, thickness, cv2.LINE_AA)


def _draw_pits(image, confirmed_pits, rejected_candidates, scale_um_per_px, filename):
    """Return an annotated copy of image with every pit drawn and labelled."""
    vis = image.copy()
    img_h, img_w = vis.shape[:2]

    # --- Rejected candidates: grey outline, no label ----------------------
    for cand in rejected_candidates:
        if "contour" not in cand:
            continue
        cv2.drawContours(vis, [cand["contour"]], -1, REJECTED_COL, 1)

    # --- Confirmed pits: coloured outline + label -------------------------
    n_macro = sum(1 for p in confirmed_pits if p.get("pit_tier") == "macro")
    n_micro = len(confirmed_pits) - n_macro

    for pit in confirmed_pits:
        is_macro = pit.get("pit_tier", "micro") == "macro"
        colour   = _pit_colour(pit)
        thick    = 2 if is_macro else 1
        cv2.drawContours(vis, [pit["contour"]], -1, colour, thick)

        cx = pit["centroid_x_px"]
        cy = pit["centroid_y_px"]

        if is_macro:
            depth = pit.get("pit_depth_um", 0.0)
            area  = pit.get("area_um2", 0.0)
            label = f"#{pit['pit_id']}  {area:.0f}um2  d={depth:.0f}um"
        else:
            label = f"#{pit['pit_id']}"

        _put_label(vis, label, cx + 3, cy - 3,
                   font_scale=0.28 if is_macro else 0.22,
                   thickness=1)

    # --- Stats banner at top of image ------------------------------------
    banner_h = 64
    banner   = np.zeros((banner_h, img_w, 3), dtype=np.uint8)
    banner[:] = BANNER_BG_COL

    n_rej    = len(rejected_candidates)
    line1 = (f"{os.path.basename(filename)}   "
             f"scale={scale_um_per_px:.4f} um/px   "
             f"confirmed={len(confirmed_pits)}  "
             f"macro={n_macro}  micro={n_micro}  "
             f"rejected={n_rej}")
    depths = [p["pit_depth_um"] for p in confirmed_pits if "pit_depth_um" in p]
    if depths:
        line2 = (f"depth:  avg={sum(depths)/len(depths):.1f}um  "
                 f"max={max(depths):.1f}um   "
                 f"[green=surface  orange=edge  grey=rejected  "
                 f"bright=macro  dim=micro]")
    else:
        line2 = "[green=surface  orange=edge  grey=rejected  bright=macro  dim=micro]"

    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(banner, line1, (8, 20),  font, 0.48, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.putText(banner, line2, (8, 48),  font, 0.40, (160, 160, 160), 1, cv2.LINE_AA)

    return np.vstack([banner, vis])


def _process_one(image_path):
    filename = os.path.basename(image_path)
    stem     = os.path.splitext(filename)[0]

    import re
    match = re.search(r"CR3-\d+", filename, re.IGNORECASE)
    specimen_id = match.group(0).upper() if match else None

    if specimen_id in EXCLUDED_SPECIMENS:
        return f"  skip  {filename} (excluded)"
    if stem in NO_SCALE_BAR_IMAGES:
        return f"  skip  {filename} (no scale bar)"

    try:
        um_override = MANUAL_SCALE_OVERRIDES.get(stem)
        try:
            scale_um_per_px, _, _ = detect_scale_bar(
                image_path, um_value_override=um_override
            )
        except ScaleBarNotFoundError:
            return f"  skip  {filename} (no scale bar detected)"

        specimen_mask, _, roi_dims, _ = extract_roi(image_path, scale_um_per_px)
        confirmed_pits, rejected_candidates, _ = detect_pits(
            image_path, scale_um_per_px, specimen_mask, roi_dims
        )

        image = cv2.imread(image_path)
        annotated = _draw_pits(image, confirmed_pits, rejected_candidates,
                               scale_um_per_px, filename)

        os.makedirs(OUT_DIR, exist_ok=True)
        out_path = os.path.join(OUT_DIR, stem + ".jpg")
        cv2.imwrite(out_path, annotated, [cv2.IMWRITE_JPEG_QUALITY, 92])

        n_macro = sum(1 for p in confirmed_pits if p.get("pit_tier") == "macro")
        return (f"  OK    {filename}  "
                f"confirmed={len(confirmed_pits)} macro={n_macro}  → {out_path}")

    except Exception as exc:
        return f"  ERROR {filename}: {exc}"


def main():
    filter_str = sys.argv[1] if len(sys.argv) > 1 else None

    pattern_lower = os.path.join(RAW_DIR, "*.jpg")
    pattern_upper = os.path.join(RAW_DIR, "*.jpeg")
    all_paths = sorted(glob.glob(pattern_lower) + glob.glob(pattern_upper))

    if filter_str:
        all_paths = [p for p in all_paths if filter_str in os.path.basename(p)]

    if not all_paths:
        print(f"No images found in {RAW_DIR}" +
              (f" matching '{filter_str}'" if filter_str else ""))
        sys.exit(1)

    print(f"\nAnnotating {len(all_paths)} image(s) → {OUT_DIR}\n")
    for idx, path in enumerate(all_paths, 1):
        print(f"[{idx:2d}/{len(all_paths)}] ", end="", flush=True)
        msg = _process_one(path)
        print(msg)

    print(f"\nDone. Output directory: {OUT_DIR}\n")


if __name__ == "__main__":
    main()
