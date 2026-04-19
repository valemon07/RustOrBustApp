"""
Full Pipeline Test Runner
=========================
Runs Stages 1–4 on every in-scope JPEG and saves to a dated output folder:

  <folder>/
    <stem>.jpg              — Stage 3 annotated image (all confirmed pits labeled)
    <stem>_stage2.jpg       — Stage 2 ROI/mask image
    consistency_check.csv   — Per-image metrics including per-rule rejection counts
    REPORT.md               — Pipeline summary

Usage
-----
    python tests/run_full_test.py [output_folder_name]

If output_folder_name is omitted, defaults to today's date + " full test".
"""

import csv
import datetime
import glob
import json as _json_mod
import math
import os
import re
import statistics
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage1_scale_bar     import detect_scale_bar, ScaleBarNotFoundError
from pipeline.stage2_roi           import (extract_roi, extract_roi_contrast_sweep,
                                           apply_gamma, HULL_BOUNDARY_DILATION_PX)
from pipeline.stage3_pit_detection import (
    detect_pits,
    MIN_PIT_AREA_UM2, MAX_PIT_AREA_UM2_SURFACE, MAX_PIT_AREA_UM2_EDGE,
    MAX_ASPECT_RATIO, MAX_ASPECT_RATIO_LARGE_PIT,
    MIN_CIRCULARITY, MIN_CIRCULARITY_LARGE_PIT,
    MAX_INTENSITY_RATIO, SCALE_AWARE_AREA_COEFF,
    MIN_PIXEL_COUNT, LARGE_PIT_AREA_UM2, MACRO_PIT_AREA_UM2,
    R6_MIN_COUNT,
)
from pipeline.stage4_density       import calculate_density
from pipeline.config               import (MANUAL_SCALE_OVERRIDES,
                                           NO_SCALE_BAR_IMAGES,
                                           EXCLUDED_SPECIMENS,
                                           CONTRAST_SWEEP_ENABLED,
                                           CONTRAST_SWEEP_GAMMAS,
                                           EDGE_BUFFER_UM)
from pipeline.pipeline_flags       import (
    PipelineFlag,
    ZERO_MACRO_PITS, ROI_TOO_SMALL, CONTRAST_CORRECTION_STRONG,
    HIGH_EDGE_PIT_RATIO, HIGH_REJECTION_RATE, RULE_DOMINATED_REJECTION,
    DENSITY_OUTLIER_HIGH, DENSITY_OUTLIER_LOW,
    SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO,
)

ROOT    = os.path.join(os.path.dirname(__file__), "..")

# ---------------------------------------------------------------------------
# Per-image overrides (data/image_overrides.json)
# ---------------------------------------------------------------------------
_OVERRIDES_PATH = os.path.join(ROOT, "data", "image_overrides.json")
try:
    with open(_OVERRIDES_PATH) as _f:
        IMAGE_OVERRIDES: dict = {
            k: v for k, v in _json_mod.load(_f).items()
            if not k.startswith("_")   # skip comment keys
        }
except FileNotFoundError:
    IMAGE_OVERRIDES = {}
RAW_DIR = os.path.join(ROOT, "data", "raw")

# Banner / label colours (BGR)
_MACRO_SURFACE = (0, 220, 0)
_MACRO_EDGE    = (220, 80, 0)
_MICRO_SURFACE = (0, 100, 0)
_MICRO_EDGE    = (120, 40, 0)
_REJECTED      = (70, 70, 70)

_SPECIMEN_LABELS = {
    "CR3-1": "moderate",
    "CR3-3": "moderate",
    "CR3-7": "severe",
    "CR3-8": "severe",
    "CR3-9": "severe",
}

SCALE_MIN    = 0.5
SCALE_MAX    = 10.0
ROI_MIN_UM   = 200.0


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------

def _put_label(img, text, x, y, font_scale=0.28, thickness=1):
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, text, (x + 1, y + 1), font, font_scale,
                (0, 0, 0), thickness + 1, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), font, font_scale,
                (255, 255, 255), thickness, cv2.LINE_AA)


