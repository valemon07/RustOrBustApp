# Pipeline Report — 2026-04-09 Full Test 2

## Contents of This Folder

| File pattern | Count | Description |
|---|---|---|
| `<stem>.jpg` | 63 | Stage 3 annotated images — all confirmed pits labeled |
| `<stem>_stage2.jpg` | 63 | Stage 2 ROI/mask images — hull boundary + candidate regions |
| `consistency_check.csv` | 1 | Per-image metrics table |
| `REPORT.md` | 1 | This file |

---

## Pipeline Changes Since Full Test 1 (2026-04-07)

### R2 — Surface pit area ceiling raised: 50,000 → 150,000 µm²

**Why:** The old 50,000 µm² ceiling was calibrated for high-magnification images
(1.05 µm/px), where it corresponds to ~213×213 px — correctly rejecting impossible
blobs. At overview magnification (4.2 µm/px), 50,000 µm² is only ~53×53 px. Real
large corrosion features at overview scale routinely exceed this limit and were
incorrectly rejected. The new 150,000 µm² ceiling is consistent with the edge-pit
ceiling and accommodates the full observed size range of real corrosion damage.

### R7 — Darkness confirmation added (surface pits only)

**Rule:** Reject surface candidates whose `intensity_ratio ≥ 0.92`,
where `intensity_ratio = mean_pit_pixel_intensity / mean_surface_intensity`.

**Why:** Real corrosion pits are distinctly darker than the surrounding polished
metal surface. Stage 2's morphological closing sometimes produces candidate regions
that pass all geometric filters (area, aspect, circularity) but are not
meaningfully dark — they are surface texture variation or closing artefacts.
The 0.92 threshold rejects these without affecting real pits: confirmed pit
intensity ratios across all images ranged 0.03–0.69, well below the threshold.
Edge pits are exempt because their intensity is mixed with background at the hole
boundary.

### Previous fixes (carried forward from earlier sessions)

- **R4 circularity exempt for edge pits** — edge pits wrap the curved fastener
  hole and always have low circularity by geometry; applying R4 incorrectly
  rejected large real edge pits.
- **R2 edge ceiling at 150,000 µm²** — raised from 50,000 µm² after diagnostic
  confirmed a 53,602 µm² real edge pit was being blocked.

---

## Active Filter Rules

| Rule | Applies to | Condition | Rationale |
|---|---|---|---|
| R1 | all | area < 10 µm² | Sub-resolution absolute floor |
| R2 | surface | area > 150,000 µm² | Too large to be a surface pit |
| R2 | edge | area > 150,000 µm² | Too large even for hole-boundary pits |
| R3 | all | aspect ratio > 8.0 | Polishing scratch rejection |
| R4 | surface only | circularity < 0.08 | Polishing scratch rejection |
| R5 | all | area < max(10, 84/scale) µm² | Scale-aware noise floor |
| R6 | all | isolated AND bottom 25th pct area | Small isolated noise (≥10 survivors) |
| R7 | surface only | intensity_ratio ≥ 0.92 | Not distinctly dark → not a pit |

---

## Pipeline Run Results — 2026-04-09

### Dataset

| Category | Count |
|---|---|
| Total images | 74 |
| Excluded (CR3-3, out-of-scope) | 8 |
| No scale bar | 3 |
| Successful | 63 |
| Exceptions | 0 |

### Flagged images (17 total)

| Reason | Count |
|---|---|
| excluded_specimen | 8 |
| scale outside [0.5, 10.0] µm/px | 6 |
| no_scale_bar_found | 3 |
| macro_pit_count = 0 | 3 |
| roi_width < 200 µm | 1 |
| roi_height < 200 µm | 3 |

### Per-class statistics (in-scope successful images only)

| Class | n | Macro density (pits/cm) | Macro pit count | Scale (µm/px) |
|---|---|---|---|---|
| moderate | 9 | 53.25 ± 70.58 | 13.7 ± 22.1 | 0.814 ± 0.937 |
| severe | 54 | 92.81 ± 89.11 | 48.1 ± 75.6 | 2.916 ± 2.054 |

### Overall macro density (all 63 successful images)

| Metric | Value |
|---|---|
| Mean | 87.16 pits/cm |
| Std | 87.80 pits/cm |
| Min | 0.00 pits/cm |
| Max | 390.03 pits/cm |

---

## Stage 3 Filter Validation Test Results

Run on 5 anchor images spanning both magnification levels and classes.

| Image | Macro | Floor | Invariant | R7 rejections | Dominant rule |
|---|---|---|---|---|---|
| CR3-7_c-side_BF004.jpg | 7 | ≥5 PASS | PASS | 0 | R5 (122) |
| CR3-8_c-side_pit001.jpg | 67 | ≥50 PASS | PASS | 0 | R3 (10) |
| cr3-8_8_side_overview001.jpg | 219 | ≥150 PASS | PASS | 0 | R3 (12) |
| CR3-9_c-side_pit002.jpg | 5 | ≥3 PASS | PASS | 0 | R5 (151) |
| cr3-1_initiation_pit_birdseye_view002.jpg | 47 | ≥30 PASS | PASS | 0 | R3 (6) |

**All checks passed.** Confirmed surface pit intensity ratios: 0.03–0.69 across
all anchor images (threshold 0.92) — R7 is positioned correctly above real pit
darkness, not cutting legitimate detections.

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

1. Several micro surface pits cluster near the R5 floor (80–90 µm²) in
   high-magnification images. If small pit sensitivity needs to increase,
   the `SCALE_AWARE_AREA_COEFF` (currently 84) can be lowered with caution.

2. Two large surface pits in overview images have circularity near the R4
   threshold (~0.08–0.09). These are very irregular large features that
   currently pass — worth visual inspection to confirm they are real pits
   and not resin/mounting artefacts.

3. CR3-7_c-side_BF006 remains flagged (macro=0, 26 micro pits detected).
   All confirmed pits are sub-1500 µm² — confirmed by diagnostic as
   genuinely sub-macro corrosion at this magnification.
