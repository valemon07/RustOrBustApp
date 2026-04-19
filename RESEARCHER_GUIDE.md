# Rust or Bust — Researcher Guide

This guide explains how to use the Rust or Bust application to analyze corrosion pit images,
what parameters you can adjust, and what the outputs mean.

---

## What the App Does

Rust or Bust is a desktop application for automated detection and quantification of
corrosion pits in optical microscopy images of aluminum aerospace specimens.

You supply a folder of brightfield or darkfield microscope images. The pipeline:

1. Reads the green scale bar embedded in the bottom-right corner of each image to
   calibrate pixel-to-micron conversion.
2. Extracts a mask of the specimen surface (the region of interest, or ROI), excluding
   the dark background and fastener hole.
3. Detects candidate dark regions (pits) within the ROI.
4. Applies a series of rejection rules (R1–R8) to remove scratches, noise, and artifacts.
5. Classifies surviving pits as **macro** (≥ 1500 µm²) or **micro** (< 1500 µm²).
6. Exports one row per image to a CSV file with counts, densities, and diagnostic data.

Images that the pipeline cannot process reliably are automatically **flagged for review**
so you can inspect them manually.

---

## Running the App

1. Launch the application.
2. Click **Upload Images** and select a folder of microscope images (JPEG or PNG).
3. Optionally adjust pipeline settings (see below) before processing.
4. Click **Run Pipeline**.
5. When processing completes, the output CSV and annotated images are saved to an
   `outputs/` folder next to the selected image folder.

---

## Pipeline Settings

Open the **Settings** panel to adjust the parameters below. Each parameter has a
**Default** button to restore its calibrated value.

> **Important:** These parameters are calibrated for the full dataset. Only change them
> when a specific image is being misflagged. Do not change them to "improve" results
> globally — doing so may cause regressions on other images.

### Exposure Gamma

| Setting | Default | Range |
|---|---|---|
| Exposure Gamma | 1.0 | 0 – 5 |

Controls the brightness correction applied before the surface mask is generated.

- **1.0** — neutral, no correction (default).
- **< 1.0** (e.g. 0.5) — darkens the image. Use when the mask over-expands into the
  dark background.
- **> 1.0** (e.g. 2.0–3.0) — brightens the image. Use when dim specimen edges are
  being missed by the mask.
- **0** — automatic contrast sweep: the pipeline tries gamma values of 0.5, 1.0, 2.0,
  and 3.0 and keeps whichever produces the largest mask. Slower but fully automatic.

### Morph Open Kernel (px)

| Setting | Default | Range |
|---|---|---|
| Morph Open Kernel | 0 (disabled) | 0 – 10 |

Applies a morphological opening operation before pit detection. This erases dark features
narrower than the kernel size (in pixels), which removes thin scratches and grain lines
from consideration before any rules are applied.

- **0** — disabled (default).
- **2–4** — recommended range if surface scratches are producing false positives.

### R7 Darkness Threshold

| Setting | Default | Range |
|---|---|---|
| R7 Darkness Threshold | 0.85 | 0.1 – 1.0 |

Rejects candidates whose mean intensity is brighter than this fraction of the local
surface mean. Pits should be significantly darker than the surrounding metal.

- **Decrease** (e.g. 0.72) to require pits to be darker — reduces false positives from
  faint scratches or surface texture.
- **Increase** only if genuine deep pits are being rejected.

### R3 Max Aspect Ratio

| Setting | Default | Range |
|---|---|---|
| R3 Max Aspect Ratio | 8.0 | 1 – 20 |

Rejects elongated, scratch-like candidates. The aspect ratio is the ratio of the
candidate's longest dimension to its shortest.

- **Decrease** (e.g. 5.0) to reject less-elongated features — useful when short scratch
  fragments are being counted as pits.
- **Note:** Edge pits (touching the specimen boundary) are always exempt from this rule,
  since their geometry is naturally elongated.

### R4 Min Circularity

| Setting | Default | Range |
|---|---|---|
| R4 Min Circularity | 0.08 | 0 – 1 |

Rejects irregularly shaped candidates. Circularity = 1 is a perfect circle; 0 is a
straight line.

- **Increase** (e.g. 0.12) to require rounder pit shapes — reduces irregular noise
  features.
- Only applies to candidates with area < 2000 µm². Large pits may be naturally irregular
  due to coalescence and use a much lower floor (0.005).

### R8 Scratch Aspect Ratio

| Setting | Default | Range |
|---|---|---|
| R8 Min Aspect Ratio | 3.0 | 1 – 10 |

