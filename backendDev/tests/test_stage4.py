"""
Test — Stage 4: Density Calculation

Runs Stages 1 → 2 → 3 → 4 on both sample images, prints all three density
metrics plus the 5×5 zone grid, saves debug visualisations, and reports
PASS / FAIL.

PASS criteria
-------------
1. All three density metrics are non-zero for both images.
2. Linear pit density for CR3-7 is within 40% of 30 pits/cm
   (acceptable range: 18–42 pits/cm).
3. Linear pit density for CR3-9 is within 40% of 29.4 pits/cm
   (acceptable range: 17.6–41.2 pits/cm).
"""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage1_scale_bar    import detect_scale_bar
from pipeline.stage2_roi          import extract_roi
from pipeline.stage3_pit_detection import detect_pits
from pipeline.stage4_density      import calculate_density

ROOT      = os.path.join(os.path.dirname(__file__), "..")
DEBUG_DIR = os.path.join(ROOT, "outputs", "debug")

# ---------------------------------------------------------------------------
# Ground-truth reference values from slide deck
# ---------------------------------------------------------------------------
GROUND_TRUTH = {
    "CR3-7": {"linear_per_cm": 30.0,  "tolerance_pct": 40.0},
    "CR3-9": {"linear_per_cm": 29.4,  "tolerance_pct": 40.0},
}

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
TEST_CASES = [
    (
        os.path.join("data", "raw", "cr3-9_c_side_overview003.jpg"),
        os.path.join("data", "raw", "cr3-9 c side overview003.jpg"),
        1000.0,
        "test_stage4_cr3-9.jpg",
        "CR3-9",
    ),
    (
        os.path.join("data", "raw", "CR3-7_c-side_BF002.jpg"),
        None,
        150.0,
        "test_stage4_cr3-7.jpg",
        "CR3-7",
    ),
]


def _resolve_image_path(primary_rel, fallback_rel):
    for rel in (primary_rel, fallback_rel):
        if rel is None:
            continue
        abs_path = os.path.join(ROOT, rel)
        if os.path.exists(abs_path):
            return abs_path
    return None


def _run_stage1(image_path, expected_um):
    try:
        scale, _ = detect_scale_bar(image_path)
        return scale, "OCR"
    except RuntimeError as exc:
        if "pytesseract" in str(exc) or "µm value" in str(exc):
            scale, _ = detect_scale_bar(image_path,
                                        um_value_override=expected_um)
            return scale, f"override={expected_um:.0f}µm"
        raise


def _run_one(primary_rel, fallback_rel, expected_um, debug_filename, label):
    result = {
        "label":           label,
        "filename":        None,
        "scale_um_per_px": None,
        "n_pits":          None,
        "density_metrics": None,
        "zone_grid":       None,
        "hotspot_zone":    None,
        "status":          "FAIL",
        "failures":        [],
        "message":         "",
    }

    image_path = _resolve_image_path(primary_rel, fallback_rel)
    if image_path is None:
        result["message"] = (
            f"image not found — tried {os.path.join(ROOT, primary_rel)}"
            + (f" / {os.path.join(ROOT, fallback_rel)}" if fallback_rel else "")
        )
        return result

    result["filename"] = os.path.basename(image_path)
    debug_out = os.path.join(DEBUG_DIR, debug_filename)

    # --- Stage 1 -----------------------------------------------------------
    try:
        scale_um_per_px, scale_source = _run_stage1(image_path, expected_um)
    except RuntimeError as exc:
        result["message"] = f"Stage 1 failed: {exc}"
        return result
    result["scale_um_per_px"] = scale_um_per_px

    # --- Stage 2 -----------------------------------------------------------
    try:
        specimen_mask, _, roi_dims, _ = extract_roi(image_path, scale_um_per_px)
    except Exception as exc:
        result["message"] = f"Stage 2 failed: {exc}"
        return result

    # --- Stage 3 -----------------------------------------------------------
    try:
        confirmed_pits, _, _ = detect_pits(
            image_path, scale_um_per_px, specimen_mask, roi_dims
        )
    except Exception as exc:
        result["message"] = f"Stage 3 failed: {exc}"
        return result
    result["n_pits"] = len(confirmed_pits)

    # --- Stage 4 -----------------------------------------------------------
    try:
        density_metrics, zone_grid, hotspot_zone, debug_vis = calculate_density(
            image_path, confirmed_pits, roi_dims, specimen_mask, scale_um_per_px
        )
    except Exception as exc:
        result["message"] = f"Stage 4 failed: {exc}"
        return result

    os.makedirs(DEBUG_DIR, exist_ok=True)
    cv2.imwrite(debug_out, debug_vis)

    result["density_metrics"] = density_metrics
    result["zone_grid"]       = zone_grid
    result["hotspot_zone"]    = hotspot_zone

    # --- PASS / FAIL checks ------------------------------------------------
    failures = []
    dm = density_metrics

    # Check 1: macro pit count must be > 0
    if dm["pit_count_macro"] == 0:
        failures.append("macro pit count = 0")

    # Check 2: all three full-set metrics must be non-zero
    zero_metrics = []
    if dm["pit_density_all_per_cm"] == 0:
        zero_metrics.append("pit_density_all_per_cm")
    if dm["areal_all_pits_per_mm2"] == 0:
        zero_metrics.append("areal_all_pits_per_mm2")
    if dm["pit_coverage_all_pct"] == 0:
        zero_metrics.append("pit_coverage_all_pct")
    if zero_metrics:
        failures.append(f"full-set metrics are zero: {zero_metrics}")

    # Check 3: full density >= macro density (sanity)
    if dm["pit_density_all_per_cm"] < dm["pit_density_macro_per_cm"]:
        failures.append(
            f"full density {dm['pit_density_all_per_cm']:.2f} "
            f"< macro density {dm['pit_density_macro_per_cm']:.2f}  (impossible)"
        )

    # Check 4: macro linear density within 40% of ground truth
    if label in GROUND_TRUTH:
        gt_val = GROUND_TRUTH[label]["linear_per_cm"]
        tol    = GROUND_TRUTH[label]["tolerance_pct"] / 100.0
        lo, hi = gt_val * (1 - tol), gt_val * (1 + tol)
        actual = dm["pit_density_macro_per_cm"]
        if not (lo <= actual <= hi):
            failures.append(
                f"macro density {actual:.1f} pits/cm outside "
                f"±{GROUND_TRUTH[label]['tolerance_pct']:.0f}% of "
                f"GT {gt_val:.1f} pits/cm  (range {lo:.1f}–{hi:.1f})"
            )

    result["failures"] = failures
    if failures:
        result["message"] = "  |  ".join(failures)
        result["status"]  = "FAIL"
    else:
        result["status"]  = "PASS"
        result["message"] = (
            f"macro={dm['pit_density_macro_per_cm']:.1f}p/cm  "
            f"full={dm['pit_density_all_per_cm']:.1f}p/cm  "
            f"cover={dm['pit_coverage_macro_pct']:.3f}%  "
            f"debug → {debug_out}"
        )

    return result


