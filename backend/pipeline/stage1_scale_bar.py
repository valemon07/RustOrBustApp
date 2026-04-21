"""
Stage 1: Scale Bar Detection

Detects the green scale bar in the bottom-right corner of each microscopy
image and returns the pixel-to-micron conversion factor.

The scale bar is a bright-green comb/ruler shape with a numeric µm label
(e.g. "150 µm") printed in the same green colour beside it.

Strategy
--------
1. Crop to the bottom-right 30 % × 20 % of the image where the bar lives.
2. HSV-threshold for the specific green used by the microscope software.
3. Use morphological closing with a wide horizontal kernel to merge the
   individual comb ticks into a single solid blob.
4. Pick the most horizontally elongated blob as the bar; measure its width
   in pixels.
5. Read the µm label via pytesseract OCR (with preprocessing), falling back
   to a manual override if OCR is unavailable.
6. Return scale_um_per_px = um_value / bar_px_width.

Dependencies
------------
- opencv-python, numpy  (always required)
- pytesseract + tesseract system binary  (required for OCR)
  Install: pip install pytesseract
           brew install tesseract   # macOS
"""

import re

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Tuneable constants
# ---------------------------------------------------------------------------

# Fraction of image dimensions that define the bottom-right search region.
# Bottom 15 % × right 32 % — keeps specimen illumination (even bright-green
# darkfield) outside the search window regardless of image type.
ROI_Y_FRACTION = 0.85   # start looking from 85 % down the image
ROI_X_FRACTION = 0.68   # start looking from 68 % across the image

# HSV bounds for the microscope scale-bar green.
# The bar is a vivid lime-green; we keep saturation and value floors high to
# avoid matching the golden specimen surface.
HSV_LOWER_GREEN = np.array([35,  80,  80], dtype=np.uint8)
HSV_UPPER_GREEN = np.array([90, 255, 255], dtype=np.uint8)

# Minimum contour area (px²) — filters single-pixel noise.
MIN_BLOB_AREA = 15

# Horizontal closing kernel width: wide enough to bridge the gaps between
# comb ticks (which can be ~5–15 px apart) without merging text blobs.
H_CLOSE_KERNEL_W = 20
H_CLOSE_KERNEL_H = 3

# Factor by which the ROI is upscaled before OCR (larger = better accuracy).
OCR_UPSCALE = 4


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------

