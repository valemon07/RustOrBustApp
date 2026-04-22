# CLAUDE.md — Rust or Bust Pipeline

## Project Root
- Repo: `~/RustOrBustApp`
- Backend: `~/RustOrBustApp/BackendDev`
- All relative paths in this file (e.g. `/pipeline/`, `/tests/`, `data/raw/`) are relative to the BackendDev directory.

## Project Purpose
This is a materials science image analysis pipeline for detecting and 
classifying corrosion pits in optical microscopy images of aluminum 
aerospace specimens. Images are darkfield overview shots from a 
light microscope with an embedded green scale bar (bottom right corner).

## Domain Context (Read carefully)
- Images show polished cross-sections of aluminum specimens with a 
  fastener hole at the top edge
- Pits appear as DARK regions against a BRIGHT metallic surface
- The surrounding background (outside the specimen) is also DARK —
  this must not be confused with pits
- Polishing scratches appear as long thin linear dark streaks — 
  these must be EXCLUDED from pit detection
- The green scale bar in the bottom right corner is always present 
  and must be used for pixel-to-micron calibration
- Illumination is non-uniform (bright center, darker edges) — 
  always apply CLAHE before thresholding

## Tech Stack
- Python 3.11+
- opencv-python for all image processing
- scikit-learn for classification
- numpy, pandas for data handling
- pip + venv for package management
- macOS development, GPU available for future expansion

## Code Conventions
- Each pipeline stage is a standalone module in /pipeline/
- Every stage function must accept an image path OR a numpy array
- Every stage function must return BOTH the result AND a debug 
  visualization image (numpy array) so we can visually inspect outputs
- All measurements must be in micrometers (µm) in final outputs
- Never modify files in data/raw/ — always work on copies
- Use explicit variable names — no single letter variables except 
  loop indices

## Testing Approach
- Tests are simple runnable scripts in /tests/
- Each test script loads a real sample image and prints results + 
  saves a debug visualization to outputs/debug/
- Tests should PASS/FAIL with a clear printed message
- No pytest, no mocking — test against real images

## CSV Output Format
Each row = one image. Full field list (as of 2026-04-16):

| Column | Description |
|---|---|
| filename | Image filename |
| sample_id | Specimen ID parsed from filename |
| status | ok / flagged / error |
| flag_reason | Why image was flagged (blank if ok) |
| scale_um_per_px | Calibrated µm/px from scale bar |
| classification | moderate / severe / unknown |
| roi_width_um, roi_height_um | Bounding box of specimen mask in µm |
| mask_fill_ratio | hull_pixels / bbox_pixels (quality indicator) |
| mask_warning | low_coverage / high_coverage / none |
| roi_incomplete | True if any Stage 2 quality check failed |
| contrast_gamma_used | Gamma value that produced the largest hull |
| macro_pit_count | Pits ≥1500 µm² (matches ground truth) |
| micro_pit_count | Pits <1500 µm² |
| macro_density_per_cm | Macro pits per linear cm of ROI width |
| R1–R8 rejection columns | Per-rule rejection count for diagnostics |

**Important:** Ground truth comparison always uses `macro_pit_count` only.
Never merge macro and micro tiers without client approval.

## Pipeline Flags Module
`pipeline/pipeline_flags.py` defines all string constants used for flag reasons
and mask warnings. Import from there rather than hardcoding strings in stages.

## Git / Remote
- Remote: `https://github.com/valemon07/RustOrBustApp.git` (GitHub account: valemon07)
- Active feature branch: `feature/mask-quality`
- Main branch: `main`

## Current Stage Status
- [x] Stage 1: Scale bar detection
- [x] Stage 2: ROI extraction (+ gamma contrast sweep)
- [x] Stage 3: Pit detection
- [x] Stage 4: Density calculation
- [x] Stage 5: Classification (moderate / severe, scale-adaptive thresholds)
- [x] Stage 6: CSV export (consistency_check.csv, full field list including contrast_gamma_used)

