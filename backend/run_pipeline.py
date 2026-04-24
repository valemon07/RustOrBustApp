"""
run_pipeline.py — Full pipeline runner

Processes every image in data/raw/ through all 6 stages and appends results
to outputs/csv/results.csv.

Usage:
    python run_pipeline.py
    python run_pipeline.py --image "data/raw/some_image.jpg"
"""

import argparse
import glob
import os

from pipeline.stage1_scale_bar import detect_scale_bar, ScaleBarNotFoundError
from pipeline.stage2_roi import extract_roi_contrast_sweep
from pipeline.stage3_pit_detection import detect_pits
from pipeline.stage4_density import calculate_density
from pipeline.stage6_csv_export import export_row
from pipeline.stage7_scatter_plot import build_pit_depth_scatter
from pipeline.config import (
    MANUAL_SCALE_OVERRIDES,
    NO_SCALE_BAR_IMAGES,
    EDGE_BUFFER_UM,
    PIPELINE_SCALE_MIN_UM_PX,
    PIPELINE_SCALE_MAX_UM_PX,
)
from pipeline.stage2_roi import HULL_BOUNDARY_DILATION_PX
from pipeline.pipeline_flags import (
    PipelineFlag,
    ZERO_MACRO_PITS, ROI_TOO_SMALL, CONTRAST_CORRECTION_STRONG,
    HIGH_EDGE_PIT_RATIO, HIGH_REJECTION_RATE, RULE_DOMINATED_REJECTION,
    SCALE_OUT_OF_RANGE,
    SEVERITY_WARNING, SEVERITY_ERROR, SEVERITY_INFO,
)

RAW_DIR = os.path.join(os.path.dirname(__file__), "data", "raw")
CSV_OUT = os.path.join(os.path.dirname(__file__), "outputs", "csv", "results.csv")

# Load per-image overrides from data/image_overrides.json (if present)
_OVERRIDES_PATH = os.path.join(os.path.dirname(__file__), "data", "image_overrides.json")
try:
    import json as _json
    with open(_OVERRIDES_PATH) as _f:
        _IMAGE_OVERRIDES = _json.load(_f)
except (FileNotFoundError, ValueError):
    _IMAGE_OVERRIDES = {}

# Minimum ROI dimension (µm) — below this, flag ROI_TOO_SMALL
_ROI_MIN_UM = 200.0


def _evaluate_flags(roi_dims: dict, density_metrics: dict,
                    confirmed: list, rejection_summary: dict) -> list:
    """
    Evaluate per-image quality flags and return a list of PipelineFlag objects.

    Starts from Stage 2 flags already stored in roi_dims["pipeline_flags"], then
    adds Stage 3 / density-based flags that are only knowable after the full
    pipeline runs.
    """
    flags = list(roi_dims.get("pipeline_flags", []))

    macro_count  = density_metrics.get("pit_count_macro", 0)
    full_count   = len(confirmed)
    edge_count   = sum(1 for p in confirmed if p.get("pit_type") == "edge")
    gamma        = roi_dims.get("contrast_gamma_used", 1.0)
    total_rej    = rejection_summary.get("total_rejected", 0)
    per_rule     = rejection_summary.get("per_rule", {})
    roi_width    = roi_dims.get("width_um")
    roi_height   = roi_dims.get("height_um")

    if macro_count == 0:
        flags.append(PipelineFlag(
            name=ZERO_MACRO_PITS,
            severity=SEVERITY_WARNING,
            detail="macro_pit_count=0: no pits ≥1500 µm² confirmed",
        ))

    for dim_name, val in [("width", roi_width), ("height", roi_height)]:
        if val is not None and val < _ROI_MIN_UM:
            flags.append(PipelineFlag(
                name=ROI_TOO_SMALL,
                severity=SEVERITY_ERROR,
                detail=f"roi_{dim_name}_um={val:.1f} < {_ROI_MIN_UM:.0f} µm",
            ))

    # Only flag gamma=3.0 (extreme brightening); 0.5/2.0 are normal sweep outcomes.
    if gamma is not None and gamma >= 3.0:
        flags.append(PipelineFlag(
            name=CONTRAST_CORRECTION_STRONG,
            severity=SEVERITY_WARNING,
            detail=f"contrast_gamma_used={gamma} — extreme brightening; image may be underexposed",
        ))

    if full_count > 0 and edge_count / full_count > 0.5:
        flags.append(PipelineFlag(
            name=HIGH_EDGE_PIT_RATIO,
            severity=SEVERITY_WARNING,
            detail=f"edge_pits={edge_count} / full_pit_count={full_count} > 50%",
        ))

    if total_rej > 5 * full_count and full_count < 5:
        flags.append(PipelineFlag(
            name=HIGH_REJECTION_RATE,
            severity=SEVERITY_WARNING,
            detail=f"total_rejected={total_rej} > 5 × confirmed={full_count} AND confirmed < 5",
        ))

    if total_rej > 20:
        for rule_key, rule_count in per_rule.items():
            if rule_count / total_rej > 0.70:
                flags.append(PipelineFlag(
                    name=RULE_DOMINATED_REJECTION,
                    severity=SEVERITY_INFO,
                    detail=f"{rule_key} accounts for {rule_count}/{total_rej} rejections",
                ))
                break

    return flags


