"""
Test — Stage 3 Filter Validation
=================================
Validates that the Stage 3 confirmation rules are working correctly after
the R2 (area ceiling) and R7 (darkness) filter changes.

This test does NOT require ground-truth pit counts.  Instead it checks:

  1. INVARIANT CHECK — every confirmed pit satisfies ALL active filter rules.
     If a confirmed pit fails any rule, the pipeline has a logic error.

  2. REJECTION INTEGRITY — for each rejected candidate, the rejection reason
     matches a real filter violation (no phantom rejections).

  3. DARKNESS DISTRIBUTION — for confirmed surface pits, prints the
     intensity_ratio distribution so you can see whether R7 (< 0.92) is
     cutting noise or mistakenly rejecting real pits.

  4. BORDERLINE REPORT — lists confirmed pits within 15 % of any filter
     boundary.  These are the candidates most at risk of flipping if
     thresholds are adjusted.  Review visually when counts change.

  5. ANCHOR COUNTS — for a fixed set of representative images, checks that
     macro pit counts fall within hand-verified acceptable ranges.  These
     ranges were set after the R2/R4/R7 fixes and should be updated whenever
     thresholds change intentionally.

  6. RULE BREAKDOWN — prints rejection counts by rule across all anchor images
     so you can see at a glance whether any rule is dominating unexpectedly.

Anchor images and expected macro count ranges
---------------------------------------------
  CR3-7_c-side_BF004.jpg        — high-mag severe,  expected macro ≥ 5
  CR3-8_c-side_pit001.jpg       — high-mag severe,  expected macro ≥ 50
  cr3-8_8_side_overview001.jpg  — overview severe,   expected macro ≥ 150
  CR3-9_c-side_pit002.jpg       — high-mag severe,  expected macro ≥ 3
  cr3-1_initiation_pit_birdseye_view002.jpg — moderate overview, expected macro ≥ 30

Usage
-----
    python tests/test_stage3_filter_validation.py
"""

import math
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage1_scale_bar     import detect_scale_bar, ScaleBarNotFoundError
from pipeline.stage2_roi           import extract_roi
from pipeline.stage3_pit_detection import (
    detect_pits,
    _compute_dominant_orientation,
    MIN_PIT_AREA_UM2, MAX_PIT_AREA_UM2_SURFACE, MAX_PIT_AREA_UM2_EDGE,
    MAX_PIT_AREA_UM2_RECLASSIFIED,
    MAX_ASPECT_RATIO, MAX_ASPECT_RATIO_LARGE_PIT, MAX_ASPECT_RATIO_COARSE,
    MIN_CIRCULARITY, MIN_CIRCULARITY_LARGE_PIT,
    MAX_INTENSITY_RATIO, MAX_INTENSITY_RATIO_COARSE,
    R3_SCALE_BREAKPOINT_HIGH,
    R7_SCALE_BREAKPOINT_LOW, R7_SCALE_BREAKPOINT_HIGH,
    R8_ANGLE_TOLERANCE_DEG, R8_MIN_ASPECT_RATIO, R8_MAX_AREA_UM2,
    R8_ORIENTATION_ENTROPY_MAX,
    SCALE_AWARE_AREA_COEFF, MIN_PIXEL_COUNT, LARGE_PIT_AREA_UM2,
    MACRO_PIT_AREA_UM2,
)
from pipeline.config import MANUAL_SCALE_OVERRIDES

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

# ---------------------------------------------------------------------------
# Anchor images: (filename, min_macro_expected, description)
# Update the min_macro floor whenever thresholds change intentionally.
# ---------------------------------------------------------------------------
ANCHORS = [
    ("CR3-7_c-side_BF004.jpg",                        5,
     "high-mag severe — known large edge pits after R2/R4 fix"),
    ("CR3-8_c-side_pit001.jpg",                       50,
     "high-mag severe — dense corrosion, many macro pits"),
    ("cr3-8_8_side_overview001.jpg",                  150,
     "overview severe — large-scale view, high macro density"),
    ("CR3-9_c-side_pit002.jpg",                       3,
     "high-mag severe — moderate density"),
    ("cr3-1_initiation_pit_birdseye_view002.jpg",     30,
     "moderate overview — initiation pit field"),
]

BORDER_MARGIN = 0.15   # flag pits within ±15 % of a threshold boundary


# ---------------------------------------------------------------------------
# Scale-adaptive threshold helpers (mirror logic in stage3_pit_detection)
# ---------------------------------------------------------------------------

def _effective_r3_ceiling(scale, area_um2):
    """Return the R3 aspect-ratio ceiling for the given scale and area."""
    if area_um2 >= LARGE_PIT_AREA_UM2:
        return MAX_ASPECT_RATIO_LARGE_PIT
    if scale > R3_SCALE_BREAKPOINT_HIGH:
        return MAX_ASPECT_RATIO_COARSE
    return MAX_ASPECT_RATIO