class ScaleBarNotFoundError(RuntimeError):
    """Raised when no green scale-bar blob can be located in the image."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_image(image_input):
    """Return a BGR uint8 ndarray from a file path or an existing array."""
    if isinstance(image_input, str):
        image = cv2.imread(image_input)
        if image is None:
            raise FileNotFoundError(f"Cannot load image: {image_input}")
        return image
    return image_input.copy()


def _isolate_green(bgr_roi):
    """Return a binary mask of green pixels in a BGR region."""
    hsv = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2HSV)
    raw_mask = cv2.inRange(hsv, HSV_LOWER_GREEN, HSV_UPPER_GREEN)

    # Horizontal closing to merge comb ticks into one solid bar blob.
    h_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (H_CLOSE_KERNEL_W, H_CLOSE_KERNEL_H)
    )
    merged_mask = cv2.morphologyEx(raw_mask, cv2.MORPH_CLOSE, h_kernel)
    return merged_mask, raw_mask


def _find_bar_contour(merged_mask, verbose=False):
    """
    Return the contour that best represents the horizontal scale bar.

    Selection criterion: largest width-to-height ratio among blobs with
    area >= MIN_BLOB_AREA.  The bar is wide and short; text characters are
    taller relative to their width.

    When verbose=True, prints every candidate blob with its bbox, area, and
    aspect ratio so callers can diagnose false-positive selections.
    """
    contours, _ = cv2.findContours(
        merged_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None

    best_contour = None
    best_ratio = -1.0
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < MIN_BLOB_AREA:
            continue
        bx, by, bw, bh = cv2.boundingRect(contour)
        ratio = bw / max(bh, 1)
        candidates.append((ratio, area, bx, by, bw, bh, contour))
        if ratio > best_ratio:
            best_ratio = ratio
            best_contour = contour

    if verbose:
        print(f"  [Stage 1 debug] blobs found    : {len(candidates)}")
        for i, (ratio, area, bx, by, bw, bh, _) in enumerate(
            sorted(candidates, key=lambda c: -c[0])
        ):
            marker = " ← SELECTED" if (best_contour is not None
                                        and ratio == best_ratio) else ""
            print(f"    blob #{i+1}: bbox=({bx},{by},{bw},{bh})"
                  f"  area={area:.0f}  ratio={ratio:.1f}{marker}")

    return best_contour


def _read_um_value_ocr(bgr_roi):
    """
    Run pytesseract on the ROI and return the first integer found.

    Pre-processing steps:
    1. Build the green HSV mask (same threshold as bar detection) — this
       already cleanly isolates both the scale bar ticks AND the text label
       against a black background, without any specimen noise.
    2. Find the bounding box of all green pixels.
    3. Crop to the lower 45 % of that box — where the "150 µm" label lives
       (the comb ticks occupy the upper portion).
    4. Upscale to a minimum height of 80 px for sub-pixel character detail.
    5. Dilate slightly to thicken thin strokes.
    6. Run Tesseract in single-block mode; parse the first integer >= 10.

    Returns the µm value as a float, or None if OCR fails / is unavailable.
    """
    try:
        import pytesseract
    except ImportError:
        return None

    # --- Build the clean green binary mask --------------------------------
    hsv = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(hsv, HSV_LOWER_GREEN, HSV_UPPER_GREEN)

    green_ys, green_xs = np.where(green_mask > 0)
    if len(green_xs) == 0:
        return None

    gx_min, gx_max = int(green_xs.min()), int(green_xs.max())
    gy_min, gy_max = int(green_ys.min()), int(green_ys.max())
    green_h = gy_max - gy_min

    # --- Crop to the label region (lower 45 % of the green bounding box) --
    # The scale bar ticks are in the upper ~55 %; the text box is below them.
    label_y_start = gy_min + int(green_h * 0.55)
    label_crop = green_mask[label_y_start : gy_max + 2,
                            gx_min        : gx_max + 2]

    if label_crop.size == 0 or np.count_nonzero(label_crop) == 0:
        return None

    # --- Upscale so the shortest dimension is at least 40 px ---------------
    # (the label box is typically ~35–40 px tall; 2× is sufficient for PSM 7)
    crop_h, crop_w = label_crop.shape[:2]
    min_height = 40
    scale_up = max(2, min_height // max(crop_h, 1))
    label_large = cv2.resize(
        label_crop, None,
        fx=scale_up, fy=scale_up,
        interpolation=cv2.INTER_NEAREST
    )

    # --- Dilate slightly to thicken thin strokes ---------------------------
    dil_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    label_large = cv2.dilate(label_large, dil_kernel, iterations=1)

    # --- OCR — PSM 7: treat image as a single text line --------------------
    ocr_config = "--psm 7 -c tessedit_char_whitelist=0123456789µuUmM ."
    raw_text = pytesseract.image_to_string(label_large, config=ocr_config)

    numbers = re.findall(r'\d+', raw_text)
    if numbers:
        candidates = [int(n) for n in numbers if int(n) >= 10]
        if candidates:
            return float(max(candidates))

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_scale_bar(image_input, um_value_override=None, verbose=False):
    """
    Detect the green scale bar and compute the scale factor.

    Parameters
    ----------
    image_input : str or numpy.ndarray
        Path to the image file or a BGR numpy array.
    um_value_override : float or None
        If pytesseract is not installed, pass the known µm value here
        (e.g. ``um_value_override=150.0``).
    verbose : bool
        When True, print bar width, OCR value, scale factor, and bounding
        box coordinates to stdout for debugging.

    Returns
    -------
    scale_um_per_px : float
        Micrometers per pixel derived from the scale bar.
    um_value : float
        The µm label read from the scale bar (via OCR or override).
        Divide scale_um_per_px into this to recover the bar pixel width.
    debug_vis : numpy.ndarray
        BGR image with the detected bar highlighted in red, the measured
        pixel width, and the computed scale factor.

    Raises
    ------
    RuntimeError
        If the scale bar cannot be found or the µm value cannot be read.
    """
    image = _load_image(image_input)
    img_h, img_w = image.shape[:2]

    # --- 1. Crop to bottom-right search region ----------------------------
    roi_y0 = int(img_h * ROI_Y_FRACTION)
    roi_x0 = int(img_w * ROI_X_FRACTION)
    roi_bgr = image[roi_y0:, roi_x0:]

    if roi_bgr.size == 0:
        raise RuntimeError("ROI crop produced an empty array — check image dimensions.")

    # --- 2. Green masking and blob detection -------------------------------
    merged_mask, raw_mask = _isolate_green(roi_bgr)

    if verbose:
        green_px = int(np.count_nonzero(raw_mask))
        print(f"  [Stage 1 debug] green pixels   : {green_px} in search ROI")

    bar_contour = _find_bar_contour(merged_mask, verbose=verbose)
    if bar_contour is None:
        raise ScaleBarNotFoundError(
            "No green blobs found in the bottom-right region. "
            "Check HSV_LOWER_GREEN / HSV_UPPER_GREEN constants."
        )

    bar_x, bar_y, bar_w, bar_h = cv2.boundingRect(bar_contour)

    # bar_w is the pixel span of the scale bar — this is our denominator.
    bar_px_width = bar_w

    # --- 3. Read µm value -------------------------------------------------
    um_value = um_value_override
    if um_value is None:
        um_value = _read_um_value_ocr(roi_bgr)

    if um_value is None:
        raise RuntimeError(
            "Could not read the µm value from the scale bar label.\n"
            "Options:\n"
            "  1. Install pytesseract:  pip install pytesseract\n"
            "                           brew install tesseract\n"
            "  2. Pass the value directly: detect_scale_bar(img, um_value_override=150.0)"
        )

    # --- 4. Compute scale factor ------------------------------------------
    scale_um_per_px = um_value / bar_px_width

    # Absolute coordinates of the bar in the full image.
    abs_x0 = roi_x0 + bar_x
    abs_y0 = roi_y0 + bar_y
    abs_x1 = abs_x0 + bar_w
    abs_y1 = abs_y0 + bar_h

    if verbose:
        source = "input image" if isinstance(image_input, str) else "numpy array"
        print(f"  [Stage 1 debug] input          : {source}")
        print(f"  [Stage 1 debug] image size     : {img_w} x {img_h} px")
        print(f"  [Stage 1 debug] search region  : x=[{roi_x0}:{img_w}]  y=[{roi_y0}:{img_h}]")
        print(f"  [Stage 1 debug] bar bbox (full): x0={abs_x0}  y0={abs_y0}  x1={abs_x1}  y1={abs_y1}")
        print(f"  [Stage 1 debug] bar width      : {bar_px_width} px")
        print(f"  [Stage 1 debug] bar height     : {bar_h} px")
        print(f"  [Stage 1 debug] OCR µm value   : {um_value:.0f} µm  "
              f"({'override' if um_value_override is not None else 'OCR'})")
        print(f"  [Stage 1 debug] scale factor   : {um_value:.0f} / {bar_px_width} = "
              f"{scale_um_per_px:.4f} µm/px")

    # --- 5. Debug visualisation -------------------------------------------
    debug_vis = image.copy()

    # Red rectangle around the detected bar.
    cv2.rectangle(debug_vis, (abs_x0, abs_y0), (abs_x1, abs_y1),
                  (0, 0, 255), 2)

    # Horizontal double-headed arrow showing measured pixel span.
    arrow_y = abs_y1 + 8
    cv2.arrowedLine(debug_vis, (abs_x0, arrow_y), (abs_x1, arrow_y),
                    (0, 0, 255), 1, tipLength=0.1)
    cv2.arrowedLine(debug_vis, (abs_x1, arrow_y), (abs_x0, arrow_y),
                    (0, 0, 255), 1, tipLength=0.1)

    # Annotation text.
    label = f"{um_value:.0f}um / {bar_px_width}px = {scale_um_per_px:.4f}um/px"
    text_x = max(abs_x0 - 10, 5)
    text_y = max(abs_y0 - 8, 15)
    cv2.putText(debug_vis, label, (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

    # Also outline the full bottom-right search region in yellow.
    cv2.rectangle(debug_vis, (roi_x0, roi_y0), (img_w - 1, img_h - 1),
                  (0, 220, 220), 1)

    return scale_um_per_px, float(um_value), debug_vis
