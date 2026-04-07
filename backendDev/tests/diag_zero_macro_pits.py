"""
Diagnostic: zero macro-pit images
==================================
Runs Stages 1-3 on CR3-7_c-side_BF006 and CR3-1_1-side_pit_BF001, printing:
  - Stage 1 scale result
  - Stage 2 candidate counts and per-candidate area / bbox
  - Stage 3 R1-R5 per-candidate verdict (area_um2, aspect, circularity)
    and R6 isolation check, so we can see exactly which rule eliminates pits.

Usage:  python tests/diag_zero_macro_pits.py
"""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage1_scale_bar     import detect_scale_bar
from pipeline.stage2_roi           import extract_roi
from pipeline.stage3_pit_detection import (
    detect_pits,
    MACRO_PIT_AREA_UM2, MIN_PIT_AREA_UM2, MAX_PIT_AREA_UM2,
    MAX_ASPECT_RATIO, MIN_CIRCULARITY, SCALE_AWARE_AREA_COEFF,
    R6_MIN_COUNT,
    _apply_clahe, _compute_surface_intensity, _process_candidate,
)
from pipeline.config import MANUAL_SCALE_OVERRIDES

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

TARGETS = [
    "CR3-7_c-side_BF006.jpg",
    "CR3-1_1-side_pit_BF001.jpg",
]


def _diag_one(filename):
    path = os.path.join(RAW_DIR, filename)
    stem = os.path.splitext(filename)[0]
    print(f"\n{'='*70}")
    print(f"  DIAGNOSTIC: {filename}")
    print(f"{'='*70}")

    # ── Stage 1 ──────────────────────────────────────────────────────────────
    um_override = MANUAL_SCALE_OVERRIDES.get(stem)
    scale, _, _ = detect_scale_bar(path, um_value_override=um_override, verbose=True)
    print(f"\n  Stage 1 → scale = {scale:.4f} µm/px")

    # ── Stage 2 ──────────────────────────────────────────────────────────────
    specimen_mask, _, roi_dims, _ = extract_roi(path, scale)
    edge_pits    = roi_dims["edge_pits"]
    surface_pits = roi_dims["surface_pits"]
    all_candidates = edge_pits + surface_pits
    print(f"\n  Stage 2 → edge_pits={len(edge_pits)}  surface_pits={len(surface_pits)}"
          f"  total={len(all_candidates)}")

    scale_sq = scale ** 2
    for kind, cands in [("edge", edge_pits), ("surface", surface_pits)]:
        for i, c in enumerate(cands):
            area_um2 = c["area_px"] * scale_sq
            bx, by, bw, bh = c["bbox"]
            print(f"    [{kind}#{i}] area_px={c['area_px']:5d}  "
                  f"area_um2={area_um2:8.1f}  bbox=({bx},{by},{bw},{bh})")

    # ── Stage 3 manual walkthrough ───────────────────────────────────────────
    image = cv2.imread(path)
    gray  = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe_gray = _apply_clahe(gray)

    mean_surf = _compute_surface_intensity(gray, specimen_mask, all_candidates)
    effective_min = max(MIN_PIT_AREA_UM2, SCALE_AWARE_AREA_COEFF / scale)

    print(f"\n  Stage 3 parameters:")
    print(f"    mean_surface_intensity = {mean_surf:.1f}")
    print(f"    effective_min_area_um2 = {effective_min:.1f}  "
          f"(= max({MIN_PIT_AREA_UM2}, {SCALE_AWARE_AREA_COEFF}/{scale:.4f}))")
    print(f"    MACRO_PIT_AREA_UM2     = {MACRO_PIT_AREA_UM2}")
    print(f"    MAX_ASPECT_RATIO       = {MAX_ASPECT_RATIO}")
    print(f"    MIN_CIRCULARITY        = {MIN_CIRCULARITY}")

    tagged = ([(c, "edge") for c in edge_pits] +
              [(c, "surface") for c in surface_pits])

    passed_r1_r5 = []
    print(f"\n  R1-R5 per-candidate verdicts ({len(tagged)} total):")
    print(f"    {'#':<4} {'type':<8} {'area_um2':>10} {'aspect':>7} "
          f"{'circ':>7} {'tier':<6} {'verdict'}")
    print(f"    {'-'*75}")
    for idx, (c, pit_type) in enumerate(tagged):
        result = _process_candidate(
            c, pit_type, scale, gray, mean_surf, effective_min
        )
        tier    = result.get("pit_tier", "—")
        reasons = result["rejection_reasons"]
        verdict = "PASS" if not reasons else "FAIL: " + "; ".join(reasons)
        print(f"    {idx:<4} {pit_type:<8} "
              f"{result.get('area_um2', 0):>10.1f} "
              f"{result.get('aspect_ratio', 0):>7.2f} "
              f"{result.get('circularity', 0):>7.4f} "
              f"{tier:<6} {verdict}")
        if not reasons:
            passed_r1_r5.append(result)

    # ── R6 ───────────────────────────────────────────────────────────────────
    print(f"\n  R6 isolation check: {len(passed_r1_r5)} passed R1-R5"
          f"  (threshold = {R6_MIN_COUNT} needed to activate R6)")

    if len(passed_r1_r5) >= R6_MIN_COUNT:
        NEIGHBOR_PX_SQ = 200.0 ** 2
        sorted_areas = sorted(p["area_um2"] for p in passed_r1_r5)
        pct25 = sorted_areas[len(sorted_areas) // 4]
        print(f"    25th-pct area = {pct25:.1f} µm²")
        for idx, pit in enumerate(passed_r1_r5):
            cx, cy = pit["centroid_x_px"], pit["centroid_y_px"]
            has_neighbour = any(
                (cx - o["centroid_x_px"])**2 + (cy - o["centroid_y_px"])**2
                <= NEIGHBOR_PX_SQ
                for jdx, o in enumerate(passed_r1_r5) if jdx != idx
            )
            isolated = not has_neighbour
            r6_fail  = isolated and pit["area_um2"] <= pct25
            if isolated or r6_fail:
                print(f"    pit#{idx}  area={pit['area_um2']:.1f}  "
                      f"isolated={isolated}  R6={'FAIL' if r6_fail else 'pass'}")
    else:
        print("    R6 not activated — all R1-R5 passers are confirmed.")

    # ── Final confirmed count by tier ────────────────────────────────────────
    confirmed, rejected, _ = detect_pits(path, scale, specimen_mask, roi_dims)
    macro_count = sum(1 for p in confirmed if p.get("pit_tier") == "macro")
    micro_count = sum(1 for p in confirmed if p.get("pit_tier") == "micro")
    print(f"\n  Final: confirmed={len(confirmed)} "
          f"(macro={macro_count}, micro={micro_count})  "
          f"rejected={len(rejected)}")
    print(f"{'='*70}\n")


def main():
    for filename in TARGETS:
        _diag_one(filename)


if __name__ == "__main__":
    main()
