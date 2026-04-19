# Pipeline Report — 2026-04-14

## Contents of This Folder

| File pattern | Count | Description |
|---|---|---|
| `<stem>.jpg` | 63 | Stage 3 annotated images — all confirmed pits labeled |
| `<stem>_stage2.jpg` | 63 | Stage 2 ROI/mask images — hull boundary + candidate regions |
| `consistency_check.csv` | 1 | Per-image metrics table with per-rule rejection counts |
| `REPORT.md` | 1 | This file |

---

## Pipeline Changes Since Full Test 2 (2026-04-09 full test 2)

### R5 — Pixel-count floor added

**Rule:** `effective_min = max(10, 84/scale, MIN_PIXEL_COUNT × scale²)` where `MIN_PIXEL_COUNT = 15`.

**Why:** At overview magnification (~4.2 µm/px) the old scale-aware coefficient floor collapsed
to ~20 µm² (≈ 1 pixel), admitting single-pixel noise blobs that passed all other geometric
filters. Adding a pixel-count floor of 15 px raises the effective minimum at overview scale to
265 µm² while leaving high-mag images unaffected (16.5 µm² at
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

## Pipeline Run Results — 2026-04-14

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
| macro_pit_count=0 | 4 |
| no_scale_bar_found | 3 |
| roi_height | 3 |
| roi_width | 1 |
| scale | 6 |

### Per-class statistics (in-scope successful images only)

| Class | n | Macro density (pits/cm) | Macro pit count | Scale (µm/px) |
|---|---|---|---|---|
| moderate | 9 | 52.53 ± 77.85 | 14.67 ± 24.14 | 0.81 ± 0.94 |
| severe | 54 | 91.04 ± 87.75 | 45.67 ± 66.45 | 2.92 ± 2.05 |

### Overall macro density (all 63 successful images)

| Metric | Value |
|---|---|
| Mean | 85.54 pits/cm |
| Std | 87.45 pits/cm |
| Min | 0.00 pits/cm |
| Max | 391.63 pits/cm |

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

1. The R5 pixel floor (15 px × scale² µm²  (at 4.2 µm/px → 265 µm², at 1.05 µm/px → 16.5 µm²)) significantly reduces
   noise at overview magnification. Monitor whether any real small pits near the floor
   are lost in high-density overview images.

2. The R3/R4 area-conditional relaxation (≥ 2000 µm²) recovers large irregular pits.
   The borderline report in the filter validation test flags pits near the new 12.0
   aspect ceiling — inspect these visually if counts change unexpectedly.

3. R7 at 0.85 more aggressively rejects bright surface scratches. If any image class
   shows a significant count reduction, check the intensity_ratio distribution in the
   validation test output.
