"""
Test — Stage 2: ROI Extraction

Runs Stage 1 → Stage 2 on both sample images.  Prints ROI dimensions,
edge_pit and surface_pit counts, saves debug visualisations, and reports
PASS / FAIL.

PASS criterion: surface_pit count > 0 AND ROI width/height both > 500 µm.
"""

import os
import sys

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage1_scale_bar import detect_scale_bar
from pipeline.stage2_roi import extract_roi

ROOT      = os.path.join(os.path.dirname(__file__), "..")
DEBUG_DIR = os.path.join(ROOT, "outputs", "debug")

# ---------------------------------------------------------------------------
# Test cases
# Each entry: (primary_rel_path, fallback_rel_path, expected_um, debug_file, label)
# fallback_rel_path handles the "spaces vs underscores" filename variants.
# expected_um is passed to Stage 1 if OCR is unavailable.
# ---------------------------------------------------------------------------
TEST_CASES = [
    (
        os.path.join("data", "raw", "cr3-9_c_side_overview003.jpg"),
        os.path.join("data", "raw", "cr3-9 c side overview003.jpg"),
        1000.0,
        "test_stage2_cr3-9.jpg",
        "CR3-9",
    ),
    (
        os.path.join("data", "raw", "CR3-7_c-side_BF002.jpg"),
        None,
        150.0,
        "test_stage2_cr3-7.jpg",
        "CR3-7",
    ),
]

MIN_DIMENSION_UM   = 500.0
MIN_SURFACE_PITS   = 1


def _resolve_image_path(primary_rel, fallback_rel):
    """Return the first path (absolute) that exists, or None."""
    for rel in (primary_rel, fallback_rel):
        if rel is None:
            continue
        abs_path = os.path.join(ROOT, rel)
        if os.path.exists(abs_path):
            return abs_path
    return None


def _run_stage1(image_path, expected_um):
    """Run Stage 1, falling back to the known µm value if OCR fails."""
    try:
        scale_um_per_px, _, _ = detect_scale_bar(image_path)
        return scale_um_per_px, "OCR"
    except RuntimeError as exc:
        error_text = str(exc)
        if "pytesseract" in error_text or "µm value" in error_text:
            scale_um_per_px, _ = detect_scale_bar(
                image_path, um_value_override=expected_um
            )
            return scale_um_per_px, f"override={expected_um:.0f}µm"
        raise


def _run_one(primary_rel, fallback_rel, expected_um, debug_filename, label):
    """
    Run the full Stage 1 → Stage 2 pipeline on one image.

    Returns a result dict with keys:
        label, filename, scale_um_per_px,
        width_px, height_px, width_um, height_um,
        n_edge_pits, n_surface_pits,
        status, message
    """
    result = {
        "label":           label,
        "filename":        None,
        "scale_um_per_px": None,
        "width_px":        None,
        "height_px":       None,
        "width_um":        None,
        "height_um":       None,
        "n_edge_pits":     None,
        "n_surface_pits":  None,
        "status":          "FAIL",
        "message":         "",
    }

    image_path = _resolve_image_path(primary_rel, fallback_rel)
    if image_path is None:
        result["message"] = (
            f"image not found — tried:\n"
            f"  {os.path.join(ROOT, primary_rel)}"
            + (f"\n  {os.path.join(ROOT, fallback_rel)}" if fallback_rel else "")
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
        specimen_mask, specimen_crop, roi_dims, debug_vis = extract_roi(
            image_path, scale_um_per_px
        )
    except Exception as exc:
        result["message"] = f"Stage 2 failed: {exc}"
        return result

    result["width_px"]       = roi_dims["width_px"]
    result["height_px"]      = roi_dims["height_px"]
    result["width_um"]       = roi_dims["width_um"]
    result["height_um"]      = roi_dims["height_um"]
    result["n_edge_pits"]    = len(roi_dims["edge_pits"])
    result["n_surface_pits"] = len(roi_dims["surface_pits"])

    # --- Save debug image --------------------------------------------------
    os.makedirs(DEBUG_DIR, exist_ok=True)
    cv2.imwrite(debug_out, debug_vis)

    # --- PASS / FAIL -------------------------------------------------------
    dims_ok   = (roi_dims["width_um"]  > MIN_DIMENSION_UM and
                 roi_dims["height_um"] > MIN_DIMENSION_UM)
    pits_ok   = len(roi_dims["surface_pits"]) >= MIN_SURFACE_PITS

    if dims_ok and pits_ok:
        result["status"]  = "PASS"
        result["message"] = (
            f"scale={scale_um_per_px:.4f}µm/px ({scale_source})  "
            f"debug → {debug_out}"
        )
    else:
        failures = []
        if not dims_ok:
            failures.append(
                f"ROI {roi_dims['width_um']:.0f}×{roi_dims['height_um']:.0f}µm "
                f"< {MIN_DIMENSION_UM:.0f}µm minimum"
            )
        if not pits_ok:
            failures.append(
                f"surface_pit count={len(roi_dims['surface_pits'])} "
                f"(need ≥ {MIN_SURFACE_PITS})"
            )
        result["message"] = "  |  ".join(failures)

    return result


def main():
    results = []
    for primary_rel, fallback_rel, expected_um, debug_fn, label in TEST_CASES:
        result = _run_one(primary_rel, fallback_rel, expected_um, debug_fn, label)
        results.append(result)

    # --- Results table ------------------------------------------------------
    col_label = 6
    col_file  = 34
    print()
    header = (
        f"{'ID':<{col_label}}  "
        f"{'Filename':<{col_file}}  "
        f"{'µm/px':>7}  "
        f"{'W px':>6}  {'H px':>6}  "
        f"{'W µm':>7}  {'H µm':>7}  "
        f"{'edge_p':>7}  {'surf_p':>7}  "
        f"{'Result':<6}"
    )
    divider = "-" * len(header)
    print(header)
    print(divider)

    for res in results:
        def _fmt(val, fmt):
            return format(val, fmt) if val is not None else "—"

        print(
            f"{res['label']:<{col_label}}  "
            f"{(res['filename'] or '—'):<{col_file}}  "
            f"{_fmt(res['scale_um_per_px'], '.4f'):>7}  "
            f"{_fmt(res['width_px'],  'd'):>6}  "
            f"{_fmt(res['height_px'], 'd'):>6}  "
            f"{_fmt(res['width_um'],  '.0f'):>7}  "
            f"{_fmt(res['height_um'], '.0f'):>7}  "
            f"{_fmt(res['n_edge_pits'],    'd'):>7}  "
            f"{_fmt(res['n_surface_pits'], 'd'):>7}  "
            f"{res['status']:<6}"
        )

    print(divider)
    print()

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
