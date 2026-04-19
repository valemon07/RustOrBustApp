"""
Diagnostic: Edge-zone rejection audit
======================================
Runs Stages 1–3 on every in-scope image and produces a per-image breakdown
of rejected candidates split by origin (edge vs. other), along with confirmed
macro/micro counts and a per-rule breakdown for edge rejections.

Definition of "rejected_edge":
    Candidates that Stage 2 classified as edge_pits AND that were NOT
    reclassified to surface by Stage 3's _maybe_reclassify_edge, AND that
    were ultimately rejected by one of the R1–R8 rules.
    These are candidates that the edge-zone test marked as peripheral
    and that Stage 3 then discarded — the core symptom of Challenge 1.

Definition of "rejected_other":
    All other rejected candidates: Stage 2 surface_pits that failed a rule,
    plus any Stage 2 edge_pits that were reclassified to surface by Stage 3
    but then failed a rule.

Output
------
    outputs/csv/edge_rejection_audit.csv
    Console: sorted table of all images + top-10 by rejected_edge
             + dataset-level rule summary

Usage
-----
    python tests/diag_edge_rejection_audit.py
"""

import csv
import glob
import os
import json as _json_mod
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.stage1_scale_bar     import detect_scale_bar, ScaleBarNotFoundError
from pipeline.stage2_roi           import extract_roi, extract_roi_contrast_sweep, HULL_BOUNDARY_DILATION_PX
from pipeline.stage3_pit_detection import detect_pits
from pipeline.config               import (
    MANUAL_SCALE_OVERRIDES,
    NO_SCALE_BAR_IMAGES,
    EXCLUDED_SPECIMENS,
    CONTRAST_SWEEP_ENABLED,
    EDGE_BUFFER_UM,
)

ROOT    = os.path.join(os.path.dirname(__file__), "..")
RAW_DIR = os.path.join(ROOT, "data", "raw")

_OVERRIDES_PATH = os.path.join(ROOT, "data", "image_overrides.json")
try:
    with open(_OVERRIDES_PATH) as _f:
        IMAGE_OVERRIDES: dict = {
            k: v for k, v in _json_mod.load(_f).items()
            if not k.startswith("_")
        }
except FileNotFoundError:
    IMAGE_OVERRIDES = {}
OUT_CSV = os.path.join(ROOT, "outputs", "csv", "edge_rejection_audit.csv")

EDGE_RULES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]

CSV_FIELDS = [
    "image",
    "total_candidates",
    "rejected_edge",
    "rejected_other",
    "confirmed_macro",
    "confirmed_micro",
    "scale_um_per_px",
    "rej_edge_max_area_um2",
] + [f"rej_edge_{r}" for r in EDGE_RULES] + [
    "rej_surf_max_area_um2",
    "rej_surf_max_circ",
] + [f"rej_surf_{r}" for r in EDGE_RULES] + ["note"]


