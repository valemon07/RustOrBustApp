"""
Pipeline Consistency Check

Runs the full Stage 1→2→3→4 pipeline on every JPEG in data/raw/,
collects metrics per image, flags anomalies, prints a summary table
and per-class statistics, and writes a CSV.

Usage
-----
    python tests/test_pipeline_consistency.py

Debug images are saved only for flagged images to keep runtime manageable.
"""

import csv
import glob
import math
import os
import re
import statistics
import sys

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage1_scale_bar     import detect_scale_bar, ScaleBarNotFoundError
from pipeline.stage2_roi           import extract_roi
from pipeline.stage3_pit_detection import detect_pits
from pipeline.stage4_density       import calculate_density
from pipeline.config               import MANUAL_SCALE_OVERRIDES, NO_SCALE_BAR_IMAGES, EXCLUDED_SPECIMENS

ROOT        = os.path.join(os.path.dirname(__file__), "..")
RAW_DIR     = os.path.join(ROOT, "data", "raw")
DEBUG_DIR   = os.path.join(ROOT, "outputs", "debug", "flagged")
CSV_OUT     = os.path.join(ROOT, "outputs", "csv", "consistency_check.csv")

# ---------------------------------------------------------------------------
# Specimen classification
# ---------------------------------------------------------------------------
_SPECIMEN_LABELS = {
    "CR3-1": "moderate",
    "CR3-3": "moderate",
    "CR3-7": "severe",
    "CR3-8": "severe",
    "CR3-9": "severe",
}


def _extract_specimen_id(filename):
    """Return e.g. 'CR3-7' from any filename, or None."""
    match = re.search(r"CR3-\d+", filename, re.IGNORECASE)
    if match:
        return match.group(0).upper()
    return None


def _classify(specimen_id):
    if specimen_id is None:
        return "unknown"
    return _SPECIMEN_LABELS.get(specimen_id, "unknown")


# ---------------------------------------------------------------------------
# Flag criteria
# ---------------------------------------------------------------------------
SCALE_MIN        = 0.5    # µm/px — below this suggests OCR misread
SCALE_MAX        = 10.0   # µm/px — above this suggests OCR misread
ROI_MIN_UM       = 200.0  # µm — ROI dimension floor
MACRO_MIN_COUNT  = 1      # at least one macro pit expected


def _flag_reasons(row):
    """Return list of reason strings for a result row; empty = clean."""
    reasons = []
    if row.get("excluded"):
        reasons.append("excluded_specimen")
        return reasons
    if row.get("no_scale_bar"):
        reasons.append("no_scale_bar_found")
        return reasons
    if row["error"]:
        reasons.append(f"exception: {row['error']}")
        return reasons
    scale = row["scale_um_per_px"]
    if scale is not None and not (SCALE_MIN <= scale <= SCALE_MAX):
        reasons.append(f"scale {scale:.4f} outside [{SCALE_MIN},{SCALE_MAX}]")
    if row["macro_pit_count"] == 0:
        reasons.append("macro_pit_count=0")
    if row["roi_width_um"] is not None and row["roi_width_um"] < ROI_MIN_UM:
        reasons.append(f"roi_width {row['roi_width_um']:.0f}um < {ROI_MIN_UM:.0f}")
    if row["roi_height_um"] is not None and row["roi_height_um"] < ROI_MIN_UM:
        reasons.append(f"roi_height {row['roi_height_um']:.0f}um < {ROI_MIN_UM:.0f}")
    return reasons


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def _run_pipeline(image_path):
    """
    Run Stages 1–4 on one image.

    Returns a dict of collected values; 'error' is None on success.
    """
    filename    = os.path.basename(image_path)
    specimen_id = _extract_specimen_id(filename)
    label       = _classify(specimen_id)

    result = {
        "filename":           filename,
        "specimen_id":        specimen_id or "unknown",
        "label":              label,
        "scale_um_per_px":    None,
        "scale_bar_um":       None,
        "roi_width_um":       None,
        "roi_height_um":      None,
        "macro_pit_count":    0,
        "macro_density_per_cm": 0.0,
        "full_pit_count":     0,
        "full_density_per_cm": 0.0,
        "no_scale_bar":       False,
        "excluded":           False,
        "error":              None,
    }

    # Excluded specimens are skipped entirely before any processing.
    if specimen_id in EXCLUDED_SPECIMENS:
        result["excluded"] = True
        return result

    try:
        # Stage 1 — detect scale bar.  Apply manual override when known.
        stem = os.path.splitext(filename)[0]
        if stem in NO_SCALE_BAR_IMAGES:
            result["no_scale_bar"] = True
            return result
        um_override = MANUAL_SCALE_OVERRIDES.get(stem)
        try:
            scale_um_per_px, _ = detect_scale_bar(image_path,
                                                   um_value_override=um_override)
        except ScaleBarNotFoundError:
            result["no_scale_bar"] = True
            return result
        result["scale_um_per_px"] = scale_um_per_px

        # Stage 2
        specimen_mask, _, roi_dims, _ = extract_roi(image_path, scale_um_per_px)
        result["roi_width_um"]  = roi_dims["width_um"]
        result["roi_height_um"] = roi_dims["height_um"]

        # Stage 3
        confirmed_pits, _, _ = detect_pits(
            image_path, scale_um_per_px, specimen_mask, roi_dims
        )
        result["full_pit_count"] = len(confirmed_pits)

        # Stage 4 — only need the metrics dict; skip debug vis for speed
        density_metrics, _, _, _ = calculate_density(
            image_path, confirmed_pits, roi_dims, specimen_mask, scale_um_per_px
        )
        result["macro_pit_count"]      = density_metrics["pit_count_macro"]
        result["macro_density_per_cm"] = density_metrics["pit_density_macro_per_cm"]
        result["full_density_per_cm"]  = density_metrics["pit_density_all_per_cm"]

    except Exception as exc:
        result["error"] = str(exc)

    return result