def process_image(image_path: str, settings: dict = None) -> dict:
    """
    Run stages 1–4 on a single image and return the result row dict.

    Parameters
    ----------
    image_path : str
        Absolute path to the image file.
    settings : dict, optional
        Global run settings from the frontend (user-adjustable parameters).
        Per-image entries in image_overrides.json take priority over these.

        Recognised keys:
            gamma                  (float) 0 = auto sweep; >0 forces that gamma
            morph_open_kernel_px   (int)   0 = disabled; >0 removes narrow features
            r3_max_aspect_ratio    (float) Stage 3 R3 override
            r4_min_circularity     (float) Stage 3 R4 override
            r7_max_intensity_ratio (float) Stage 3 R7 override
            r8_min_aspect_ratio    (float) Stage 3 R8 override

    Returns
    -------
    dict with CSV-ready fields plus '_debug_vis' (numpy BGR array, not written to CSV).
    """
    settings = settings or {}
    filename  = os.path.basename(image_path)
    stem      = os.path.splitext(filename)[0]
    sample_id = filename.split(" ")[0].split(".")[0]

    if stem in NO_SCALE_BAR_IMAGES:
        raise ValueError(f"{stem} has no scale bar (listed in NO_SCALE_BAR_IMAGES)")

    def _scale_error_row(scale_bar_um, scale_um_per_px):
        """Return a flagged CSV row for images whose scale is out of range."""
        detail = (
            f"{scale_um_per_px:.3f} µm/px (scale bar: {scale_bar_um:.0f} µm) is outside "
            f"the pipeline's {PIPELINE_SCALE_MIN_UM_PX}–{PIPELINE_SCALE_MAX_UM_PX} µm/px "
            f"operating range — retake this image at the correct magnification."
        )
        return {
            "file_name":              filename,
            "specimen_id":            sample_id,
            "scale_bar_um":           round(scale_bar_um, 1),
            "pit_count":              0,
            "pit_density_per_cm":     0.0,
            "mean_pit_depth":         0.0,
            "max_pit_depth":          0.0,
            "all_pit_depths":         "",
            "flagged_for_review":     "Yes",
            "reason_for_flag":        f"{SCALE_OUT_OF_RANGE}: {detail}",
            "exposure_contrast_used": "",
            "R1_rejections":          0,
            "R2_rejections":          0,
            "R3_rejections":          0,
            "R4_rejections":          0,
            "R5_rejections":          0,
            "R6_rejections":          0,
            "R7_rejections":          0,
            "R8_rejections":          0,
            "_debug_vis":             None,
        }

    # ── Stage 1: scale calibration ────────────────────────────────────────────
    um_override      = MANUAL_SCALE_OVERRIDES.get(stem)
    scale_um_per_px, scale_bar_um, _ = detect_scale_bar(
        image_path, um_value_override=um_override
    )

    # ── Scale range check ─────────────────────────────────────────────────────
    if not (PIPELINE_SCALE_MIN_UM_PX <= scale_um_per_px <= PIPELINE_SCALE_MAX_UM_PX):
        return _scale_error_row(scale_bar_um, scale_um_per_px)

    # ── Resolve per-image overrides (image_overrides.json wins over settings) ─
    img_overrides = _IMAGE_OVERRIDES.get(stem, {})

    # Edge buffer
    buf_um = img_overrides.get("edge_buffer_um") or EDGE_BUFFER_UM
    edge_buffer_px = (
        max(1, round(buf_um / scale_um_per_px)) if buf_um is not None
        else HULL_BOUNDARY_DILATION_PX
    )

    # Gamma: per-image override → global setting (0 means "auto") → None (sweep)
    _gamma_img      = img_overrides.get("gamma")
    _gamma_setting  = settings.get("gamma", 0)
    _gamma_setting  = float(_gamma_setting) if _gamma_setting else 0.0
    effective_gamma = _gamma_img or (_gamma_setting if _gamma_setting != 0.0 else None)
    gamma_values    = [float(effective_gamma)] if effective_gamma is not None else None

    # Morph open kernel
    _morph_img      = img_overrides.get("morph_open_kernel_px")
    _morph_setting  = settings.get("morph_open_kernel_px", 0)
    _morph_setting  = int(_morph_setting) if _morph_setting else 0
    morph_open_kernel_px = _morph_img or (_morph_setting if _morph_setting != 0 else None)

    # Stage 3 rule overrides
    _s3_img = img_overrides.get("stage3", {})
    stage3_overrides = {}
    for key in ["r3_max_aspect_ratio", "r4_min_circularity",
                "r7_max_intensity_ratio", "r8_min_aspect_ratio"]:
        if key in _s3_img:
            stage3_overrides[key] = _s3_img[key]
        elif key in settings and settings[key] is not None:
            val = settings[key]
            if val != "" and val is not None:
                stage3_overrides[key] = float(val)

    # ── Stage 2: ROI extraction ───────────────────────────────────────────────
    specimen_mask, _, roi_dims, _ = extract_roi_contrast_sweep(
        image_path,
        scale_um_per_px=scale_um_per_px,
        gamma_values=gamma_values,
        edge_buffer_px=edge_buffer_px,
        morph_open_kernel_px=morph_open_kernel_px,
    )

    # ── Stage 3: pit detection ────────────────────────────────────────────────
    confirmed, _, debug_vis, rejection_summary = detect_pits(
        image_path, scale_um_per_px, specimen_mask, roi_dims,
        edge_buffer_px=edge_buffer_px,
        overrides=stage3_overrides,
    )

    # ── Stage 4: density metrics ──────────────────────────────────────────────
    density_metrics, _, _, _ = calculate_density(
        image_path, confirmed, roi_dims, specimen_mask, scale_um_per_px
    )

    # ── Pit stats from confirmed macro pits ───────────────────────────────────
    macro_pits = [p for p in confirmed if p.get("pit_tier") == "macro"]
    widths     = [p["width_um"] for p in macro_pits if "width_um" in p]
    mean_pit_depth  = round(sum(widths) / len(widths), 2) if widths else 0.0
    max_pit_depth   = round(max(widths), 2) if widths else 0.0
    all_pit_depths  = ";".join(str(round(w, 2)) for w in widths)

    # ── Flag evaluation ───────────────────────────────────────────────────────
    flags       = _evaluate_flags(roi_dims, density_metrics, confirmed, rejection_summary)
    flagged     = bool(flags)
    flag_reason = "; ".join(f.name for f in flags) if flags else ""

    # ── R1–R8 rejection counts ────────────────────────────────────────────────
    per_rule = rejection_summary.get("per_rule", {})

    return {
        "file_name":              filename,
        "specimen_id":            sample_id,
        "scale_bar_um":           round(scale_bar_um, 1),
        "pit_count":              density_metrics["pit_count_macro"],
        "pit_density_per_cm":     round(density_metrics.get("pit_density_macro_per_cm", 0.0), 4),
        "mean_pit_depth":         mean_pit_depth,
        "max_pit_depth":          max_pit_depth,
        "all_pit_depths":         all_pit_depths,
        "flagged_for_review":     "Yes" if flagged else "No",
        "reason_for_flag":        flag_reason,
        "exposure_contrast_used": roi_dims.get("contrast_gamma_used", 1.0),
        "R1_rejections":          per_rule.get("R1", 0),
        "R2_rejections":          per_rule.get("R2", 0),
        "R3_rejections":          per_rule.get("R3", 0),
        "R4_rejections":          per_rule.get("R4", 0),
        "R5_rejections":          per_rule.get("R5", 0),
        "R6_rejections":          per_rule.get("R6", 0),
        "R7_rejections":          per_rule.get("R7", 0),
        "R8_rejections":          per_rule.get("R8", 0),
        # Non-CSV field: stage 3 annotated debug image (saved by server)
        "_debug_vis":             debug_vis,
    }