The minimum aspect ratio for the orientation-based scratch rejection rule (R8). R8 rejects
candidates whose long axis aligns with the dominant surface texture direction.

- **Decrease** (e.g. 2.0) to also catch less-elongated scratch segments.

---

## Output Files

After processing, the app creates an `outputs/` folder containing:

### `results.csv`

One row per processed image. Columns:

| Column | Description |
|---|---|
| `file_name` | Original image filename |
| `specimen_id` | Specimen ID parsed from the filename |
| `scale_bar_um` | Scale bar value (µm) read from the image — verify if results look wrong |
| `pit_count` | **Macro pit count** (area ≥ 1500 µm²). This is the primary metric for ground-truth comparison. |
| `pit_density_per_cm` | Macro pits per linear cm of ROI width |
| `mean_pit_depth` | Mean width of all confirmed macro pits (µm) |
| `max_pit_depth` | Width of the largest confirmed macro pit (µm) |
| `all_pit_depths` | Semicolon-separated list of individual macro pit widths (µm) |
| `flagged_for_review` | `Yes` or `No` |
| `reason_for_flag` | Semicolon-separated list of flag reasons (blank if not flagged) |
| `exposure_contrast_used` | Gamma value actually used for mask generation |
| `R1_rejections` – `R8_rejections` | Count of candidates rejected by each rule — useful for diagnosing why an image has an unexpectedly low or high pit count |

### Annotated Images

Annotated debug images are saved alongside the CSV. They show:

- The specimen ROI mask (green overlay)
- Detected macro pits (red outlines)
- Detected micro pits (yellow outlines)
- Rejected candidates (gray outlines)

---

## Flag Reasons

Images flagged for review carry one or more of these reason strings:

| Reason | Meaning | What to Do |
|---|---|---|
| `excluded_specimen` | Specimen is in the exclusion list — skipped entirely | Expected; no action needed |
| `no_scale_bar_found` | No green scale bar detected in the image | Check image quality; the pipeline cannot process this image without a scale bar |
| `exception: ...` | An unhandled error occurred during processing | Check the image for unusual formatting; contact the development team |
| `scale X outside [0.5, 10.0]` | Computed µm/px is outside the valid operating range | Verify the scale bar is readable; may be an extreme close-up outside scope |
| `macro_pit_count=0` | Pipeline completed but found no macro pits | May be correct — verify visually before treating as a failure |
| `roi_width Xum < 200` | The ROI bounding box width is less than 200 µm | Usually indicates a bad scale reading; the image may be out of scope |
| `roi_height Xum < 200` | The ROI bounding box height is less than 200 µm | Same as above |

---

## Pit Size Tiers

| Tier | Area | Notes |
|---|---|---|
| **Macro** | ≥ 1500 µm² (≥ ~44 µm diameter) | Used for all ground-truth comparison and density metrics. Calibrated against expert manual counts. |
| **Micro** | < 1500 µm², above detection floor | Detected and included in annotated images and CSV for exploratory use, but **not** used in ground-truth comparison. |

> Do not compare macro and micro counts combined against ground-truth data.
> The 1500 µm² threshold was derived from expert calibration and must not be changed
> without client approval.

---

## Rejection Rules Reference

These rules filter candidate dark regions inside the ROI before they are confirmed as pits.
The `R1_rejections` through `R8_rejections` columns in the CSV show how many candidates
each rule rejected for that image.

| Rule | Name | What It Removes |
|---|---|---|
| R1 | Minimum area | Candidates below the scale-adaptive pixel-noise floor |
| R2 | Maximum area | Candidates larger than the scale-adaptive surface ceiling (background leakage) |
| R3 | Max aspect ratio | Elongated, scratch-like candidates |
| R4 | Min circularity | Irregular, non-pit-shaped candidates |
| R5 | Area floor | Second area floor, scale-adaptive formula |
| R6 | Isolation | Candidates not sufficiently isolated from neighbors (inactive at high magnification — expected behavior) |
| R7 | Darkness threshold | Candidates not dark enough relative to the surface mean |
| R8 | Orientation | Candidates whose long axis aligns with the dominant surface texture (scratch direction) |

---

## Installation

See [INSTALL.md](INSTALL.md) for full setup instructions.

---

## Support

If you encounter unexpected results, first check:
1. The annotated debug image — does the ROI mask look correct?
2. The `reason_for_flag` column — is the image flagged, and why?
3. The `R1`–`R8` rejection columns — is one rule rejecting far more candidates than usual?

If the issue persists, contact the development team with the image filename and the
relevant CSV row.
