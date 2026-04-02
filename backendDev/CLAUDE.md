# CLAUDE.md — Rust or Bust Pipeline

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