def _audit_one(image_path):
    """Run Stages 1–3 on one image and return an audit row dict."""
    filename = os.path.basename(image_path)
    stem     = os.path.splitext(filename)[0]

    row = {
        "image":                 filename,
        "total_candidates":      0,
        "rejected_edge":         0,
        "rejected_other":        0,
        "confirmed_macro":       0,
        "confirmed_micro":       0,
        "scale_um_per_px":       "",
        "rej_edge_max_area_um2": 0.0,
        "rej_surf_max_area_um2": 0.0,
        "rej_surf_max_circ":     0.0,
        "note":                  "",
    }
    for r in EDGE_RULES:
        row[f"rej_edge_{r}"] = 0
        row[f"rej_surf_{r}"] = 0

    # --- Stage 1 ---
    um_override = MANUAL_SCALE_OVERRIDES.get(stem)
    try:
        scale, _, _ = detect_scale_bar(image_path, um_value_override=um_override)
    except ScaleBarNotFoundError as exc:
        row["note"] = f"no_scale_bar: {exc}"
        return row

    row["scale_um_per_px"] = round(scale, 4)

    # Per-image edge buffer
    _img_overrides = IMAGE_OVERRIDES.get(stem, {})
    _buf_um        = _img_overrides.get("edge_buffer_um") or EDGE_BUFFER_UM
    edge_buffer_px = (
        max(1, round(_buf_um / scale)) if _buf_um is not None
        else HULL_BOUNDARY_DILATION_PX
    )

    # --- Stage 2 ---
    try:
        if CONTRAST_SWEEP_ENABLED:
            specimen_mask, _, roi_dims, _ = extract_roi_contrast_sweep(
                image_path, scale_um_per_px=scale, edge_buffer_px=edge_buffer_px
            )
        else:
            specimen_mask, _, roi_dims, _ = extract_roi(
                image_path, scale, edge_buffer_px=edge_buffer_px
            )
    except Exception as exc:
        row["note"] = f"stage2_error: {exc}"
        return row

    row["total_candidates"] = (
        len(roi_dims["edge_pits"]) + len(roi_dims["surface_pits"])
    )

    # --- Stage 3 ---
    try:
        confirmed, rejected, _, _ = detect_pits(
            image_path, scale, specimen_mask, roi_dims, edge_buffer_px=edge_buffer_px
        )
    except Exception as exc:
        row["note"] = f"stage3_error: {exc}"
        return row

    # Confirmed counts
    row["confirmed_macro"] = sum(
        1 for p in confirmed if p.get("pit_tier") == "macro"
    )
    row["confirmed_micro"] = sum(
        1 for p in confirmed if p.get("pit_tier") == "micro"
    )

    # Rejected breakdown:
    #   rejected_edge  → pit_type == "edge" (stayed edge after reclassification)
    #   rejected_other → everything else (surface, or reclassified-from-edge)
    edge_buckets = {}   # rule_tag → list of area_um2 values for edge pits
    surf_buckets = {}   # rule_tag → list of (area_um2, circularity) for surface pits
    for r in rejected:
        reasons  = r.get("rejection_reasons", ["?"])
        rule_tag = reasons[0].split(":")[0].strip()
        area     = r.get("area_um2", 0.0)
        circ     = r.get("circularity", 0.0)
        if r.get("pit_type") == "edge":
            row["rejected_edge"] += 1
            edge_buckets.setdefault(rule_tag, []).append(area)
        else:
            row["rejected_other"] += 1
            surf_buckets.setdefault(rule_tag, []).append((area, circ))

    for rule in EDGE_RULES:
        row[f"rej_edge_{rule}"] = len(edge_buckets.get(rule, []))
        row[f"rej_surf_{rule}"] = len(surf_buckets.get(rule, []))

    edge_areas = [a for areas in edge_buckets.values() for a in areas]
    row["rej_edge_max_area_um2"] = round(max(edge_areas, default=0.0), 1)

    surf_pairs = [(a, c) for pairs in surf_buckets.values() for a, c in pairs]
    if surf_pairs:
        max_surf_area, max_surf_circ = max(surf_pairs, key=lambda x: x[0])
        row["rej_surf_max_area_um2"] = round(max_surf_area, 1)
        row["rej_surf_max_circ"]     = round(max_surf_circ, 4)

    return row


def _rule_summary_str(row, prefix="rej_edge"):
    """Return a compact rule-breakdown string, e.g. 'R3×4 R5×2'."""
    parts = []
    for r in EDGE_RULES:
        count = row.get(f"{prefix}_{r}", 0)
        if count:
            parts.append(f"{r}×{count}")
    return " ".join(parts) if parts else "—"


def _blank_skipped_row(filename, note):
    """Return a fully-populated zero row for skipped images."""
    row = {
        "image": filename, "total_candidates": 0,
        "rejected_edge": 0, "rejected_other": 0,
        "confirmed_macro": 0, "confirmed_micro": 0,
        "scale_um_per_px": "",
        "rej_edge_max_area_um2": 0.0,
        "rej_surf_max_area_um2": 0.0,
        "rej_surf_max_circ":     0.0,
        "note": note,
    }
    for r in EDGE_RULES:
        row[f"rej_edge_{r}"] = 0
        row[f"rej_surf_{r}"] = 0
    return row