## Known Challenges
- Non-uniform illumination must be corrected before thresholding
- Must distinguish specimen background from pit darkness
- Polishing scratches (high aspect ratio) must be filtered out
- Scale bar value varies per image — must be read dynamically
- Two pit tiers exist in output: macro (≥1500 µm², matches GT) 
  and micro (<1500 µm², full detection). Ground truth comparison 
  always uses macro tier only. Do not merge these tiers without 
  client approval.
- R5 minimum area coefficient is 84, derived from physical 
  minimum pit diameter of 10 µm (π·5² = 78.5 µm²). Do not 
  lower this without domain justification from the client.
- R6 isolation filter is intentionally inactive at high 
  magnification — this is correct behavior, not a bug.
- Two image types confirmed in dataset:
    Overview images: ~4.20 µm/px, 1000 µm scale bar
    High-mag images: ~1.05 µm/px, 150 µm scale bar
  Both are handled correctly by scale-aware thresholds.
## User-Adjustable Parameter System (added 2026-04-18)

### Philosophy
Rule thresholds (R1–R8 constants in `stage3_pit_detection.py`) are **module-level defaults
calibrated for the full dataset**. When a specific image is flagged for review by the user,
the correct fix is to add a per-image entry to `data/image_overrides.json` — or to pass
equivalent values through the frontend API — rather than changing source code constants.

> **Do NOT modify module-level constants in `stage3_pit_detection.py` or `stage2_roi.py`
> to fix a per-image false-positive or false-negative issue. Use the override system.**

### Override flow
`data/image_overrides.json` → `tests/run_full_test.py _run_one()` → `stage2_roi.extract_roi*` /
`stage3_pit_detection.detect_pits()`. The frontend API will eventually supply the same dict
directly to these functions without going through the JSON file.

### User-adjustable parameters

| Parameter | Location | Default | Direction to tighten (fewer false positives) | Notes |
|---|---|---|---|---|
| `gamma` | Stage 2 | auto (contrast sweep) | N/A — try 1.0 or 0.5 to darken | Skips contrast sweep; forces a fixed gamma |
| `morph_open_kernel_px` | Stage 2 | None (disabled) | Increase (e.g. 2–4) | Removes dark features narrower than this many pixels before Stage 3 |
| `r7_max_intensity_ratio` | Stage 3 R7 | 0.85 | Decrease (e.g. 0.72) | Rejects candidates less dark than this fraction of the surface mean |
| `r3_max_aspect_ratio` | Stage 3 R3 | 8.0 | Decrease (e.g. 5.0) | Rejects elongated candidates; cap applies to fine-scale base and via min() at medium/coarse |
| `r4_min_circularity` | Stage 3 R4 | 0.08 | Increase (e.g. 0.12) | Rejects irregular candidates; applies to standard tier only (area < 2000 µm²) |
| `r8_min_aspect_ratio` | Stage 3 R8 | 3.0 | Decrease (e.g. 2.0) | Catches less-elongated scratch fragments in R8 orientation test |

### Example image_overrides.json entry
```json
{
  "CR3-8_c-side_pit001": {
    "morph_open_kernel_px": 2,
    "stage3": {
      "r7_max_intensity_ratio": 0.72,
      "r3_max_aspect_ratio": 5.0
    }
  }
}
```

### Scale-adaptive interactions
- **R7**: the coarse-scale end (0.78 at ≥4 µm/px) is `min(0.78, override)` — a tighter
  override also tightens the coarse end.
- **R3**: medium (6.5) and coarse (5.0) scale constants are `min(constant, override)` — the
  override can only tighten at those scales, not loosen. Large pits (≥2000 µm²) always use
  MAX_ASPECT_RATIO_LARGE_PIT = 14.0 regardless of override.