def _save_flagged_debug(image_path, flag_tag):
    """Run pipeline again for a flagged image and save the Stage 4 debug vis."""
    try:
        scale_um_per_px, _ = detect_scale_bar(image_path)
        specimen_mask, _, roi_dims, _ = extract_roi(image_path, scale_um_per_px)
        confirmed_pits, _, _ = detect_pits(
            image_path, scale_um_per_px, specimen_mask, roi_dims
        )
        _, _, _, debug_vis = calculate_density(
            image_path, confirmed_pits, roi_dims, specimen_mask, scale_um_per_px
        )
        os.makedirs(DEBUG_DIR, exist_ok=True)
        out_name = f"{flag_tag}_{os.path.basename(image_path)}"
        out_path = os.path.join(DEBUG_DIR, out_name)
        cv2.imwrite(out_path, debug_vis)
        return out_path
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _mean_std(values):
    if not values:
        return None, None
    mean = statistics.mean(values)
    std  = statistics.pstdev(values) if len(values) > 1 else 0.0
    return mean, std


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _cr3_diagnostic():
    """
    Verbose Stage 1 + Stage 2 diagnostic for a representative CR3-3 darkfield
    image.  Prints blob-level detail so we can see why scale / ROI go wrong.
    """
    target = "cr3-3_ci-side_DF001.jpg"
    path   = os.path.join(RAW_DIR, target)
    if not os.path.exists(path):
        print(f"  [diagnostic] {target} not found — skipping")
        return

    print(f"\n{'='*60}")
    print(f"  CR3-3 Diagnostic: {target}")
    print(f"{'='*60}")

    import cv2 as _cv2
    img = _cv2.imread(path)
    if img is None:
        print("  Cannot load image.")
        return
    h, w = img.shape[:2]
    print(f"  Image size       : {w} x {h} px")

    # Stage 1 verbose — prints search region, green pixel count, all blobs
    try:
        scale, _ = detect_scale_bar(path, verbose=True)
        print(f"  Scale result     : {scale:.4f} µm/px")
    except ScaleBarNotFoundError as exc:
        print(f"  Stage 1 FAILED   : no_scale_bar_found ({exc})")
        scale = None
    except RuntimeError as exc:
        print(f"  Stage 1 FAILED   : {exc}")
        scale = None

    if scale is None:
        print("  Skipping Stage 2 (no valid scale).")
        print(f"{'='*60}\n")
        return

    # Stage 2 — print ROI and pit counts
    try:
        _, _, roi_dims, _ = extract_roi(path, scale)
        print(f"  ROI              : {roi_dims['width_px']} x {roi_dims['height_px']} px"
              f"  ({roi_dims['width_um']:.0f} x {roi_dims['height_um']:.0f} µm)")
        print(f"  surface_pits     : {len(roi_dims['surface_pits'])}")
        print(f"  edge_pits        : {len(roi_dims['edge_pits'])}")
    except Exception as exc:
        print(f"  Stage 2 FAILED   : {exc}")

    print(f"{'='*60}\n")