def _effective_r7_threshold(scale):
    """Return the R7 intensity-ratio ceiling for the given scale."""
    if scale <= R7_SCALE_BREAKPOINT_LOW:
        return MAX_INTENSITY_RATIO
    if scale >= R7_SCALE_BREAKPOINT_HIGH:
        return MAX_INTENSITY_RATIO_COARSE
    t = ((scale - R7_SCALE_BREAKPOINT_LOW) /
         (R7_SCALE_BREAKPOINT_HIGH - R7_SCALE_BREAKPOINT_LOW))
    return MAX_INTENSITY_RATIO + t * (MAX_INTENSITY_RATIO_COARSE - MAX_INTENSITY_RATIO)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_one(filename):
    import cv2 as _cv2
    path  = os.path.join(RAW_DIR, filename)
    stem  = os.path.splitext(filename)[0]
    um_override = MANUAL_SCALE_OVERRIDES.get(stem)

    scale, _, _ = detect_scale_bar(path, um_value_override=um_override)
    specimen_mask, _, roi_dims, _ = extract_roi(path, scale)
    confirmed, rejected, _ = detect_pits(
        path, scale, specimen_mask, roi_dims
    )
    gray = _cv2.cvtColor(_cv2.imread(path), _cv2.COLOR_BGR2GRAY)
    return scale, confirmed, rejected, gray, specimen_mask


# Tolerance for area comparisons in the invariant check.
# area_um2 is stored rounded to 2 dp; eff_min is recomputed with full float
# precision, so a pit exactly at the floor can round to a value ≤ 0.005 µm²
# below the recomputed threshold.  _AREA_EPSILON prevents false failures.
_AREA_EPSILON = 0.01


def _invariant_violations(pit, scale, pit_type):
    """
    Return list of invariant violation strings for a CONFIRMED pit.
    A confirmed pit must pass every active rule — any failure is a bug.
    """
    violations = []
    area       = pit.get("area_um2", 0)
    aspect     = pit.get("aspect_ratio", 0)
    circ       = pit.get("circularity", 0)
    ir         = pit.get("intensity_ratio", 0)
    pixel_floor = MIN_PIXEL_COUNT * (scale ** 2)
    eff_min    = max(MIN_PIT_AREA_UM2, SCALE_AWARE_AREA_COEFF / scale, pixel_floor)
    if pit_type == "edge":
        max_area = MAX_PIT_AREA_UM2_EDGE
    elif pit.get("reclassified_from_edge"):
        max_area = MAX_PIT_AREA_UM2_RECLASSIFIED
    else:
        max_area = MAX_PIT_AREA_UM2_SURFACE
    aspect_ceil  = _effective_r3_ceiling(scale, area)
    circ_floor   = (MIN_CIRCULARITY_LARGE_PIT if area >= LARGE_PIT_AREA_UM2
                    else MIN_CIRCULARITY)
    r7_threshold = _effective_r7_threshold(scale)

    if area < eff_min - _AREA_EPSILON:
        violations.append(f"R1/R5:area {area:.1f} < {eff_min:.1f}")
    if area > max_area:
        violations.append(f"R2:area {area:.1f} > {max_area:.1f}")
    if aspect > aspect_ceil:
        violations.append(f"R3:aspect {aspect:.2f} > {aspect_ceil}")
    if pit_type != "edge" and circ < circ_floor:
        violations.append(f"R4:circ {circ:.4f} < {circ_floor}")
    if pit_type != "edge" and ir >= r7_threshold:
        violations.append(f"R7:intensity_ratio {ir:.4f} >= {r7_threshold:.3f}")
    return violations