- **R4**: only the standard tier (area < 2000 µm², scale ≥ 1.5 µm/px) uses the override.
  MIN_CIRCULARITY_LARGE_PIT (0.005) is domain-calibrated and not overridden.

## Known Pipeline Challenges (updated 2026-04-09)

### Challenge 6: Stage 2 hull under-coverage — mask stops short of specimen edges (partially resolved — ea05349)
**Status:** Mitigated; root cause not fully eliminated  
**Symptom:** The convex hull mask consistently under-covers the specimen — it stops short
of the true edges, causing Stage 3 to miss pits in the peripheral zone.  
**Root cause:** Otsu global thresholding on non-uniformly illuminated images misclassifies
dim specimen edges as background. CLAHE partially helps but is insufficient alone.  
**Fix implemented:** `extract_roi_contrast_sweep()` in `stage2_roi.py` — always tries all
four gamma values `[0.5, 1.0, 2.0, 3.0]` for every image and keeps the result that
produces the **largest hull pixel count** (`width_px × height_px × mask_fill_ratio`).
More coverage is always better in this dataset; no instance of genuine over-segmentation
has been observed by the client.  
**Result:** Mean fill ratio across dataset increased from 0.9143 → 0.9200 after switch to
max-coverage selection. 22 images improved, 5 slightly reduced, 36 unchanged.
`contrast_gamma_used` is logged to the output CSV for every image.  
**Controlled by:** `CONTRAST_SWEEP_ENABLED` and `CONTRAST_SWEEP_GAMMAS` in `config.py`.  
**Risk:** Extreme gamma values (very dark or very bright) could cause the Otsu threshold to
produce a qualitatively wrong hull on unusual images — inspect debug images if a new image
type is added to the dataset.

**History of failed approaches (do not re-attempt without new information):**  
1. Complex scoring (`roi_incomplete` flag + fill range + hull preservation penalty) →
   caused regressions; darkening gammas won by clearing `high_coverage` warnings, shrinking
   the hull rather than growing it.  
2. Trigger only on `roi_incomplete` → too conservative; under-coverage images without an
   explicit flag were not swept.  
3. Trigger on fill < 0.55 or any `mask_warning` → CR3-7_c-side_BF001 macro count dropped
   204 → 46 (catastrophic) because scoring rewarded clearing `high_coverage` by darkening.  
4. Raised `MASK_FILL_HIGH_THRESHOLD` to 0.97 + fill < 0.70 trigger → limited improvement,
   still gated by trigger condition.  
The client's insight that resolved this: **"There are no instances where coverage is too
high."** Simple max-area selection eliminates all scoring complexity.

---

### Challenge 1: Large edge-originating pits misclassified as edge features (resolved — 2026-04-18)
**Status:** Resolved  
**Affected images:** All overview images (~4.2 µm/px) and many fine-scale images  
**Two root causes fixed:**

1. **R2 ceiling too low at overview scale** (`MAX_PIT_AREA_UM2_SURFACE = 500k µm²`):  
   At ~4.2 µm/px genuine coalesced corrosion regions reach 600k–2.3M µm², all correctly
   inside the hull mask. Fix: scale-adaptive R2 ceiling — `MAX_PIT_AREA_UM2_SURFACE_COARSE = 5M µm²`
   applied when `scale ≥ 4.0 µm/px`. Background-leakage artifacts at 8–11 µm/px (14M/22M µm²)
   still exceed this and remain rejected. Result: `rej_surf_R2` dropped from 31 → 6 (only
   the legitimate ultra-coarse images remain).

2. **R3 applied to all small edge pits** (aspect ratio ceiling = 5.0 at coarse scale):  
   Pits at the specimen boundary can only grow inward, creating natural elongation that is a
   geometric artifact of position. R4 and R7 were already fully exempt for all edge pits;
   R3 now follows. Fix: changed `if not (pit_type == "edge" and area_um2 >= LARGE_PIT_AREA_UM2)`
   → `if pit_type != "edge"`. Result: `rej_edge_R3` dropped from 83 → 0 dataset-wide.

