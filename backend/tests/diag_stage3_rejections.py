"""
Diagnostic: Stage 3 contour rejection detail
=============================================
Runs Stages 1–3 on a target image with verbose=True so every rejected
candidate prints its area_um2, aspect_ratio, circularity, solidity, and
the specific rule that caused rejection.

Usage
-----
    python tests/diag_stage3_rejections.py                   # default target
    python tests/diag_stage3_rejections.py CR3-9_c-side_pit002.jpg
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline.stage1_scale_bar     import detect_scale_bar, ScaleBarNotFoundError
from backend.pipeline.stage2_roi           import extract_roi
from backend.pipeline.stage3_pit_detection import detect_pits, MACRO_PIT_AREA_UM2
from backend.pipeline.config               import MANUAL_SCALE_OVERRIDES

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

DEFAULT_TARGET = "CR3-7_c-side_BF004.jpg"


def main():
    filename = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET
    path     = os.path.join(RAW_DIR, filename)

    if not os.path.exists(path):
        print(f"Image not found: {path}")
        sys.exit(1)

    print(f"\n{'='*80}")
    print(f"  Stage 3 rejection diagnostic: {filename}")
    print(f"{'='*80}")

    # Stage 1
    stem        = os.path.splitext(filename)[0]
    um_override = MANUAL_SCALE_OVERRIDES.get(stem)
    try:
        scale_um_per_px, um_value, _ = detect_scale_bar(
            path, um_value_override=um_override
        )
    except ScaleBarNotFoundError as exc:
        print(f"  Stage 1 FAILED: {exc}")
        sys.exit(1)
    print(f"\n  Stage 1: scale={scale_um_per_px:.4f} µm/px  "
          f"(bar label={um_value:.0f} µm)")

    # Stage 2
    specimen_mask, _, roi_dims, _ = extract_roi(path, scale_um_per_px)
    n_edge    = len(roi_dims["edge_pits"])
    n_surface = len(roi_dims["surface_pits"])
    print(f"  Stage 2: edge_pits={n_edge}  surface_pits={n_surface}  "
          f"total={n_edge + n_surface}")
    print(f"           ROI {roi_dims['width_um']:.0f} × {roi_dims['height_um']:.0f} µm")

    # Stage 3 — verbose rejection log
    confirmed, rejected, _, _ = detect_pits(
        path, scale_um_per_px, specimen_mask, roi_dims, verbose=True
    )

    # Post-run summary
    macro = [p for p in confirmed if p.get("pit_tier") == "macro"]
    micro = [p for p in confirmed if p.get("pit_tier") == "micro"]

    print(f"  Stage 3 confirmed : {len(confirmed)} total  "
          f"(macro={len(macro)}  micro={len(micro)})")

    # Break down rejected by primary rule
    rule_buckets = {}
    for r in rejected:
        reasons = r.get("rejection_reasons", ["?"])
        key = reasons[0].split(":")[0]   # e.g. "R3", "R4", "R6"
        rule_buckets.setdefault(key, []).append(r.get("area_um2", 0))

    print(f"\n  Rejection breakdown by rule:")
    for rule, areas in sorted(rule_buckets.items()):
        areas_sorted = sorted(areas, reverse=True)
        large = [a for a in areas_sorted if a >= MACRO_PIT_AREA_UM2]
        print(f"    {rule}: {len(areas)} rejected  "
              f"(≥{MACRO_PIT_AREA_UM2:.0f} µm² = {len(large)})  "
              f"largest={areas_sorted[0]:.1f} µm²")

    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    main()