def main():
    image_paths = sorted(
        glob.glob(os.path.join(RAW_DIR, "*.jpg")) +
        glob.glob(os.path.join(RAW_DIR, "*.jpeg"))
    )
    if not image_paths:
        print(f"No JPEG images found in {RAW_DIR}")
        sys.exit(1)

    print(f"\nEdge rejection audit — {len(image_paths)} images found\n")

    audit_rows = []

    for idx, image_path in enumerate(image_paths, 1):
        filename       = os.path.basename(image_path)
        stem           = os.path.splitext(filename)[0]
        specimen_match = re.search(r"CR3-\d+", filename, re.IGNORECASE)
        specimen_id    = specimen_match.group(0).upper() if specimen_match else ""

        if specimen_id in EXCLUDED_SPECIMENS:
            print(f"  [{idx:2d}/{len(image_paths)}] {filename}  SKIPPED (excluded specimen)")
            audit_rows.append(_blank_skipped_row(filename, "excluded_specimen"))
            continue

        if stem in NO_SCALE_BAR_IMAGES:
            print(f"  [{idx:2d}/{len(image_paths)}] {filename}  SKIPPED (no scale bar)")
            audit_rows.append(_blank_skipped_row(filename, "no_scale_bar"))
            continue

        print(f"  [{idx:2d}/{len(image_paths)}] {filename} … ", end="", flush=True)
        row = _audit_one(image_path)
        audit_rows.append(row)
        edge_rule_str = _rule_summary_str(row, prefix="rej_edge")
        surf_rule_str = _rule_summary_str(row, prefix="rej_surf")
        print(
            f"edge_rej={row['rejected_edge']:3d}  "
            f"surf_rej={row['rejected_other']:3d}  "
            f"macro={row['confirmed_macro']:3d}  "
            f"micro={row['confirmed_micro']:3d}  "
            f"max_surf_area={row['rej_surf_max_area_um2']:8.0f}µm²  "
            f"surf_rules=[{surf_rule_str}]  "
            f"edge_rules=[{edge_rule_str}]"
            + (f"  [{row['note']}]" if row["note"] else "")
        )

    # --- Write CSV ---
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(audit_rows)
    print(f"\nCSV written: {OUT_CSV}")

    processable = [r for r in audit_rows if r["note"] in ("", None)]

    # --- Dataset-level rule summary ---
    print(f"\n  Edge rejections by rule (across {len(processable)} images):")
    edge_totals = {r: sum(row.get(f"rej_edge_{r}", 0) for row in processable)
                   for r in EDGE_RULES}
    print("    " + "    ".join(f"{r}: {edge_totals[r]}" for r in EDGE_RULES))

    print(f"\n  Surface rejections by rule (across {len(processable)} images):")
    surf_totals = {r: sum(row.get(f"rej_surf_{r}", 0) for row in processable)
                   for r in EDGE_RULES}
    print("    " + "    ".join(f"{r}: {surf_totals[r]}" for r in EDGE_RULES))

    # --- Top-10 by rejected_other (surface pits) ---
    top10_surf = sorted(processable, key=lambda r: r["rejected_other"], reverse=True)[:10]

    col_w = 44
    print(f"\n{'─' * 130}")
    print(f"  TOP 10 IMAGES BY rejected_other (surface/reclassified pits)")
    print(f"{'─' * 130}")
    print(
        f"  {'image':<{col_w}}  {'total':>7}  {'surf_rej':>8}  "
        f"{'macro':>5}  {'micro':>5}  "
        f"{'max_area':>10}  {'max_circ':>8}  surf_rules"
    )
    print(
        f"  {'-'*col_w}  {'-'*7}  {'-'*8}  {'-'*5}  {'-'*5}  "
        f"{'-'*10}  {'-'*8}  ----------"
    )
    for r in top10_surf:
        surf_str = _rule_summary_str(r, prefix="rej_surf")
        print(
            f"  {r['image']:<{col_w}}  {r['total_candidates']:>7}  "
            f"{r['rejected_other']:>8}  "
            f"{r['confirmed_macro']:>5}  {r['confirmed_micro']:>5}  "
            f"{r['rej_surf_max_area_um2']:>10.0f}  "
            f"{r['rej_surf_max_circ']:>8.4f}  {surf_str}"
        )
    print(f"{'─' * 130}\n")

    # --- Top-10 by rejected_edge ---
    top10_edge = sorted(processable, key=lambda r: r["rejected_edge"], reverse=True)[:10]

    print(f"\n{'─' * 115}")
    print(f"  TOP 10 IMAGES BY rejected_edge")
    print(f"{'─' * 115}")
    print(
        f"  {'image':<{col_w}}  {'total':>7}  {'rej_edge':>8}  "
        f"{'rej_surf':>8}  {'macro':>5}  {'micro':>5}  "
        f"{'max_area':>10}  edge_rules"
    )
    print(
        f"  {'-'*col_w}  {'-'*7}  {'-'*8}  {'-'*8}  {'-'*5}  {'-'*5}  "
        f"{'-'*10}  ----------"
    )
    for r in top10_edge:
        edge_str = _rule_summary_str(r, prefix="rej_edge")
        frac_str = (
            f"  ({r['rejected_edge'] / r['total_candidates'] * 100:.1f}%)"
            if r["total_candidates"] > 0 else ""
        )
        print(
            f"  {r['image']:<{col_w}}  {r['total_candidates']:>7}  "
            f"{r['rejected_edge']:>8}  {r['rejected_other']:>8}  "
            f"{r['confirmed_macro']:>5}  {r['confirmed_micro']:>5}  "
            f"{r['rej_edge_max_area_um2']:>10.0f}  {edge_str}"
            + frac_str
        )
    print(f"{'─' * 115}\n")

    # --- Overall totals ---
    total_edge_rej  = sum(r["rejected_edge"]    for r in processable)
    total_other_rej = sum(r["rejected_other"]   for r in processable)
    total_cands     = sum(r["total_candidates"] for r in processable)
    max_area_all    = max((r["rej_edge_max_area_um2"] for r in processable), default=0.0)
    print(f"  Dataset totals ({len(processable)} images):")
    print(f"    total_candidates    : {total_cands}")
    print(f"    rejected_edge       : {total_edge_rej}"
          + (f"  ({total_edge_rej / total_cands * 100:.1f}%)" if total_cands else ""))
    print(f"    rejected_other      : {total_other_rej}"
          + (f"  ({total_other_rej / total_cands * 100:.1f}%)" if total_cands else ""))
    print(f"    largest rej_edge pit: {max_area_all:.0f} µm²")
    print()


if __name__ == "__main__":
    main()
