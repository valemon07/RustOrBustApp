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
Each row = one image
Columns: filename, sample_id, scale_um_per_px, pit_count, 
         pit_density_per_cm, classification, 
         mean_pit_width_um, max_pit_width_um

## Current Stage Status
- [x] Stage 1: Scale bar detection
- [x] Stage 2: ROI extraction  
- [x] Stage 3: Pit detection
- [x] Stage 4: Density calculation
- [ ] Stage 5: Classification
- [ ] Stage 6: CSV export

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
## Known Pipeline Challenges (updated 2026-04-09)

### Challenge 1: Large edge-originating pits misclassified as edge features
**Status:** Open — fix in progress  
**Affected images:** CR3-7_c-side_BF007 and similar severe-class images with 
finger-like or coalescing pits that begin at the sample edge  
**Symptom:** Stage 2 mask correctly segments these pits; Stage 3 classifies them 
as `edge-macro` and rejects them, yielding anomalously low macro pit counts  
**Root cause (hypothesized):** Edge-zone classification uses a binary touch test — 
any candidate that intersects the edge buffer is labeled edge-macro regardless of 
how much of its area is in the interior  
**Proposed fix:** Replace binary touch test with an area-overlap fraction check; 
pits with <60% of area in the edge zone should be reclassified as surface-macro. 
For pits ≥ 2000 µm², also apply a centroid-location test as a secondary criterion.  
**Risk:** Could increase false positives if large background regions near the edge 
pass the overlap check — validate on full test suite after change.

### Challenge 2: Scale-dependent pixel-floor noise (resolved — df57a9a)
Single-pixel noise at low magnification was admitted by the old area floor. 
Fixed in R5 with `effective_min = max(10, 84/scale, 15·scale²)`.

### Challenge 3: Large irregular pits rejected by circularity/aspect rules (resolved — df57a9a)
Crevice and coalescing pits with area ≥ 2000 µm² were being discarded by R3/R4. 
Fixed by relaxing aspect ceiling to 12.0 and circularity floor to 0.04 for that 
size class.

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