def main():
    parser = argparse.ArgumentParser(description="Rust or Bust pipeline")
    parser.add_argument("--image", help="Process a single image file")
    args = parser.parse_args()

    if args.image:
        image_paths = [args.image]
    else:
        image_paths = sorted(
            glob.glob(os.path.join(RAW_DIR, "*.jpg"))
            + glob.glob(os.path.join(RAW_DIR, "*.png"))
            + glob.glob(os.path.join(RAW_DIR, "*.tif"))
            + glob.glob(os.path.join(RAW_DIR, "*.tiff"))
        )

    if not image_paths:
        print("No images found in", RAW_DIR)
        return

    collected_rows = []
    for image_path in image_paths:
        print(f"Processing {os.path.basename(image_path)} ...", end=" ", flush=True)
        try:
            row_data = process_image(image_path)
            row_data.pop("_debug_vis", None)
            export_row(row_data, CSV_OUT)
            collected_rows.append(row_data)
            flag_str = f" [FLAGGED: {row_data['reason_for_flag']}]" if row_data["flagged_for_review"] == "Yes" else ""
            print(f"done — {row_data['pit_count']} macro pits{flag_str}")
        except Exception as exc:
            print(f"ERROR — {exc}")

    print(f"\nResults written to {CSV_OUT}")

    scatter_png = build_pit_depth_scatter(collected_rows)
    if scatter_png:
        scatter_path = os.path.join(os.path.dirname(CSV_OUT), "pit_depth_scatter.png")
        with open(scatter_path, "wb") as fh:
            fh.write(scatter_png)
        print(f"Scatter plot written to {scatter_path}")


if __name__ == "__main__":
    main()