**Constants added:**  
- `MAX_PIT_AREA_UM2_SURFACE_COARSE = 5_000_000.0` µm² (new constant in stage3_pit_detection.py)

### Challenge 2: Scale-dependent pixel-floor noise (resolved — df57a9a)
Single-pixel noise at low magnification was admitted by the old area floor. 
Fixed in R5 with `effective_min = max(10, 84/scale, 15·scale²)`.

### Challenge 3: Large irregular pits rejected by circularity/aspect rules (resolved — df57a9a, re-resolved 2026-04-17)
Crevice and coalescing pits with area ≥ 2000 µm² were being discarded by R3/R4.
Initially fixed (df57a9a) by relaxing aspect ceiling to 12.0 and circularity floor to 0.04.
Re-opened: diagnostic data (CR3-8, CR3-9) showed genuine large corrosion zones reaching
circ ≈ 0.005–0.009, still below the 0.04 floor. Also, very large coalesced pits
(200–250k µm²) were hitting the 150k µm² R2 surface ceiling.

**Final fix (2026-04-17):**
- `MAX_PIT_AREA_UM2_SURFACE`: 150,000 → 500,000 µm² (aligns with reclassified ceiling)
- `MIN_CIRCULARITY_LARGE_PIT`: 0.04 → 0.005 (for pits ≥ 2000 µm²)
- `R5_FORMULA_CAP_UM2 = 200.0`: caps the `84/scale` term to prevent it growing > 200 µm²
  at very fine scales (< 0.5 µm/px) outside the normal operating range
- `MEDIUM_PIT_AREA_UM2_FINE = 400.0` + `MIN_CIRCULARITY_MEDIUM_FINE = 0.03`: at fine scale
  (< 1.5 µm/px), pits ≥ 400 µm² use 0.03 floor instead of 0.12 (catches complex medium
  pits at extreme fine scale, e.g. BF005 at 0.1546 µm/px)

**Results:** CR3-8_c-side_pit006: macro 7→12; CR3-9_9-side_pit003: 11→13;
CR3-9_9-side_pit005: 6→7; CR3-1_1-side_pit_BF005: confirmed largest pit as micro
(633 µm² < 1500 µm² macro threshold — correct behavior).

### Challenge 4: Surface scratches passing darkness threshold (resolved — df57a9a)
Scratches in the 0.70–0.91 brightness range were passing R7. Fixed by tightening 
threshold from 0.92 → 0.85 (confirmed pits max at 0.69).

### Challenge 5: Scale-dependent false positives from surface scratches (open)
**Status:** Open — fix in progress  
**Affected images:** High-scale images (≥4 µm/px), e.g. CR3-8_c8-side_pit005 
(scale=5.96, macro=191 — grossly overcounted)  
**Symptom:** Machining grain lines and surface scratches are segmented into 
short elongated blobs at low magnification and confirmed as macro pits. Rules 
R3/R5/R7 pass them individually because each fragment looks borderline-acceptable.  
**Root cause:** R3, R7 have no scale dependence. At 6 µm/px a 2×20 pixel scratch 
fragment covers ~1400 µm² with aspect ~3–4 — passing all current rules.  
**Proposed fix:** 
  - R8 (new): reject candidates whose major axis aligns within 20° of dominant 
    surface texture orientation AND aspect > 3 AND area < 5000 µm²
  - R3 scale-adaptive ceiling: 12→8→5 at scale <2 / 2–4 / >4 µm/px
  - R7 scale-adaptive darkness: 0.85→0.78 interpolated between 2–4 µm/px  
**Risk:** R8 dominant-orientation detection may be unreliable on isotropic 
surfaces — add entropy fallback to skip R8 if texture has no clear direction.  
**Validation targets:** CR3-8 macro count should drop substantially; 
moderate-class images (clean surface, ~1 µm/px) should be unaffected.