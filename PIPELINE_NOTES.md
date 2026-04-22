# Pipeline Notes

Reference document for pipeline configuration decisions, manual overrides, and
flag meanings. Update this file whenever `pipeline/config.py` changes.

---

## Excluded Specimens

Defined in `pipeline/config.py → EXCLUDED_SPECIMENS`.

These specimens are skipped entirely before any pipeline processing and appear
in test output with reason `excluded_specimen`. They are intentional close-up
or non-standard captures that fall outside the pipeline's operating scale range
(0.5–10.0 µm/px) and cannot produce meaningful pit-density numbers.

| Specimen | Reason |
|---|---|
| CR3-3 | All images are extreme high-magnification cross-sections (0.08–0.26 µm/px). Includes `ci-side` and `3-side` captures. |

---

## Images with No Scale Bar

Defined in `pipeline/config.py → NO_SCALE_BAR_IMAGES`.

These image stems have no embedded green scale bar. They are skipped cleanly
with reason `no_scale_bar_found` rather than raising an exception. They cannot
be processed without a manual µm/px value.

| Filename | Notes |
|---|---|
| `cr3-1_initiation_pit_birdseye_view001` | No scale bar present |
| `cr3-1_initiation_pit_sideview001` | No scale bar present |
| `cr3-1_initiation_pit_sideview002` | No scale bar present |

---

## Manual Scale Overrides

Defined in `pipeline/config.py → MANUAL_SCALE_OVERRIDES`.

Keys are filename **stems** (no directory, no extension). Values are the µm
label printed on the scale bar — **not** µm/px. The pipeline divides this by
the detected bar pixel width to derive µm/px, identical to OCR-based detection.

These are needed when:
- Tesseract OCR finds the bar blob but cannot parse the label text (low
  contrast, unusual rendering, partial crop).
- The OCR reads a plausible but wrong number (e.g. CR3-3 darkfield images
  where OCR read "120" instead of the correct value).

| Stem | µm label | Reason |
|---|---|---|
| `cr3-3_ci-side006` | 30 | OCR misread — extreme high-mag crop |
| `cr3-3_ci-side008` | 30 | OCR misread — extreme high-mag crop |
| `cr3-3_ci-side009` | 30 | OCR misread — extreme high-mag crop |
| `cr3-3_ci-side010` | 30 | OCR misread — extreme high-mag crop |
| `cr3-3_ci-side_DF001` | 120 | OCR misread — darkfield overview |
| `cr3-3_ci-side_DF002` | 120 | OCR misread — darkfield overview |
| `CR3-1_1-side_pit_BF007` | 60 | OCR could not parse label |
| `CR3-1_1-side_pit_DF001` | 60 | OCR could not parse label |
| `CR3-7_c-side_BF009` | 300 | OCR could not parse label |
| `CR3-8_c8-side_pit002` | 150 | OCR could not parse label |
| `cr3-1_initiation_pit_birdseye_view004` | 500 | OCR could not parse label |
| `cr3-3_3-side001` | 30 | OCR misread — high-mag |
| `cr3-3_3-side_DF001` | 120 | OCR misread — darkfield |
| `cr3-7_7_side_overview001` | 1000 | OCR could not parse label |
| `cr3-9_c_side_overview001` | 1000 | OCR could not parse label |

---

## Flag Reasons

Each flagged image in `test_pipeline_consistency` carries one or more of these
reason strings. Multiple reasons can apply to the same image.

| Reason | Meaning | Action |
|---|---|---|
| `excluded_specimen` | Specimen is in `EXCLUDED_SPECIMENS` — skipped before processing | Expected; no fix needed |
| `no_scale_bar_found` | No green scale bar blob detected, and stem is in `NO_SCALE_BAR_IMAGES` | Expected; add a manual µm/px override to process |
| `exception: ...` | An unhandled exception occurred during pipeline stages 1–4 | Investigate; likely an OCR failure — add to `MANUAL_SCALE_OVERRIDES` |
| `scale X outside [0.5, 10.0]` | Computed µm/px is outside the pipeline's valid range | Check image type; may be out-of-scope close-up or OCR misread |
| `macro_pit_count=0` | Pipeline completed but found no pits ≥ 1500 µm² | May be correct — some frames genuinely contain only micro-pits. Verify visually before treating as a bug |
| `roi_width Xum < 200` | ROI bounding box width < 200 µm | Usually paired with a bad scale; the ROI is too small to measure reliably |
| `roi_height Xum < 200` | ROI bounding box height < 200 µm | Same as above |

---

## Macro vs. Micro Pit Tiers

The pipeline classifies every confirmed pit into one of two tiers:

| Tier | Area threshold | Notes |
|---|---|---|
| **macro** | ≥ 1500 µm² | Matches human-expert counting scale (calibrated against UVA CESE slide deck, 2026-02-13). Used for all ground-truth-comparable density metrics. |
| **micro** | < 1500 µm², above R5 floor | Detected but excluded from ground-truth comparison. Preserved in output for exploratory analysis only. |

**Do not merge these tiers or lower the 1500 µm² threshold without client
approval.** The threshold corresponds to ~44 µm diameter and was derived from
calibration against expert manual counts.

---

## Scale Bar Detection Notes

- **Search region**: bottom 15% × right 32% of the image. Restricted to
  this corner so that specimen illumination (including bright-green darkfield
  surfaces) never contaminates the green HSV threshold.
- **OCR**: uses `pytesseract` with `--psm 7` on an upscaled crop of the label
  region. Requires both `pip install pytesseract` and `brew install tesseract`.
- **Two confirmed image types in dataset**:
  - Overview images: ~4.20 µm/px, 1000 µm scale bar
  - High-mag images: ~1.05 µm/px, 150 µm scale bar
