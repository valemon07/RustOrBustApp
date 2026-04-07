"""
Stage 3 Threshold Calibration

Sweeps a range of minimum pit area thresholds across both test images and
reports how each value compares against the human-expert ground truth linear
density (pits/cm) from the slide deck.

Usage
-----
    python tests/calibrate_stage3_threshold.py

No arguments needed.  The script runs automatically.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage1_scale_bar     import detect_scale_bar
from pipeline.stage2_roi           import extract_roi
import pipeline.stage3_pit_detection as stage3_module
from pipeline.stage3_pit_detection import detect_pits

ROOT = os.path.join(os.path.dirname(__file__), "..")

# ---------------------------------------------------------------------------
# Threshold values to sweep
# ---------------------------------------------------------------------------
THRESHOLDS_UM2 = [80, 150, 250, 350, 500, 750, 1000, 1500, 2000]

# ---------------------------------------------------------------------------
# Ground truth from slide deck
# ---------------------------------------------------------------------------
GROUND_TRUTH = {
    "CR3-7": 30.0,    # pits/cm  severe
    "CR3-9": 29.4,    # pits/cm  severe
}
GT_TOLERANCE = 0.40   # ±40%

# ---------------------------------------------------------------------------
# Test images
# ---------------------------------------------------------------------------
IMAGES = [
    (
        "CR3-9",
        os.path.join("data", "raw", "cr3-9 c side overview003.jpg"),
        1000.0,
    ),
    (
        "CR3-7",
        os.path.join("data", "raw", "CR3-7_c-side_BF002.jpg"),
        150.0,
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve(rel_path):
    abs_path = os.path.join(ROOT, rel_path)
    return abs_path if os.path.exists(abs_path) else None


def _run_stage1(image_path, expected_um):
    try:
        scale, _, _ = detect_scale_bar(image_path)
        return scale
    except RuntimeError as exc:
        if "pytesseract" in str(exc) or "µm value" in str(exc):
            scale, _, _ = detect_scale_bar(image_path,
                                        um_value_override=expected_um)
            return scale
        raise


def _pipeline_to_stage3(image_path, expected_um, min_area_override_um2):
    """
    Run Stages 1–3 with a temporary override of both area floor constants in
    stage3_pit_detection.  Returns (scale_um_per_px, roi_width_um, n_confirmed).
    """
    scale_um_per_px = _run_stage1(image_path, expected_um)
    specimen_mask, _, roi_dims, _ = extract_roi(image_path, scale_um_per_px)

    # Temporarily patch the two module-level constants that drive R1 and R5.
    original_r1    = stage3_module.MIN_PIT_AREA_UM2
    original_coeff = stage3_module.SCALE_AWARE_AREA_COEFF

    # Force both floors to the override value regardless of scale:
    #   R1 floor = override
    #   R5 effective_min = max(override, coeff/scale)
    # Setting coeff = override * scale makes max(override, coeff/scale) = override.
    stage3_module.MIN_PIT_AREA_UM2       = float(min_area_override_um2)
    stage3_module.SCALE_AWARE_AREA_COEFF = float(min_area_override_um2) * scale_um_per_px

    try:
        confirmed_pits, _, _ = detect_pits(
            image_path, scale_um_per_px, specimen_mask, roi_dims
        )
    finally:
        stage3_module.MIN_PIT_AREA_UM2       = original_r1
        stage3_module.SCALE_AWARE_AREA_COEFF = original_coeff

    return scale_um_per_px, roi_dims["width_um"], len(confirmed_pits)


def _linear_density(n_pits, roi_width_um):
    return n_pits / (roi_width_um / 10_000.0)


def _gt_bounds(label):
    gt  = GROUND_TRUTH[label]
    return gt * (1 - GT_TOLERANCE), gt * (1 + GT_TOLERANCE)


def _passes(density, label):
    lo, hi = _gt_bounds(label)
    return lo <= density <= hi


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # --- Pre-flight: resolve image paths and run Stages 1-2 once -----------
    image_data = {}   # label → (image_path, scale_um_per_px, roi_width_um)
    print()
    print("  Pre-flight: running Stages 1-2 on both images …")
    for label, rel_path, expected_um in IMAGES:
        image_path = _resolve(rel_path)
        if image_path is None:
            print(f"  ERROR: image not found for {label}: {rel_path}")
            sys.exit(1)
        scale = _run_stage1(image_path, expected_um)
        _, roi_dims, _ = extract_roi(image_path, scale)[1:4]   # skip mask
        # actually need roi_dims from extract_roi — call properly
        _, _, roi_dims, _ = extract_roi(image_path, scale)
        image_data[label] = (image_path, scale, roi_dims["width_um"], expected_um)
        print(f"    {label}: scale={scale:.4f} µm/px  "
              f"roi_width={roi_dims['width_um']:.0f} µm")
    print()

    # --- Calibration sweep -------------------------------------------------
    labels_ordered = [label for label, *_ in IMAGES]

    # Collect results first so we can mark "best row so far"
    rows = []
    for threshold in THRESHOLDS_UM2:
        row = {"threshold": threshold, "images": {}}
        for label, (image_path, scale, roi_width_um, expected_um) in image_data.items():
            _, _, n = _pipeline_to_stage3(image_path, expected_um, threshold)
            density = _linear_density(n, roi_width_um)
            ratio   = density / GROUND_TRUTH[label]
            row["images"][label] = {
                "n":       n,
                "density": density,
                "ratio":   ratio,
                "passes":  _passes(density, label),
            }
        row["both_pass"] = all(
            row["images"][lbl]["passes"] for lbl in labels_ordered
        )
        rows.append(row)

    # Identify best row (lowest threshold where both pass)
    best_threshold = None
    for row in rows:
        if row["both_pass"]:
            best_threshold = row["threshold"]
            break

    # --- Print calibration table -------------------------------------------
    gt_line = "  ".join(
        f"{lbl} GT={GROUND_TRUTH[lbl]:.1f}±{GT_TOLERANCE*100:.0f}%"
        for lbl in labels_ordered
    )
    print(f"  Ground truth: {gt_line}")
    print()

    # Header
    col_thresh = 14
    col_img    = 28   # "  pits=NNN  density=NNN.N  ratio=N.NNx  ✓/✗"
    header = (
        f"  {'Min area (µm²)':<{col_thresh}}"
        + "  ".join(f"{'  ' + lbl + ' ':^{col_img}}" for lbl in labels_ordered)
        + "  Status"
    )
    sub = (
        f"  {'':<{col_thresh}}"
        + "  ".join(
            f"  {'pits  density(p/cm)  ratio':^{col_img}}"
            for _ in labels_ordered
        )
    )
    divider = "  " + "-" * (len(header) - 2)
    print(header)
    print(sub)
    print(divider)

    best_seen = False
    for row in rows:
        thresh_str = str(row["threshold"])

        cells = []
        for lbl in labels_ordered:
            img = row["images"][lbl]
            tick = "✓" if img["passes"] else "✗"
            cell = (f"{img['n']:4d}  "
                    f"{img['density']:6.1f}       "
                    f"{img['ratio']:5.2f}x {tick}")
            cells.append(f"  {cell:<{col_img}}")

        if row["both_pass"] and not best_seen:
            status = "→ RECOMMENDED"
            best_seen = True
        elif row["both_pass"]:
            status = "✓"
        else:
            # Report which image fails
            failing = [lbl for lbl in labels_ordered
                       if not row["images"][lbl]["passes"]]
            status = "✗ (" + ", ".join(failing) + " fails)"

        print(f"  {thresh_str:<{col_thresh}}" + "".join(cells) + f"  {status}")

    print(divider)

    # --- Summary -----------------------------------------------------------
    print()
    if best_threshold is not None:
        print(f"  Recommended threshold: {best_threshold} µm²")
        print(f"  (lowest value where both images pass ±{GT_TOLERANCE*100:.0f}% of GT density)")
        print()

        # Detail for recommended row
        rec_row = next(r for r in rows if r["threshold"] == best_threshold)
        print(f"  At {best_threshold} µm²:")
        for lbl in labels_ordered:
            img = rec_row["images"][lbl]
            lo, hi = _gt_bounds(lbl)
            print(f"    {lbl}: {img['n']} pits  "
                  f"{img['density']:.1f} pits/cm  "
                  f"ratio={img['ratio']:.2f}x  "
                  f"(GT range {lo:.1f}–{hi:.1f})")
    else:
        print("  No threshold in the tested range produces passing results")
        print("  for both images simultaneously.")
        print()
        # Show where each image individually first passes
        for lbl in labels_ordered:
            first_pass = next(
                (r["threshold"] for r in rows if r["images"][lbl]["passes"]),
                None
            )
            print(f"    {lbl} first passes at: "
                  + (f"{first_pass} µm²" if first_pass else "never in range"))

    # --- Failure-crossover analysis ----------------------------------------
    print()
    print("  Failure crossover: which image fails first as threshold rises?")
    print()
    prev_state = {}
    for row in rows:
        for lbl in labels_ordered:
            passes_now = row["images"][lbl]["passes"]
            if prev_state.get(lbl, True) and not passes_now:
                print(f"    {lbl} drops out at threshold > "
                      f"{row['threshold']} µm²  "
                      f"(density={row['images'][lbl]['density']:.1f} pits/cm  "
                      f"ratio={row['images'][lbl]['ratio']:.2f}x)")
            prev_state[lbl] = passes_now
    print()


if __name__ == "__main__":
    main()