def main():
    # --- CR3-3 diagnostic (runs before main loop) -------------------------
    _cr3_diagnostic()

    # --- Discover images ---------------------------------------------------
    pattern_lower = os.path.join(RAW_DIR, "*.jpg")
    pattern_upper = os.path.join(RAW_DIR, "*.jpeg")
    image_paths   = sorted(
        glob.glob(pattern_lower) + glob.glob(pattern_upper)
    )
    if not image_paths:
        print(f"No JPEG images found in {RAW_DIR}")
        sys.exit(1)

    print(f"\nFound {len(image_paths)} images in {RAW_DIR}")
    print("Running full pipeline on each …\n")

    # --- Run pipeline on each image ----------------------------------------
    rows = []
    for idx, image_path in enumerate(image_paths, 1):
        name = os.path.basename(image_path)
        print(f"  [{idx:2d}/{len(image_paths)}] {name} … ", end="", flush=True)
        row = _run_pipeline(image_path)
        reasons = _flag_reasons(row)
        row["_flag_reasons"] = reasons
        rows.append(row)
        status = "OK" if not reasons else f"FLAGGED ({'; '.join(reasons)})"
        print(status)

    # --- Save flagged debug images -----------------------------------------
    flagged_rows = [r for r in rows if r["_flag_reasons"]]
    if flagged_rows:
        print(f"\nSaving debug images for {len(flagged_rows)} flagged image(s) …")
        for idx, row in enumerate(flagged_rows, 1):
            path = os.path.join(RAW_DIR, row["filename"])
            tag  = f"flag{idx:02d}"
            out  = _save_flagged_debug(path, tag)
            if out:
                print(f"  Saved: {out}")

    # --- Write CSV ---------------------------------------------------------
    os.makedirs(os.path.dirname(CSV_OUT), exist_ok=True)
    csv_fields = [
        "filename", "specimen_id", "label",
        "scale_um_per_px", "scale_bar_um",
        "roi_width_um", "roi_height_um",
        "macro_pit_count", "macro_density_per_cm",
        "full_pit_count", "full_density_per_cm",
        "flagged", "flag_reasons", "error",
    ]
    with open(CSV_OUT, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=csv_fields)
        writer.writeheader()
        for row in rows:
            reasons = row["_flag_reasons"]
            writer.writerow({
                "filename":             row["filename"],
                "specimen_id":          row["specimen_id"],
                "label":                row["label"],
                "scale_um_per_px":      row["scale_um_per_px"] or "",
                "scale_bar_um":         row["scale_bar_um"]    or "",
                "roi_width_um":         row["roi_width_um"]    or "",
                "roi_height_um":        row["roi_height_um"]   or "",
                "macro_pit_count":      row["macro_pit_count"],
                "macro_density_per_cm": row["macro_density_per_cm"],
                "full_pit_count":       row["full_pit_count"],
                "full_density_per_cm":  row["full_density_per_cm"],
                "flagged":              "YES" if reasons else "NO",
                "flag_reasons":         "; ".join(reasons),
                "error":                row["error"] or "",
            })
    print(f"\nCSV written: {CSV_OUT}")

    # --- Print results table -----------------------------------------------
    print()
    col_w = 36
    col_spec = 6
    header = (
        f"  {'Filename':<{col_w}}  "
        f"{'ID':<{col_spec}}  "
        f"{'Label':>8}  "
        f"{'Scale':>7}  "
        f"{'ROI W':>7}  "
        f"{'ROI H':>7}  "
        f"{'Macro':>6}  "
        f"{'Mac p/cm':>9}  "
        f"{'All':>5}  "
        f"{'All p/cm':>9}"
    )
    divider = "  " + "-" * (len(header) - 2)
    print(header)
    print(divider)

    for row in rows:
        reasons = row["_flag_reasons"]
        flag_marker = "***" if reasons else "   "

        def _f(val, fmt):
            return format(val, fmt) if val is not None else "—"

        print(
            f"{flag_marker} "
            f"{row['filename']:<{col_w}}  "
            f"{row['specimen_id']:<{col_spec}}  "
            f"{row['label']:>8}  "
            f"{_f(row['scale_um_per_px'], '7.4f')}  "
            f"{_f(row['roi_width_um'],    '7.0f')}  "
            f"{_f(row['roi_height_um'],   '7.0f')}  "
            f"{row['macro_pit_count']:>6}  "
            f"{row['macro_density_per_cm']:>9.2f}  "
            f"{row['full_pit_count']:>5}  "
            f"{row['full_density_per_cm']:>9.2f}"
            + (f"  FLAGGED: {'; '.join(reasons)}" if reasons else "")
        )

    print(divider)

    # --- Summary section ---------------------------------------------------
    print()
    print("  SUMMARY")
    print("  " + "─" * 58)

    excluded       = [r for r in rows if r.get("excluded")]
    in_scope       = [r for r in rows if not r.get("excluded")]
    successful     = [r for r in in_scope if not r["error"] and not r.get("no_scale_bar")]
    failed         = [r for r in in_scope if r["error"]]
    no_scale_bar   = [r for r in in_scope if r.get("no_scale_bar")]

    print(f"  Images in dataset : {len(rows)}")
    print(f"  Excluded (out of scope): {len(excluded)}")
    if excluded:
        specs = sorted(set(r["specimen_id"] for r in excluded))
        print(f"    specimens: {specs}")
    print(f"  In-scope images  : {len(in_scope)}")
    print(f"  Successful       : {len(successful)}")
    print(f"  No scale bar     : {len(no_scale_bar)}")
    if no_scale_bar:
        for r in no_scale_bar:
            print(f"    ○ {r['filename']}")
    print(f"  Errors (exception): {len(failed)}")
    if failed:
        for r in failed:
            print(f"    ✗ {r['filename']}: {r['error']}")

    print(f"  Flagged total    : {len(flagged_rows)}")
    # Breakdown by reason category
    reason_counts = {}
    for row in flagged_rows:
        for reason in row["_flag_reasons"]:
            key = reason.split(" ")[0]   # first word as category
            reason_counts[key] = reason_counts.get(key, 0) + 1
    for key, count in sorted(reason_counts.items()):
        print(f"    {key}: {count}")

    # Class distribution (in-scope successful only)
    print()
    label_counts = {}
    for row in successful:
        label_counts[row["label"]] = label_counts.get(row["label"], 0) + 1
    print("  Class distribution (in-scope successful):")
    for lbl, count in sorted(label_counts.items()):
        print(f"    {lbl}: {count}")

    # Per-class statistics
    print()
    print("  Per-class statistics (in-scope successful images):")
    for lbl in sorted(set(r["label"] for r in successful)):
        subset = [r for r in successful if r["label"] == lbl]
        densities = [r["macro_density_per_cm"] for r in subset]
        counts    = [r["macro_pit_count"]      for r in subset]
        scales    = [r["scale_um_per_px"]      for r in subset if r["scale_um_per_px"]]
        mean_d, std_d = _mean_std(densities)
        mean_c, std_c = _mean_std(counts)
        mean_s, std_s = _mean_std(scales)
        print(f"\n    [{lbl}]  n={len(subset)}")
        print(f"      macro density  : {mean_d:.2f} ± {std_d:.2f} pits/cm")
        print(f"      macro pit count: {mean_c:.1f} ± {std_c:.1f}")
        print(f"      scale (um/px)  : {mean_s:.4f} ± {std_s:.4f}")

    # Overall density statistics
    all_densities = [r["macro_density_per_cm"] for r in successful]
    mean_all, std_all = _mean_std(all_densities)
    min_d = min(all_densities) if all_densities else None
    max_d = max(all_densities) if all_densities else None
    print()
    print("  Overall macro density (all successful images):")
    if mean_all is not None:
        print(f"    mean  : {mean_all:.2f} pits/cm")
        print(f"    std   : {std_all:.2f} pits/cm")
        print(f"    min   : {min_d:.2f} pits/cm")
        print(f"    max   : {max_d:.2f} pits/cm")

    # In-scope specimens where ALL images were flagged
    specimen_ids = sorted(set(r["specimen_id"] for r in in_scope
                              if r["specimen_id"] != "unknown"))
    all_flagged_specimens = []
    for spec in specimen_ids:
        spec_rows = [r for r in in_scope if r["specimen_id"] == spec]
        if all(r["_flag_reasons"] for r in spec_rows):
            all_flagged_specimens.append(spec)
    if all_flagged_specimens:
        print()
        print("  *** All images flagged for specimens:", all_flagged_specimens)

    print()


if __name__ == "__main__":
    main()
