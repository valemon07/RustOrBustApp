"""
Test — Stage 1: Scale Bar Detection

Runs detect_scale_bar() against every entry in TEST_CASES, prints a side-by-
side results table, and saves a named debug image for each case.

If pytesseract / tesseract is unavailable the known µm value is used as a
fallback so bar detection and scale arithmetic are still exercised.
"""

import os
import sys

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline.stage1_scale_bar import detect_scale_bar

ROOT = os.path.join(os.path.dirname(__file__), "..")

# ---------------------------------------------------------------------------
# Test cases:
#   (image_rel_path, expected_um, expected_bar_px, debug_filename)
#
# expected_bar_px is the known scale-bar width in pixels for each image,
# used only as a sanity-check bound (±20 %).  Measure once from the debug
# image and record here so the check travels with the image.
# ---------------------------------------------------------------------------
TEST_CASES = [
    (
        os.path.join("data", "raw", "CR3-7 c-side BF002.jpg"),
        150.0,
        143,
        "debug_stage1_spaces.png",
    ),
    (
        os.path.join("data", "raw", "CR3-7_c-side_BF002.jpg"),
        150.0,
        143,
        "debug_stage1_underscores.png",
    ),
    (
        os.path.join("data", "raw", "cr3-9 c side overview003.jpg"),
        1000.0,
        238,
        "debug_stage1_cr3-9.png",
    ),
]


def _run_one(image_rel_path, expected_um, expected_bar_px, debug_filename):
    """
    Run Stage 1 on a single image.  Returns a result dict with keys:
        filename, scale_um_per_px, ocr_method, status, message
    """
    image_path = os.path.join(ROOT, image_rel_path)
    debug_out  = os.path.join(ROOT, "outputs", "debug", debug_filename)

    result = {
        "filename":      os.path.basename(image_path),
        "scale_um_per_px": None,
        "ocr_method":    None,
        "status":        "FAIL",
        "message":       "",
    }

    if not os.path.exists(image_path):
        result["message"] = f"image not found: {image_path}"
        return result, None

    # --- First attempt: full OCR -----------------------------------------
    try:
        scale_um_per_px, _, debug_vis = detect_scale_bar(image_path)
        result["ocr_method"] = "OCR"
    except RuntimeError as exc:
        error_text = str(exc)
        if "pytesseract" in error_text or "µm value" in error_text:
            # --- Fallback: known µm value --------------------------------
            try:
                scale_um_per_px, _, debug_vis = detect_scale_bar(
                    image_path, um_value_override=expected_um
                )
                result["ocr_method"] = f"override={expected_um:.0f}µm"
            except RuntimeError as inner_exc:
                result["message"] = str(inner_exc)
                return result, None
        else:
            result["message"] = error_text
            return result, None

    # --- Sanity checks ---------------------------------------------------
    if scale_um_per_px <= 0:
        result["message"] = f"scale_um_per_px must be positive, got {scale_um_per_px}"
        return result, debug_vis

    # Warn if the computed scale deviates more than 20 % from the value
    # derived from the known bar pixel width for this specific image.
    expected_scale = expected_um / expected_bar_px
    deviation_pct = abs(scale_um_per_px - expected_scale) / expected_scale * 100
    if deviation_pct > 20:
        result["message"] = (
            f"scale {scale_um_per_px:.4f} deviates {deviation_pct:.1f}% "
            f"from expected ~{expected_scale:.4f} "
            f"({expected_um:.0f}µm / {expected_bar_px}px)"
        )
        return result, debug_vis

    cv2.imwrite(debug_out, debug_vis)
    result["status"]        = "PASS"
    result["scale_um_per_px"] = scale_um_per_px
    result["message"]       = f"debug → {debug_out}"
    return result, debug_vis


def main():
    results = []
    for image_rel_path, expected_um, expected_bar_px, debug_filename in TEST_CASES:
        result, _ = _run_one(image_rel_path, expected_um, expected_bar_px, debug_filename)
        results.append(result)

    # --- Side-by-side results table --------------------------------------
    col_w = 34
    header = (
        f"{'Filename':<{col_w}}  "
        f"{'Scale (µm/px)':>14}  "
        f"{'µm source':>18}  "
        f"{'Result':<6}"
    )
    divider = "-" * len(header)
    print()
    print(header)
    print(divider)
    for res in results:
        scale_str = f"{res['scale_um_per_px']:.4f}" if res["scale_um_per_px"] else "—"
        ocr_str   = res["ocr_method"] or "—"
        print(
            f"{res['filename']:<{col_w}}  "
            f"{scale_str:>14}  "
            f"{ocr_str:>18}  "
            f"{res['status']:<6}"
        )
    print(divider)

    # Print per-case detail lines.
    print()
    all_passed = True
    for res in results:
        tag = res["status"]
        print(f"  {tag} — {res['filename']}: {res['message']}")
        if res["status"] != "PASS":
            all_passed = False
    print()

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