def _print_zone_grid(zone_grid, hotspot_zone, label, title="Zone grid (macro pits only)"):
    """Print the 5×5 zone grid as a formatted table."""
    print(f"\n  {title} — {label}  (hotspot ★ = row {hotspot_zone[0]}, col {hotspot_zone[1]})")
    rows, cols = zone_grid.shape
    # Column header
    header = "       " + "  ".join(f"C{col}" for col in range(cols))
    print(f"  {header}")
    print(f"  {'  ' + '-' * (len(header) - 2)}")
    for row in range(rows):
        cells = []
        for col in range(cols):
            count = int(zone_grid[row, col])
            marker = "★" if (row, col) == hotspot_zone else " "
            cells.append(f"{count:2d}{marker}")
        print(f"    R{row} | " + "  ".join(cells))


def main():
    results = []
    for primary_rel, fallback_rel, expected_um, debug_fn, label in TEST_CASES:
        result = _run_one(primary_rel, fallback_rel, expected_um, debug_fn, label)
        results.append(result)

    # --- Per-image detail --------------------------------------------------
    for res in results:
        print()
        print(f"  {'='*60}")
        print(f"  {res['label']}  —  {res['filename'] or '(not found)'}")
        print(f"  {'='*60}")

        if res["density_metrics"] is None:
            print(f"  {res['message']}")
            continue

        dm = res["density_metrics"]
        gt = GROUND_TRUTH.get(res["label"], {})

        def _v(val, fmt):
            return format(val, fmt) if val is not None else "—"

        gt_str = f"  [GT: {gt['linear_per_cm']:.1f}±{gt['tolerance_pct']:.0f}%]" if gt else ""
        rows = [
            ("Scale (µm/px)",             _v(res["scale_um_per_px"], ".4f")),
            ("Confirmed pits (all)",       _v(dm["n_confirmed"], "d")),
            ("  macro / micro",            f"{dm['n_macro']} / {dm['n_micro']}"),
            ("  surface / edge",           f"{dm['n_surface']} / {dm['n_edge']}"),
            ("ROI width (µm)",             _v(dm["roi_width_um"], ".1f")),
            ("ROI height (µm)",            _v(dm["roi_height_um"], ".1f")),
            ("── Metric 1: Linear density", ""),
            ("  MACRO (≥1500µm²) pits/cm", _v(dm["pit_density_macro_per_cm"], ".2f") + gt_str),
            ("  Full set          pits/cm", _v(dm["pit_density_all_per_cm"],   ".2f")),
            ("  Surface           pits/cm", _v(dm["linear_surface_per_cm"],    ".2f")),
            ("  Edge              pits/cm", _v(dm["linear_edge_per_cm"],       ".2f")),
            ("── Metric 2: Areal density",  ""),
            ("  MACRO pits/mm²",            _v(dm["areal_macro_per_mm2"],      ".4f")),
            ("  Full set pits/mm²",         _v(dm["areal_all_pits_per_mm2"],   ".4f")),
            ("── Metric 3: Coverage",       ""),
            ("  MACRO pits (%)",            _v(dm["pit_coverage_macro_pct"],   ".4f")),
            ("  Full set (%)",              _v(dm["pit_coverage_all_pct"],     ".4f")),
            ("Result",                      res["status"]),
        ]
        col_w = max(len(row[0]) for row in rows) + 2
        for key, val in rows:
            print(f"  {key:<{col_w}}: {val}")

        _print_zone_grid(res["zone_grid"], res["hotspot_zone"], res["label"])
        # Also print the all-pits reference grid if available.
        zone_grid_all = (res["density_metrics"] or {}).get("zone_grid_all")
        if zone_grid_all is not None:
            import numpy as np
            hotspot_all = tuple(int(i) for i in np.unravel_index(
                zone_grid_all.argmax(), zone_grid_all.shape))
            _print_zone_grid(zone_grid_all, hotspot_all, res["label"],
                             title="Zone grid (all pits, reference)")

    # --- Overall pass/fail -------------------------------------------------
    print()
    print("  " + "-" * 60)
    all_passed = True
    for res in results:
        print(f"  {res['status']} — {res['label']}: {res['message']}")
        if res["status"] != "PASS":
            all_passed = False
    print()

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