def _annotate_stage3(image, confirmed_pits, rejected_candidates,
                     scale_um_per_px, filename):
    """Return a fully annotated stage-3 image with banner."""
    vis    = image.copy()
    img_h, img_w = vis.shape[:2]

    for cand in rejected_candidates:
        if "contour" in cand:
            cv2.drawContours(vis, [cand["contour"]], -1, _REJECTED, 1)

    n_macro = sum(1 for p in confirmed_pits if p.get("pit_tier") == "macro")
    n_micro = len(confirmed_pits) - n_macro

    for pit in confirmed_pits:
        is_macro = pit.get("pit_tier", "micro") == "macro"
        colour   = (_MACRO_SURFACE if pit["pit_type"] == "surface" else _MACRO_EDGE) \
                   if is_macro else \
                   (_MICRO_SURFACE if pit["pit_type"] == "surface" else _MICRO_EDGE)
        thick    = 2 if is_macro else 1
        cv2.drawContours(vis, [pit["contour"]], -1, colour, thick)

        cx, cy = pit["centroid_x_px"], pit["centroid_y_px"]
        if is_macro:
            depth = pit.get("pit_depth_um", 0.0)
            area  = pit.get("area_um2", 0.0)
            label = f"#{pit['pit_id']}  {area:.0f}µm²  d={depth:.0f}µm"
        else:
            label = f"#{pit['pit_id']}"
        _put_label(vis, label, cx + 3, cy - 3,
                   font_scale=0.28 if is_macro else 0.22)

    # Banner
    banner_h = 64
    banner   = np.zeros((banner_h, img_w, 3), dtype=np.uint8)
    banner[:] = (30, 30, 30)

    depths = [p["pit_depth_um"] for p in confirmed_pits if "pit_depth_um" in p]
    line1 = (f"{os.path.basename(filename)}   "
             f"scale={scale_um_per_px:.4f} µm/px   "
             f"confirmed={len(confirmed_pits)} macro={n_macro} micro={n_micro}  "
             f"rejected={len(rejected_candidates)}")
    if depths:
        line2 = (f"depth avg={sum(depths)/len(depths):.1f}µm  "
                 f"max={max(depths):.1f}µm   "
                 f"[bright-green=surface-macro  bright-orange=edge-macro  "
                 f"dim=micro  grey=rejected]")
    else:
        line2 = "[bright-green=surface-macro  bright-orange=edge-macro  dim=micro  grey=rejected]"

    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(banner, line1, (8, 20), font, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.putText(banner, line2, (8, 48), font, 0.38, (160, 160, 160), 1, cv2.LINE_AA)

    return np.vstack([banner, vis])


# ---------------------------------------------------------------------------
# Per-image runner
# ---------------------------------------------------------------------------

def _run_one(image_path):
    filename    = os.path.basename(image_path)
    stem        = os.path.splitext(filename)[0]
    match       = re.search(r"CR3-\d+", filename, re.IGNORECASE)
    specimen_id = match.group(0).upper() if match else "unknown"
    label       = _SPECIMEN_LABELS.get(specimen_id, "unknown")

    base = {
        "filename":            filename,
        "specimen_id":         specimen_id,
        "label":               label,
        "scale_um_per_px":     None,
        "scale_bar_um":        None,
        "roi_width_um":        None,
        "roi_height_um":       None,
        "macro_pit_count":     0,
        "macro_density_per_cm": 0.0,
        "full_pit_count":      0,
        "full_density_per_cm": 0.0,
        "pit_count":           0,
        "pit_density_per_cm2": 0.0,
        "avg_pit_depth_um":    None,
        "max_pit_depth_um":    None,
        "pit_depths_um":       [],
        "rejected_R1":         0,
        "rejected_R2":         0,
        "rejected_R3":         0,
        "rejected_R4":         0,
        "rejected_R5":         0,
        "rejected_R6":         0,
        "rejected_R7":         0,
        "rejected_R8":         0,
        "pit_count_edge":      0,
        "_rejection_summary":  {},
        "_pipeline_flags":     [],
        "mask_fill_ratio":     None,
        "mask_warning":        None,
        "roi_incomplete":      False,
        "roi_flags":           [],
        "contrast_gamma_used": 1.0,
        "excluded":            False,
        "no_scale_bar":        False,
        "error":               None,
        "_stage2_vis":         None,
        "_stage3_vis":         None,
    }

    if specimen_id in EXCLUDED_SPECIMENS:
        base["excluded"] = True
        return base

    if stem in NO_SCALE_BAR_IMAGES:
        base["no_scale_bar"] = True
        return base

    try:
        um_override = MANUAL_SCALE_OVERRIDES.get(stem)
        try:
            scale, um_value, _ = detect_scale_bar(
                image_path, um_value_override=um_override
            )
        except ScaleBarNotFoundError:
            base["no_scale_bar"] = True
            return base

        base["scale_um_per_px"] = scale
        base["scale_bar_um"]    = um_value

        # Per-image overrides: loaded from data/image_overrides.json.
        # Supported keys:
        #   edge_buffer_um       — float, boundary buffer in µm
        #   gamma                — float, forces a specific gamma (skips contrast sweep)
        #   morph_open_kernel_px — int, Stage 2 morphological opening radius in pixels
        #   stage3               — dict with optional keys:
        #                          r3_max_aspect_ratio, r4_min_circularity,
        #                          r7_max_intensity_ratio, r8_min_aspect_ratio
        _img_overrides       = IMAGE_OVERRIDES.get(stem, {})
        _buf_um              = _img_overrides.get("edge_buffer_um") or EDGE_BUFFER_UM
        edge_buffer_px       = (
            max(1, round(_buf_um / scale)) if _buf_um is not None
            else HULL_BOUNDARY_DILATION_PX
        )
        morph_open_kernel_px = _img_overrides.get("morph_open_kernel_px", None)
        forced_gamma         = _img_overrides.get("gamma", None)
        stage3_overrides     = _img_overrides.get("stage3", {})

        if forced_gamma is not None:
            # Forced gamma: skip contrast sweep; apply the specified gamma directly.
            _img = cv2.imread(image_path)
            _img_g = apply_gamma(_img, forced_gamma)
            specimen_mask, _, roi_dims, stage2_vis = extract_roi(
                _img_g, scale_um_per_px=scale,
                edge_buffer_px=edge_buffer_px,
                morph_open_kernel_px=morph_open_kernel_px,
            )
            roi_dims["contrast_gamma_used"] = forced_gamma
        elif CONTRAST_SWEEP_ENABLED:
            specimen_mask, _, roi_dims, stage2_vis = extract_roi_contrast_sweep(
                image_path, scale_um_per_px=scale,
                edge_buffer_px=edge_buffer_px,
                morph_open_kernel_px=morph_open_kernel_px,
            )
        else:
            specimen_mask, _, roi_dims, stage2_vis = extract_roi(
                image_path, scale,
                edge_buffer_px=edge_buffer_px,
                morph_open_kernel_px=morph_open_kernel_px,
            )
        base["roi_width_um"]       = roi_dims["width_um"]
        base["roi_height_um"]      = roi_dims["height_um"]
        base["mask_fill_ratio"]    = roi_dims["mask_fill_ratio"]
        base["mask_warning"]       = roi_dims["mask_warning"]
        base["roi_incomplete"]     = roi_dims["roi_incomplete"]
        base["roi_flags"]          = roi_dims["pipeline_flags"]
        base["contrast_gamma_used"] = roi_dims.get("contrast_gamma_used", 1.0)
        base["_stage2_vis"]        = stage2_vis

        confirmed, rejected, stage3_vis, rejection_summary = detect_pits(
            image_path, scale, specimen_mask, roi_dims,
            edge_buffer_px=edge_buffer_px,
            overrides=stage3_overrides,
        )
        base["full_pit_count"]      = len(confirmed)
        base["pit_count"]           = len(confirmed)
        base["pit_count_edge"]      = sum(1 for p in confirmed if p.get("pit_type") == "edge")
        base["_rejection_summary"]  = rejection_summary

        # Per-pit depth stats
        depths = [p["pit_depth_um"] for p in confirmed if "pit_depth_um" in p]
        if depths:
            base["pit_depths_um"]    = depths
            base["avg_pit_depth_um"] = round(sum(depths) / len(depths), 2)
            base["max_pit_depth_um"] = round(max(depths), 2)

        # Per-rule rejection counts
        for r in rejected:
            for reason in r.get("rejection_reasons", []):
                key = reason.split(":")[0].strip()
                col = f"rejected_{key}"
                if col in base:
                    base[col] += 1

        # Stage 3 annotated image (with richer labels/banner)
        image = cv2.imread(image_path)
        base["_stage3_vis"] = _annotate_stage3(
            image, confirmed, rejected, scale, filename
        )

        # Stage 4
        density_metrics, _, _, _ = calculate_density(
            image_path, confirmed, roi_dims, specimen_mask, scale
        )
        base["macro_pit_count"]       = density_metrics["pit_count_macro"]
        base["macro_density_per_cm"]  = density_metrics["pit_density_macro_per_cm"]
        base["full_density_per_cm"]   = density_metrics["pit_density_all_per_cm"]
        base["pit_density_per_cm2"]   = round(
            density_metrics["areal_all_pits_per_mm2"] * 100.0, 4
        )

    except Exception as exc:
        base["error"] = str(exc)

    return base


# ---------------------------------------------------------------------------
# Flag helpers
# ---------------------------------------------------------------------------

def _flag_reasons(row):
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
    if row["roi_width_um"]  is not None and row["roi_width_um"]  < ROI_MIN_UM:
        reasons.append(f"roi_width {row['roi_width_um']:.0f}um < {ROI_MIN_UM:.0f}")
    if row["roi_height_um"] is not None and row["roi_height_um"] < ROI_MIN_UM:
        reasons.append(f"roi_height {row['roi_height_um']:.0f}um < {ROI_MIN_UM:.0f}")
    return reasons


def _evaluate_per_image_flags(row) -> list:
    """Return PipelineFlag objects for per-image quality issues not already raised by Stage 2.

    Stage 2 flags (MASK_ROI_INCOMPLETE, MASK_COVERAGE_LOW/HIGH) arrive via
    row["roi_flags"] and are merged separately in main().  This function adds
    the remaining per-image checks.
    """
    flags = []
    # Skip images that didn't run the full pipeline
    if row.get("excluded") or row.get("no_scale_bar") or row.get("error"):
        return flags

    # ZERO_MACRO_PITS
    if row["macro_pit_count"] == 0:
        flags.append(PipelineFlag(
            name=ZERO_MACRO_PITS,
            severity=SEVERITY_WARNING,
            detail="macro_pit_count=0: no pits ≥1500 µm² confirmed",
        ))

    # ROI_TOO_SMALL
    for dim, val in [("width", row.get("roi_width_um")),
                     ("height", row.get("roi_height_um"))]:
        if val is not None and val < ROI_MIN_UM:
            flags.append(PipelineFlag(
                name=ROI_TOO_SMALL,
                severity=SEVERITY_ERROR,
                detail=f"roi_{dim}_um={val:.1f} < {ROI_MIN_UM:.0f} µm",
            ))

    # CONTRAST_CORRECTION_STRONG — only flag gamma=3.0, the extreme brightening value.
    # gamma=0.5 (moderate darkening) and gamma=2.0 (moderate brightening) are normal
    # corrections selected by the contrast sweep and do not indicate a problem.
    gamma = row.get("contrast_gamma_used", 1.0)
    if gamma is not None and gamma >= 3.0:
        flags.append(PipelineFlag(
            name=CONTRAST_CORRECTION_STRONG,
            severity=SEVERITY_WARNING,
            detail=f"contrast_gamma_used={gamma} — extreme brightening required; image may be severely underexposed",
        ))

    # HIGH_EDGE_PIT_RATIO
    full_count = row.get("full_pit_count", 0)
    edge_count = row.get("pit_count_edge", 0)
    if full_count > 0 and edge_count / full_count > 0.5:
        flags.append(PipelineFlag(
            name=HIGH_EDGE_PIT_RATIO,
            severity=SEVERITY_WARNING,
            detail=(f"edge_pits={edge_count} / full_pit_count={full_count} "
                    f"= {edge_count/full_count:.0%} > 50%"),
        ))

    # HIGH_REJECTION_RATE
    summary = row.get("_rejection_summary", {})
    total_rejected = summary.get("total_rejected", 0)
    confirmed_count = row.get("full_pit_count", 0)
    if total_rejected > 5 * confirmed_count and confirmed_count < 5:
        flags.append(PipelineFlag(
            name=HIGH_REJECTION_RATE,
            severity=SEVERITY_WARNING,
            detail=(f"total_rejected={total_rejected} > 5 × confirmed={confirmed_count} "
                    f"AND confirmed < 5"),
        ))

    # RULE_DOMINATED_REJECTION
    per_rule = summary.get("per_rule", {})
    if total_rejected > 20:
        for rule_key, rule_count in per_rule.items():
            if rule_count / total_rejected > 0.70:
                flags.append(PipelineFlag(
                    name=RULE_DOMINATED_REJECTION,
                    severity=SEVERITY_INFO,
                    detail=(f"{rule_key} accounts for {rule_count}/{total_rejected} "
                            f"rejections ({rule_count/total_rejected:.0%})"),
                ))
                break  # only one dominant-rule flag per image

    return flags


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

def _write_report(out_dir, rows, n_stage2, n_stage3, run_date):
    successful = [r for r in rows
                  if not r.get("excluded") and not r.get("no_scale_bar")
                  and not r["error"]]
    excluded   = [r for r in rows if r.get("excluded")]
    no_scale   = [r for r in rows if r.get("no_scale_bar")]
    errors     = [r for r in rows if r.get("error") and not r.get("no_scale_bar")]

    # Structured flag summary (from new _pipeline_flags system)
    all_flagged     = [r for r in rows if r.get("_pipeline_flags")]
    error_flagged   = [r for r in rows
                       if any(f.severity == SEVERITY_ERROR
                              for f in r.get("_pipeline_flags", []))]
    warning_flagged = [r for r in rows
                       if any(f.severity == SEVERITY_WARNING
                              for f in r.get("_pipeline_flags", []))]

    # Count images affected by each flag name (deduplicated per image)
    flag_name_counts: dict = {}
    for row in rows:
        seen = set()
        for f in row.get("_pipeline_flags", []):
            if f.name not in seen:
                flag_name_counts[f.name] = flag_name_counts.get(f.name, 0) + 1
                seen.add(f.name)

    flag_freq_table = "\n".join(
        f"| `{name}` | {count} |"
        for name, count in sorted(flag_name_counts.items(), key=lambda x: -x[1])
    ) or "| — | — |"

    # Per-image detail table
    flagged_detail_rows = []
    for row in sorted(all_flagged, key=lambda r: r["filename"]):
        errs  = [f.name for f in row["_pipeline_flags"] if f.severity == SEVERITY_ERROR]
        warns = [f.name for f in row["_pipeline_flags"] if f.severity == SEVERITY_WARNING]
        infos = [f.name for f in row["_pipeline_flags"] if f.severity == SEVERITY_INFO]
        parts = []
        if errs:   parts.append("ERROR: " + ", ".join(errs))
        if warns:  parts.append("WARN: "  + ", ".join(warns))
        if infos:  parts.append("INFO: "  + ", ".join(infos))
        flagged_detail_rows.append(f"| {row['filename']} | {' / '.join(parts)} |")
    flagged_detail_table = "\n".join(flagged_detail_rows) or "| — | — |"

    # Keep legacy count for the dataset summary line
    flagged = all_flagged

    # Per-class stats
    def _ms(vals):
        if not vals:
            return "—", "—"
        m = statistics.mean(vals)
        s = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        return f"{m:.2f}", f"{s:.2f}"

    classes = sorted(set(r["label"] for r in successful))
    class_rows = []
    for lbl in classes:
        sub = [r for r in successful if r["label"] == lbl]
        dm, ds = _ms([r["macro_density_per_cm"] for r in sub])
        cm, cs = _ms([r["macro_pit_count"]      for r in sub])
        sm, ss = _ms([r["scale_um_per_px"]      for r in sub if r["scale_um_per_px"]])
        class_rows.append(
            f"| {lbl} | {len(sub)} | {dm} ± {ds} | {cm} ± {cs} | {sm} ± {ss} |"
        )
    class_table = "\n".join(class_rows)

    all_dens = [r["macro_density_per_cm"] for r in successful]
    mean_d = statistics.mean(all_dens) if all_dens else 0
    std_d  = statistics.pstdev(all_dens) if len(all_dens) > 1 else 0
    min_d  = min(all_dens) if all_dens else 0
    max_d  = max(all_dens) if all_dens else 0

    pixel_floor_note = (
        f"15 px × scale² µm²  (at 4.2 µm/px → {15 * 4.2**2:.0f} µm², "
        f"at 1.05 µm/px → {15 * 1.05**2:.1f} µm²)"
    )

    report = f"""# Pipeline Report — {run_date}

## Contents of This Folder

| File pattern | Count | Description |
|---|---|---|
| `<stem>.jpg` | {n_stage3} | Stage 3 annotated images — all confirmed pits labeled |
| `<stem>_stage2.jpg` | {n_stage2} | Stage 2 ROI/mask images — hull boundary + candidate regions |
| `consistency_check.csv` | 1 | Per-image metrics table with per-rule rejection counts |
| `REPORT.md` | 1 | This file |

---

## Pipeline Changes Since Full Test 2 (2026-04-09 full test 2)

### R5 — Pixel-count floor added

**Rule:** `effective_min = max(10, 84/scale, MIN_PIXEL_COUNT × scale²)` where `MIN_PIXEL_COUNT = 15`.

**Why:** At overview magnification (~4.2 µm/px) the old scale-aware coefficient floor collapsed
to ~20 µm² (≈ 1 pixel), admitting single-pixel noise blobs that passed all other geometric
filters. Adding a pixel-count floor of 15 px raises the effective minimum at overview scale to
{15 * 4.2**2:.0f} µm² while leaving high-mag images unaffected ({15 * 1.05**2:.1f} µm² at
1.05 µm/px, dominated by the 80.1 µm² coefficient term).

### R7 — Darkness threshold tightened: 0.92 → 0.85

**Why:** Confirmed real pit intensity ratios across all images ranged 0.03–0.69, well below
the 0.92 threshold. Surface scratches that passed R3/R4 (polishing scratches with moderate
aspect) often had intensity ratios in the 0.85–0.92 range — distinctly bright but not caught
by the old threshold. Tightening to 0.85 rejects these without affecting confirmed pits.

### R3 — Aspect ratio: area-conditional relaxation

**Rule:** `aspect_ceiling = 12.0` when `area ≥ 2000 µm²`, else `8.0`.

**Why:** Large real corrosion features (macro tier) can be elongated along grain boundaries or
pit chains without being polishing scratches. The 8.0 ceiling was rejecting large real pits at
high magnification that had aspect ratios in the 8–12 range. 12.0 still blocks true polishing
streaks, which typically reach 15–30×.

### R4 — Circularity: area-conditional relaxation

**Rule:** `circ_floor = 0.04` when `area ≥ 2000 µm²`, else `0.08` (surface pits only).

**Why:** Large real corrosion damage can be highly irregular without being a scratch — crevice
pits, coalescing pit clusters, and etch fronts produce low circularity by geometry, not because
they are noise. Relaxing from 0.08 → 0.04 for pits above the macro tier recovers these large
real features while keeping the strict 0.08 floor for small pits where circularity is the
primary scratch discriminator.

### Previous fixes (carried forward)

- **R4 circularity exempt for edge pits** — edge pits wrap the curved fastener hole.
- **R2 edge ceiling at 150,000 µm²** — raised from 50,000 µm² after diagnostic confirmed
  a 53,602 µm² real edge pit was being blocked.
- **R2 surface ceiling at 150,000 µm²** — raised from 50,000 µm² for overview scale.
- **R7 darkness filter introduced** — surface pits only, exempt for edge pits.

---

## Active Filter Rules

| Rule | Applies to | Condition | Rationale |
|---|---|---|---|
| R1 | all | area < 10 µm² | Sub-resolution absolute floor |
| R2 | surface | area > 150,000 µm² | Too large to be a surface pit |
| R2 | edge | area > 150,000 µm² | Too large even for hole-boundary pits |
| R3 | all (area < 2000 µm²) | aspect ratio > 8.0 | Polishing scratch rejection |
| R3 | all (area ≥ 2000 µm²) | aspect ratio > 12.0 | Relaxed for large pits |
| R4 | surface (area < 2000 µm²) | circularity < 0.08 | Polishing scratch rejection |
| R4 | surface (area ≥ 2000 µm²) | circularity < 0.04 | Relaxed for large surface pits |
| R5 | all | area < max(10, 84/scale, 15×scale²) µm² | Scale-aware + pixel-count noise floor |
| R6 | all | isolated AND bottom 25th pct area | Small isolated noise (≥10 survivors) |
| R7 | surface only | intensity_ratio ≥ 0.85 | Not distinctly dark → not a pit |

---

## Pipeline Run Results — {run_date}

### Dataset

| Category | Count |
|---|---|
| Total images | {len(rows)} |
| Excluded (CR3-3, out-of-scope) | {len(excluded)} |
| No scale bar | {len(no_scale)} |
| Successful | {len(successful)} |
| Exceptions | {len(errors)} |

### Flagged images ({len(all_flagged)} total — {len(error_flagged)} error, {len(warning_flagged)} warning)

#### Flag frequency

| Flag | Images affected |
|---|---|
{flag_freq_table}

#### Per-image flag detail

| Filename | Flags |
|---|---|
{flagged_detail_table}

### Per-class statistics (in-scope successful images only)

| Class | n | Macro density (pits/cm) | Macro pit count | Scale (µm/px) |
|---|---|---|---|---|
{class_table}

### Overall macro density (all {len(successful)} successful images)

| Metric | Value |
|---|---|
| Mean | {mean_d:.2f} pits/cm |
| Std | {std_d:.2f} pits/cm |
| Min | {min_d:.2f} pits/cm |
| Max | {max_d:.2f} pits/cm |

---

## Image Key

### Stage 2 masks (`_stage2.jpg`)
- **Green outline** — convex hull specimen boundary
- **Red fill** — edge pit candidates (touching the hole boundary)
- **Yellow fill** — surface pit candidates (fully interior)
- **Blue rectangle** — excluded scale-bar zone

### Stage 3 annotated images (no suffix)
- **Bright green outline** — confirmed surface pit, macro tier (≥1500 µm²)
- **Bright orange outline** — confirmed edge pit, macro tier
- **Dim green/orange** — confirmed micro pit (<1500 µm²)
- **Dark grey outline** — rejected candidate
- **Label on macro pits** — `#ID  <area> µm²  d=<depth> µm`
- **Top banner** — scale, confirmed/macro/micro counts, avg/max depth

---

## Notes for Next Review

1. The R5 pixel floor ({pixel_floor_note}) significantly reduces
   noise at overview magnification. Monitor whether any real small pits near the floor
   are lost in high-density overview images.

2. The R3/R4 area-conditional relaxation (≥ 2000 µm²) recovers large irregular pits.
   The borderline report in the filter validation test flags pits near the new 12.0
   aspect ceiling — inspect these visually if counts change unexpectedly.

3. R7 at 0.85 more aggressively rejects bright surface scratches. If any image class
   shows a significant count reduction, check the intensity_ratio distribution in the
   validation test output.
"""

    out_path = os.path.join(out_dir, "REPORT.md")
    with open(out_path, "w") as fh:
        fh.write(report)
    return out_path


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

import json as _json


def _flags_to_json(flags):
    """Serialize a list of PipelineFlag objects to a compact JSON string."""
    if not flags:
        return "[]"
    return _json.dumps([f.to_dict() for f in flags], separators=(",", ":"))


CSV_FIELDS = [
    "filename", "specimen_id", "label",
    "scale_um_per_px", "scale_bar_um",
    "roi_width_um", "roi_height_um",
    "mask_fill_ratio", "mask_warning",
    "roi_incomplete", "roi_flags",
    "contrast_gamma_used",
    "macro_pit_count", "macro_density_per_cm",
    "full_pit_count", "full_density_per_cm",
    "pit_count", "pit_density_per_cm2",
    "avg_pit_depth_um", "max_pit_depth_um", "pit_depths_um",
    "rejected_R1", "rejected_R2", "rejected_R3", "rejected_R4",
    "rejected_R5", "rejected_R6", "rejected_R7", "rejected_R8",
    "pit_count_edge",
    "pipeline_flags", "flagged_for_review", "flag_count",
    "flagged", "flag_reasons", "error",
]


def _write_csv(out_dir, rows):
    out_path = os.path.join(out_dir, "consistency_check.csv")
    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            reasons   = row.get("_flag_reasons", [])
            all_flags = row.get("_pipeline_flags", [])
            has_review = any(
                f.severity in (SEVERITY_ERROR, SEVERITY_WARNING)
                for f in all_flags
            )
            writer.writerow({
                "filename":             row["filename"],
                "specimen_id":          row["specimen_id"],
                "label":                row["label"],
                "scale_um_per_px":      row["scale_um_per_px"] or "",
                "scale_bar_um":         row["scale_bar_um"]    or "",
                "roi_width_um":         row["roi_width_um"]    or "",
                "roi_height_um":        row["roi_height_um"]   or "",
                "mask_fill_ratio":      row["mask_fill_ratio"] if row["mask_fill_ratio"] is not None else "",
                "mask_warning":         row["mask_warning"]    or "",
                "roi_incomplete":       "True" if row["roi_incomplete"] else "False",
                "roi_flags":            _flags_to_json(row["roi_flags"]),
                "contrast_gamma_used":  row.get("contrast_gamma_used", 1.0),
                "macro_pit_count":      row["macro_pit_count"],
                "macro_density_per_cm": row["macro_density_per_cm"],
                "full_pit_count":       row["full_pit_count"],
                "full_density_per_cm":  row["full_density_per_cm"],
                "pit_count":            row["pit_count"],
                "pit_density_per_cm2":  row["pit_density_per_cm2"],
                "avg_pit_depth_um":     row["avg_pit_depth_um"] if row["avg_pit_depth_um"] is not None else "",
                "max_pit_depth_um":     row["max_pit_depth_um"] if row["max_pit_depth_um"] is not None else "",
                "pit_depths_um":        "|".join(str(d) for d in row["pit_depths_um"]),
                "rejected_R1":          row["rejected_R1"],
                "rejected_R2":          row["rejected_R2"],
                "rejected_R3":          row["rejected_R3"],
                "rejected_R4":          row["rejected_R4"],
                "rejected_R5":          row["rejected_R5"],
                "rejected_R6":          row["rejected_R6"],
                "rejected_R7":          row["rejected_R7"],
                "rejected_R8":          row.get("rejected_R8", 0),
                "pit_count_edge":       row.get("pit_count_edge", 0),
                "pipeline_flags":       _flags_to_json(all_flags),
                "flagged_for_review":   "true" if has_review else "false",
                "flag_count":           len(all_flags),
                "flagged":              "YES" if reasons else "NO",
                "flag_reasons":         "; ".join(reasons),
                "error":                row["error"] or "",
            })
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) > 1:
        folder_name = " ".join(sys.argv[1:])
    else:
        today = datetime.date.today().strftime("%Y-%m-%d")
        folder_name = f"{today} full test"

    out_dir = os.path.join(ROOT, "outputs", folder_name)
    os.makedirs(out_dir, exist_ok=True)
    print(f"\nOutput folder: {out_dir}")

    image_paths = sorted(
        glob.glob(os.path.join(RAW_DIR, "*.jpg")) +
        glob.glob(os.path.join(RAW_DIR, "*.jpeg"))
    )
    if not image_paths:
        print(f"No JPEG images found in {RAW_DIR}")
        sys.exit(1)

    print(f"Found {len(image_paths)} images. Running full pipeline …\n")

    rows        = []
    n_stage2    = 0
    n_stage3    = 0

    for idx, image_path in enumerate(image_paths, 1):
        name = os.path.basename(image_path)
        stem = os.path.splitext(name)[0]
        print(f"  [{idx:2d}/{len(image_paths)}] {name} … ", end="", flush=True)

        row     = _run_one(image_path)
        reasons = _flag_reasons(row)
        row["_flag_reasons"] = reasons

        # Merge Stage 2 flags (already PipelineFlag objects) with per-image evaluated flags
        stage2_flags   = row.get("roi_flags", [])
        computed_flags = _evaluate_per_image_flags(row)
        row["_pipeline_flags"] = stage2_flags + computed_flags

        rows.append(row)

        # Save Stage 2 mask
        if row.get("_stage2_vis") is not None:
            s2_path = os.path.join(out_dir, stem + "_stage2.jpg")
            cv2.imwrite(s2_path, row["_stage2_vis"],
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
            n_stage2 += 1

        # Save Stage 3 annotated image
        if row.get("_stage3_vis") is not None:
            s3_path = os.path.join(out_dir, stem + ".jpg")
            cv2.imwrite(s3_path, row["_stage3_vis"],
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
            n_stage3 += 1

        # Free large arrays immediately to keep memory stable
        row["_stage2_vis"] = None
        row["_stage3_vis"] = None

        new_flags = row.get("_pipeline_flags", [])
        if new_flags:
            flag_summary = ", ".join(
                f.name for f in new_flags
                if f.severity in (SEVERITY_ERROR, SEVERITY_WARNING)
            )
            status = f"FLAGGED [{flag_summary}]" if flag_summary else "OK (info only)"
        else:
            status = "OK"
        print(status)

    # --- Dataset-level statistical outlier flags (require all rows first) ---
    _stat_rows = [
        r for r in rows
        if not r.get("excluded") and not r.get("no_scale_bar")
        and not r.get("error") and r.get("macro_pit_count", 0) > 0
    ]
    if len(_stat_rows) >= 3:
        _dens  = [r["macro_density_per_cm"] for r in _stat_rows]
        _mean  = statistics.mean(_dens)
        _std   = statistics.pstdev(_dens) if len(_dens) > 1 else 0.0
        _hi    = _mean + 3 * _std
        _lo    = _mean - 3 * _std
        for row in rows:
            if row.get("excluded") or row.get("no_scale_bar") or row.get("error"):
                continue
            density = row.get("macro_density_per_cm", 0.0)
            if density > _hi:
                row["_pipeline_flags"].append(PipelineFlag(
                    name=DENSITY_OUTLIER_HIGH,
                    severity=SEVERITY_WARNING,
                    detail=(f"macro_density_per_cm={density:.2f} > "
                            f"mean+3σ={_hi:.2f} (mean={_mean:.2f}, σ={_std:.2f})"),
                ))
            elif density > 0 and density < _lo:
                row["_pipeline_flags"].append(PipelineFlag(
                    name=DENSITY_OUTLIER_LOW,
                    severity=SEVERITY_WARNING,
                    detail=(f"macro_density_per_cm={density:.2f} < "
                            f"mean-3σ={_lo:.2f} (mean={_mean:.2f}, σ={_std:.2f})"),
                ))

    # Write CSV
    csv_path = _write_csv(out_dir, rows)
    print(f"\nCSV written: {csv_path}")

    # Write REPORT.md
    run_date    = datetime.date.today().strftime("%Y-%m-%d")
    report_path = _write_report(out_dir, rows, n_stage2, n_stage3, run_date)
    print(f"Report written: {report_path}")

    # --- Summary ---
    successful = [r for r in rows
                  if not r.get("excluded") and not r.get("no_scale_bar")
                  and not r["error"]]
    excluded   = [r for r in rows if r.get("excluded")]
    flagged    = [r for r in rows if any(
                      f.severity in (SEVERITY_ERROR, SEVERITY_WARNING)
                      for f in r.get("_pipeline_flags", []))]
    errors     = [r for r in rows if r.get("error") and not r.get("no_scale_bar")]

    print()
    print("  SUMMARY")
    print("  " + "─" * 58)
    print(f"  Total images   : {len(rows)}")
    print(f"  Excluded       : {len(excluded)}")
    print(f"  Successful     : {len(successful)}")
    print(f"  Flagged        : {len(flagged)}")
    print(f"  Errors         : {len(errors)}")
    print(f"  Stage-2 saved  : {n_stage2}")
    print(f"  Stage-3 saved  : {n_stage3}")

    if successful:
        all_dens = [r["macro_density_per_cm"] for r in successful]
        mean_d = statistics.mean(all_dens)
        std_d  = statistics.pstdev(all_dens) if len(all_dens) > 1 else 0.0
        print()
        print(f"  Overall macro density (n={len(successful)}): "
              f"{mean_d:.2f} ± {std_d:.2f} pits/cm  "
              f"[min={min(all_dens):.2f}  max={max(all_dens):.2f}]")

    # Per-class breakdown
    print()
    print("  Per-class statistics (in-scope successful):")
    for lbl in sorted(set(r["label"] for r in successful)):
        sub = [r for r in successful if r["label"] == lbl]
        dens = [r["macro_density_per_cm"] for r in sub]
        md = statistics.mean(dens)
        sd = statistics.pstdev(dens) if len(dens) > 1 else 0.0
        mc = statistics.mean([r["macro_pit_count"] for r in sub])
        print(f"    [{lbl}]  n={len(sub)}  density={md:.2f}±{sd:.2f} pits/cm  "
              f"avg_macro={mc:.1f}")

    print()


if __name__ == "__main__":
    main()
