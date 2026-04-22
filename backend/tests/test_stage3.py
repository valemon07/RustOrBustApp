"""
Test — Stage 3: Pit Detection

Runs Stages 1 → 2 → 3 on both sample images, prints a detailed summary
table, saves debug visualisations, and reports PASS / FAIL.

PASS criteria (ALL must hold for each image):
  1. confirmed pit count > 0
  2. No confirmed pit has aspect_ratio > 8.0
  3. No confirmed pit has area_um2 < 10 µm²
"""

import math
import os
import statistics
import sys
import collections

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline.stage1_scale_bar import detect_scale_bar
from backend.pipeline.stage2_roi       import extract_roi
from backend.pipeline.stage3_pit_detection import detect_pits

ROOT      = os.path.join(os.path.dirname(__file__), "..")
DEBUG_DIR = os.path.join(ROOT, "outputs", "debug")

# ---------------------------------------------------------------------------
# Test cases
# (primary_path, fallback_path, expected_um, debug_filename, label)
# ---------------------------------------------------------------------------
TEST_CASES = [
    (
        os.path.join("data", "raw", "cr3-9_c_side_overview003.jpg"),
        os.path.join("data", "raw", "cr3-9 c side overview003.jpg"),
        1000.0,
        "test_stage3_cr3-9.jpg",
        "CR3-9",
    ),
    (
        os.path.join("data", "raw", "CR3-7_c-side_BF002.jpg"),
        None,
        150.0,
        "test_stage3_cr3-7.jpg",
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
        scale, _, _ = detect_scale_bar(image_path)
        return scale, "OCR"
    except RuntimeError as exc:
        if "pytesseract" in str(exc) or "µm value" in str(exc):
            scale, _, _ = detect_scale_bar(image_path,
                                        um_value_override=expected_um)
            return scale, f"override={expected_um:.0f}µm"
        raise


def _rejection_breakdown(rejected_candidates):
    """Return a Counter keyed on the first rule tag in rejection_reasons."""
    counter = collections.Counter()
    for cand in rejected_candidates:
        for reason in cand["rejection_reasons"]:
            # reason starts with "R1:", "R2:", etc.
            tag = reason.split(":")[0]
            counter[tag] += 1
            break   # count each candidate once, under its first failed rule
    return counter


def _run_one(primary_rel, fallback_rel, expected_um, debug_filename, label):
    result = {
        "label":            label,
        "filename":         None,
        "scale_um_per_px":  None,
        "n_candidates":     None,
        "n_confirmed":      None,
        "n_rejected":       None,
        "rejection_breakdown": None,
        "mean_area_um2":    None,
        "mean_int_ratio":   None,
        "confirmed_pits":   [],     # kept for noise diagnostics
        "status":           "FAIL",
        "failures":         [],
        "message":          "",
    }

    image_path = _resolve_image_path(primary_rel, fallback_rel)
    if image_path is None:
        result["message"] = (
            f"image not found — tried {os.path.join(ROOT, primary_rel)}"
            + (f" and {os.path.join(ROOT, fallback_rel)}" if fallback_rel else "")
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

    n_candidates = (len(roi_dims["edge_pits"]) +
                    len(roi_dims["surface_pits"]))
    result["n_candidates"] = n_candidates

    # --- Stage 3 -----------------------------------------------------------
    try:
        confirmed_pits, rejected_candidates, debug_vis, _ = detect_pits(
            image_path, scale_um_per_px, specimen_mask, roi_dims
        )
    except Exception as exc:
        result["message"] = f"Stage 3 failed: {exc}"
        return result

    os.makedirs(DEBUG_DIR, exist_ok=True)
    cv2.imwrite(debug_out, debug_vis)

    result["n_confirmed"]         = len(confirmed_pits)
    result["n_rejected"]          = len(rejected_candidates)
    result["rejection_breakdown"] = _rejection_breakdown(rejected_candidates)
    result["confirmed_pits"]      = confirmed_pits

    if confirmed_pits:
        result["mean_area_um2"]  = round(
            sum(p["area_um2"]      for p in confirmed_pits) / len(confirmed_pits), 2
        )
        result["mean_int_ratio"] = round(
            sum(p["intensity_ratio"] for p in confirmed_pits) / len(confirmed_pits), 4
        )

    # --- PASS / FAIL checks ------------------------------------------------
    failures = []

    if len(confirmed_pits) == 0:
        failures.append("confirmed pit count = 0")

    bad_aspect = [p for p in confirmed_pits if p["aspect_ratio"] > 8.0]
    if bad_aspect:
        failures.append(
            f"{len(bad_aspect)} pit(s) have aspect_ratio > 8.0 "
            f"(ids: {[p['pit_id'] for p in bad_aspect]})"
        )

    bad_area = [p for p in confirmed_pits if p["area_um2"] < 10.0]
    if bad_area:
        failures.append(
            f"{len(bad_area)} pit(s) have area < 10 µm² "
            f"(ids: {[p['pit_id'] for p in bad_area]})"
        )

    # New check: high-mag noise bucket must be < 20 % of confirmed pits.
    if scale_um_per_px is not None and scale_um_per_px < 2.0 and confirmed_pits:
        hist = _diag_size_histogram(confirmed_pits)
        noise_count = hist[0][1]   # first bucket: 10–100 µm²
        noise_pct   = 100.0 * noise_count / len(confirmed_pits)
        if noise_pct >= 20.0:
            failures.append(
                f"high-mag noise bucket {noise_pct:.1f}% ≥ 20%  "
                f"({noise_count}/{len(confirmed_pits)} pits in 10–100µm²)"
            )

    # New check: scale-appropriate confirmed-pit count minimums.
    # Overview images (low-mag, ≥ 2 µm/px): need at least 50 pits.
    # High-mag images (< 2 µm/px): need at least 30 pits after stricter R5/R6.
    if scale_um_per_px is not None:
        min_count = 50 if scale_um_per_px >= 2.0 else 30
        mag_label = "overview" if scale_um_per_px >= 2.0 else "high-mag"
        if len(confirmed_pits) < min_count:
            failures.append(
                f"{mag_label} confirmed count {len(confirmed_pits)} < {min_count}"
            )

    result["failures"] = failures
    if failures:
        result["message"] = "  |  ".join(failures)
        result["status"]  = "FAIL"
    else:
        result["status"]  = "PASS"
        result["message"] = (
            f"scale={scale_um_per_px:.4f}µm/px ({scale_source})  "
            f"debug → {debug_out}"
        )

    return result


# ---------------------------------------------------------------------------
# Noise diagnostics
# ---------------------------------------------------------------------------

_AREA_BUCKETS = [
    (    10,    100, "10–100 µm²   (likely noise)"),
    (   100,    500, "100–500 µm²  (small pits)  "),
    (   500,  2_000, "500–2000 µm² (medium pits) "),
    ( 2_000, 50_000, "2000–50k µm² (large pits)  "),
]

_SHALLOW_INTENSITY_RATIO = 0.85   # pits brighter than this may be noise
_CLUSTER_RADIUS_UM       = 50.0   # neighbour search radius in µm


def _diag_size_histogram(confirmed_pits):
    """
    Return per-bucket counts and percentages of confirmed pit areas.

    Returns list of (label, count, pct_str) tuples in bucket order.
    """
    total = len(confirmed_pits)
    rows  = []
    for lo, hi, bucket_label in _AREA_BUCKETS:
        count = sum(1 for p in confirmed_pits if lo <= p["area_um2"] < hi)
        pct   = 100.0 * count / total if total > 0 else 0.0
        rows.append((bucket_label, count, f"{pct:5.1f}%"))
    return rows


def _diag_intensity(confirmed_pits):
    """
    Return (mean, std_dev, count_above_threshold) for intensity_ratio.

    A pit with intensity_ratio > _SHALLOW_INTENSITY_RATIO is nearly as
    bright as the surface and may be a very shallow feature or noise.
    """
    if not confirmed_pits:
        return None, None, 0
    ratios = [p["intensity_ratio"] for p in confirmed_pits]
    mean   = statistics.mean(ratios)
    std    = statistics.pstdev(ratios)          # population std dev
    n_shallow = sum(1 for r in ratios if r > _SHALLOW_INTENSITY_RATIO)
    return mean, std, n_shallow


def _diag_spatial_clustering(confirmed_pits, scale_um_per_px):
    """
    Return (n_clustered, n_isolated) based on a 50 µm neighbour radius.

    A pit is *clustered* if at least one other pit centroid lies within
    _CLUSTER_RADIUS_UM µm.  Otherwise it is *isolated*.
    """
    if not confirmed_pits:
        return 0, 0

    threshold_px = _CLUSTER_RADIUS_UM / scale_um_per_px
    threshold_px_sq = threshold_px ** 2

    centroids = [(p["centroid_x_px"], p["centroid_y_px"])
                 for p in confirmed_pits]

    n_clustered = 0
    for idx, (cx, cy) in enumerate(centroids):
        for jdx, (ox, oy) in enumerate(centroids):
            if idx == jdx:
                continue
            dist_sq = (cx - ox) ** 2 + (cy - oy) ** 2
            if dist_sq <= threshold_px_sq:
                n_clustered += 1
                break   # one neighbour is enough

    n_isolated = len(confirmed_pits) - n_clustered
    return n_clustered, n_isolated


def _print_diagnostics(label, confirmed_pits, scale_um_per_px):
    """Print the three noise-diagnostic sections for one image."""
    indent = "    "
    n = len(confirmed_pits)

    print(f"\n  Noise diagnostics — {label}  ({n} confirmed pits)")
    print(f"  {'-'*52}")

    if n == 0:
        print(f"{indent}(no confirmed pits to analyse)")
        return

    # 1. Size distribution ------------------------------------------------
    print(f"\n{indent}1. Size distribution")
    for bucket_label, count, pct_str in _diag_size_histogram(confirmed_pits):
        bar = "#" * count if count <= 40 else "#" * 40 + f"… (+{count-40})"
        print(f"{indent}  {bucket_label}  {count:4d}  {pct_str}  {bar}")

    # 2. Intensity distribution -------------------------------------------
    mean_ir, std_ir, n_shallow = _diag_intensity(confirmed_pits)
    print(f"\n{indent}2. Intensity ratio  (pit / surface mean;  < 1.0 = darker than surface)")
    print(f"{indent}  mean  = {mean_ir:.4f}")
    print(f"{indent}  std   = {std_ir:.4f}")
    print(f"{indent}  ratio > {_SHALLOW_INTENSITY_RATIO}  (shallow / noisy): "
          f"{n_shallow} / {n}  "
          f"({100.0*n_shallow/n:.1f}%)")

    # 3. Spatial clustering -----------------------------------------------
    n_clustered, n_isolated = _diag_spatial_clustering(
        confirmed_pits, scale_um_per_px
    )
    print(f"\n{indent}3. Spatial clustering  (neighbour radius = "
          f"{_CLUSTER_RADIUS_UM:.0f} µm)")
    print(f"{indent}  clustered (≥1 neighbour within radius): "
          f"{n_clustered} / {n}  "
          f"({100.0*n_clustered/n:.1f}%)")
    print(f"{indent}  isolated  (no neighbour within radius): "
          f"{n_isolated} / {n}  "
          f"({100.0*n_isolated/n:.1f}%)")


def main():
    results = []
    for primary_rel, fallback_rel, expected_um, debug_fn, label in TEST_CASES:
        result = _run_one(primary_rel, fallback_rel, expected_um, debug_fn, label)
        results.append(result)

    # --- Per-image summary tables ------------------------------------------
    for res in results:
        print()
        print(f"  {'='*56}")
        print(f"  {res['label']}  —  {res['filename'] or '(not found)'}")
        print(f"  {'='*56}")

        if res["n_candidates"] is None:
            print(f"  {res['message']}")
            continue

        breakdown_str = "  ".join(
            f"{rule}={count}"
            for rule, count in sorted((res["rejection_breakdown"] or {}).items())
        ) or "—"

        def _v(val, fmt=""):
            return format(val, fmt) if val is not None else "—"

        rows = [
            ("Scale (µm/px)",       _v(res["scale_um_per_px"], ".4f")),
            ("Stage 2 candidates",  _v(res["n_candidates"],    "d")),
            ("Confirmed pits",      _v(res["n_confirmed"],     "d")),
            ("Rejected",            _v(res["n_rejected"],      "d")),
            ("  rejection breakdown", breakdown_str),
            ("Mean area (µm²)",     _v(res["mean_area_um2"],   ".2f")),
            ("Mean intensity ratio", _v(res["mean_int_ratio"], ".4f")),
            ("Result",              res["status"]),
        ]
        col_w = max(len(row[0]) for row in rows) + 2
        for key, val in rows:
            print(f"  {key:<{col_w}}: {val}")

    # --- Noise diagnostics — printed after all summary tables ---------------
    for res in results:
        if res["confirmed_pits"] and res["scale_um_per_px"]:
            _print_diagnostics(
                res["label"],
                res["confirmed_pits"],
                res["scale_um_per_px"],
            )

    # --- Filter breakdown summary table ------------------------------------
    all_rules = ["R1", "R2", "R3", "R4", "R5", "R6"]
    col_image = 6
    col_file  = 34
    print()
    print("  Filter breakdown summary")
    header = (
        f"  {'Image':<{col_image}}  {'Scale':>7}  "
        f"{'Cands':>6}  "
        + "  ".join(f"{r:>4}" for r in all_rules)
        + f"  {'Conf':>5}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for res in results:
        bd = res["rejection_breakdown"] or {}
        rule_counts = "  ".join(f"{bd.get(r, 0):>4}" for r in all_rules)
        scale_str = f"{res['scale_um_per_px']:.4f}" if res["scale_um_per_px"] else "—"
        cands_str = str(res["n_candidates"]) if res["n_candidates"] is not None else "—"
        conf_str  = str(res["n_confirmed"])  if res["n_confirmed"]  is not None else "—"
        print(
            f"  {res['label']:<{col_image}}  {scale_str:>7}  "
            f"{cands_str:>6}  "
            + rule_counts
            + f"  {conf_str:>5}"
        )
    print()

    # --- Overall pass/fail -------------------------------------------------
    print("  " + "-" * 56)
    all_passed = True
    for res in results:
        tag = res["status"]
        print(f"  {tag} — {res['label']}: {res['message']}")
        if tag != "PASS":
            all_passed = False
    print()

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