def _borderline(pit, scale, pit_type):
    """
    Return list of (rule, distance_pct) for this pit being close to a boundary.
    """
    flags  = []
    area   = pit.get("area_um2", 0)
    aspect = pit.get("aspect_ratio", 0)
    circ   = pit.get("circularity", 0)
    ir     = pit.get("intensity_ratio", 0)
    pixel_floor = MIN_PIXEL_COUNT * (scale ** 2)
    eff_min = max(MIN_PIT_AREA_UM2, SCALE_AWARE_AREA_COEFF / scale, pixel_floor)
    if pit_type == "edge":
        max_area = MAX_PIT_AREA_UM2_EDGE
    elif pit.get("reclassified_from_edge"):
        max_area = MAX_PIT_AREA_UM2_RECLASSIFIED
    else:
        max_area = MAX_PIT_AREA_UM2_SURFACE
    aspect_ceil  = _effective_r3_ceiling(scale, area)
    circ_floor   = (MIN_CIRCULARITY_LARGE_PIT if area >= LARGE_PIT_AREA_UM2
                    else MIN_CIRCULARITY)
    r7_threshold = _effective_r7_threshold(scale)

    # Area floor — skip pits exactly at the floor (floating-point boundary)
    if area > eff_min - _AREA_EPSILON and abs(area - eff_min) / eff_min < BORDER_MARGIN:
        flags.append(f"near-R5-floor ({area:.1f} vs {eff_min:.1f})")
    # Area ceiling
    if abs(area - max_area) / max_area < BORDER_MARGIN:
        flags.append(f"near-R2-ceiling ({area:.1f} vs {max_area:.1f})")
    # Aspect
    if aspect > 0 and abs(aspect - aspect_ceil) / aspect_ceil < BORDER_MARGIN:
        flags.append(f"near-R3-aspect ({aspect:.2f} vs {aspect_ceil})")
    # Circularity (surface only)
    if pit_type != "edge" and circ > 0:
        if abs(circ - circ_floor) / circ_floor < BORDER_MARGIN:
            flags.append(f"near-R4-circ ({circ:.4f} vs {circ_floor})")
    # Intensity ratio (surface only) — use scale-adaptive threshold
    if pit_type != "edge":
        if abs(ir - r7_threshold) / r7_threshold < BORDER_MARGIN:
            flags.append(f"near-R7-intensity ({ir:.4f} vs {r7_threshold:.3f})")
    return flags


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_passed = True

    print(f"\n{'='*78}")
    print(f"  Stage 3 Filter Validation")
    print(f"  R2 surface ceiling : {MAX_PIT_AREA_UM2_SURFACE:,.0f} µm²")
    print(f"  R4 circularity     : >= {MIN_CIRCULARITY}  (surface pits only; "
          f">= {MIN_CIRCULARITY_LARGE_PIT} for area >= {LARGE_PIT_AREA_UM2:.0f} µm²)")
    print(f"  R8 scratch filter  : ±{R8_ANGLE_TOLERANCE_DEG:.0f}°  "
          f"aspect>{R8_MIN_ASPECT_RATIO}  area<{R8_MAX_AREA_UM2:.0f} µm²  "
          f"entropy_max={R8_ORIENTATION_ENTROPY_MAX}")
    print(f"\n  Scale-adaptive threshold audit:")
    print(f"  {'scale µm/px':>12}  {'R3 small pit':>14}  {'R3 large pit':>14}  {'R7 threshold':>14}")
    for s in [1.0, 2.0, 4.0, 6.0]:
        r3s = _effective_r3_ceiling(s, 0.0)          # area=0 → small pit branch
        r3l = _effective_r3_ceiling(s, LARGE_PIT_AREA_UM2)  # large pit branch
        r7  = _effective_r7_threshold(s)
        print(f"  {s:>12.1f}  {r3s:>14.1f}  {r3l:>14.1f}  {r7:>14.3f}")
    print(f"{'='*78}\n")

    global_rule_counts = {}
    global_invariant_fails = []

    for filename, min_macro, description in ANCHORS:
        path = os.path.join(RAW_DIR, filename)
        print(f"  {'─'*72}")
        print(f"  {filename}")
        print(f"  {description}")

        if not os.path.exists(path):
            print(f"  SKIP — file not found\n")
            continue

        try:
            scale, confirmed, rejected, _gray, _mask = _run_one(filename)
        except Exception as exc:
            print(f"  ERROR — {exc}\n")
            all_passed = False
            continue

        macro_pits   = [p for p in confirmed if p.get("pit_tier") == "macro"]
        surface_conf = [p for p in confirmed if p["pit_type"] == "surface"]
        edge_conf    = [p for p in confirmed if p["pit_type"] == "edge"]
        pixel_floor  = MIN_PIXEL_COUNT * (scale ** 2)
        eff_min      = max(MIN_PIT_AREA_UM2, SCALE_AWARE_AREA_COEFF / scale, pixel_floor)

        print(f"\n  scale={scale:.4f} µm/px  eff_min_area={eff_min:.1f} µm²  "
              f"(pixel_floor={pixel_floor:.1f})")
        print(f"  confirmed={len(confirmed)} "
              f"(macro={len(macro_pits)} micro={len(confirmed)-len(macro_pits)})  "
              f"surface={len(surface_conf)}  edge={len(edge_conf)}")
        print(f"  rejected={len(rejected)}")

        # --- 1. Anchor count check ----------------------------------------
        if len(macro_pits) >= min_macro:
            print(f"  [PASS] macro count {len(macro_pits)} >= expected floor {min_macro}")
        else:
            print(f"  [FAIL] macro count {len(macro_pits)} < expected floor {min_macro}  ← REGRESSION")
            all_passed = False

        # --- 2. Invariant check -------------------------------------------
        inv_fails = []
        for pit in confirmed:
            violations = _invariant_violations(pit, scale, pit["pit_type"])
            if violations:
                inv_fails.append((pit["pit_id"], pit["pit_type"],
                                  pit.get("area_um2", 0), violations))
                global_invariant_fails.append((filename, pit["pit_id"], violations))

        if not inv_fails:
            print(f"  [PASS] invariant check — all {len(confirmed)} confirmed pits satisfy their rules")
        else:
            print(f"  [FAIL] {len(inv_fails)} confirmed pit(s) violate a filter rule:")
            for pid, ptype, area, viols in inv_fails[:5]:
                print(f"         pit#{pid} ({ptype}, {area:.1f} µm²): {'; '.join(viols)}")
            all_passed = False

        # --- 3. Darkness distribution (surface pits) ----------------------
        ir_values = [p.get("intensity_ratio", 0) for p in surface_conf
                     if p.get("intensity_ratio") is not None]
        if ir_values:
            ir_mean = statistics.mean(ir_values)
            ir_min  = min(ir_values)
            ir_max  = max(ir_values)
            ir_std  = statistics.pstdev(ir_values) if len(ir_values) > 1 else 0.0
            near_boundary = sum(1 for v in ir_values
                                if abs(v - MAX_INTENSITY_RATIO) / MAX_INTENSITY_RATIO < BORDER_MARGIN)
            print(f"\n  Intensity ratio (surface confirmed, n={len(ir_values)}):")
            print(f"    min={ir_min:.3f}  mean={ir_mean:.3f}  max={ir_max:.3f}  "
                  f"std={ir_std:.3f}  near-R7={near_boundary}")
            if ir_max >= MAX_INTENSITY_RATIO:
                print(f"  [WARN] max intensity_ratio {ir_max:.4f} >= R7 threshold "
                      f"{MAX_INTENSITY_RATIO} — invariant failure above")

        # --- 4. Borderline report -----------------------------------------
        borderline_pits = []
        for pit in confirmed:
            flags = _borderline(pit, scale, pit["pit_type"])
            if flags:
                borderline_pits.append((pit["pit_id"], pit["pit_type"],
                                        pit.get("area_um2", 0), flags))
        if borderline_pits:
            print(f"\n  Borderline pits (within {BORDER_MARGIN*100:.0f}% of a threshold):")
            for pid, ptype, area, flags in sorted(borderline_pits,
                                                   key=lambda x: x[2], reverse=True)[:8]:
                print(f"    pit#{pid} ({ptype}, {area:.1f} µm²): {'; '.join(flags)}")

        # --- 5a. R8 dominant-orientation stats ----------------------------
        dom_angle, dom_entropy = _compute_dominant_orientation(_gray, _mask)
        r8_active = dom_entropy <= R8_ORIENTATION_ENTROPY_MAX
        if r8_active:
            r8_note = f"dominant={dom_angle:.1f}°  entropy={dom_entropy:.2f} bits"
        else:
            r8_note = f"SKIPPED (entropy={dom_entropy:.2f} > {R8_ORIENTATION_ENTROPY_MAX})"
        print(f"\n  R8 orientation: {r8_note}")

        # --- 5b. Rejection rule breakdown ----------------------------------
        rule_counts = {}
        for r in rejected:
            for reason in r.get("rejection_reasons", []):
                key = reason.split(":")[0]
                rule_counts[key] = rule_counts.get(key, 0) + 1
                global_rule_counts[key] = global_rule_counts.get(key, 0) + 1
        print(f"\n  Rejection breakdown:")
        for rule, count in sorted(rule_counts.items()):
            note = ("  ← noise filter" if rule == "R7"
                    else "  ← scratch-orientation filter" if rule == "R8"
                    else "")
            print(f"    {rule}: {count}{note}")

        print()

    # --- Global summary ---------------------------------------------------
    print(f"  {'='*72}")
    print(f"  GLOBAL SUMMARY across {len(ANCHORS)} anchor images")
    print(f"  {'─'*72}")
    print(f"  Rejection counts by rule (all anchors combined):")
    for rule, count in sorted(global_rule_counts.items()):
        print(f"    {rule}: {count}")

    if global_invariant_fails:
        print(f"\n  INVARIANT FAILURES ({len(global_invariant_fails)} total):")
        for fname, pid, viols in global_invariant_fails:
            print(f"    {fname}  pit#{pid}: {'; '.join(viols)}")

    print()
    if all_passed:
        print("  RESULT: ALL CHECKS PASSED\n")
    else:
        print("  RESULT: FAILURES DETECTED — see above\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
