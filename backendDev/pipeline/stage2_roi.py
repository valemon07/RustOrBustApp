"""
Stage 2: ROI Extraction

Isolates the specimen boundary using a convex-hull approach so that dark pit
regions INSIDE the specimen are retained in the mask rather than treated as
background.

Strategy
--------
1. Gaussian blur + Otsu threshold → coarse bright/dark classification.
2. Morphological closing to bridge tiny surface gaps and produce a clean
   bright blob representing the specimen.
3. Exclude the scale bar corner from the closed mask before contour detection
   so the scale bar never contaminates the specimen shape.
4. Find the largest remaining bright connected component; compute its convex
   hull and fill it completely.  The filled hull is the specimen mask — dark
   pits inside the boundary are now INCLUDED.
5. Classify every dark connected component inside the hull:
     edge_pit    — touches the hull boundary (hole edge, mounting resin, etc.)
     surface_pit — fully interior to the hull (candidate corrosion pits)
6. Return the hull mask, a bounding-box crop, dimension + classification
   metadata, and a colour-coded debug image.

Returns
-------
specimen_mask : ndarray uint8   255 = inside hull (includes dark pits), 0 = outside
specimen_crop : ndarray BGR     rectangular bounding-box crop, non-hull pixels blacked out
roi_dims      : dict
    width_px, height_px, width_um, height_um
    edge_pits     — list of {mask, area_px, bbox}  (hole-edge dark regions)
    surface_pits  — list of {mask, area_px, bbox}  (interior dark regions)
debug_vis     : ndarray BGR     colour-coded diagnostic image
"""

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Tuneable constants
# ---------------------------------------------------------------------------

# Gaussian blur kernel applied before Otsu thresholding.
BLUR_KERNEL_SIZE = 15

# Morphological closing kernel to fill small surface gaps in the bright mask.
CLOSE_KERNEL_SIZE = 15

# Scale bar exclusion zone: bottom-right corner of the image.
# Excluded region = rightmost 32 % × bottommost 20 %.
SCALEBAR_X_FRACTION = 0.68   # exclusion starts at 68 % across
SCALEBAR_Y_FRACTION = 0.80   # exclusion starts at 80 % down

# Dark regions smaller than this (px²) are treated as noise and skipped.
MIN_DARK_REGION_AREA_PX = 10

# The hull boundary is dilated by this many pixels before checking whether a
# dark region "touches" it.  Catches pits that are adjacent to the boundary
# without being literally on the 1-px-thick edge line.
HULL_BOUNDARY_DILATION_PX = 5


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


def _largest_bright_contour(binary_mask):
    """
    Return the external contour of the largest bright connected component
    in binary_mask.

    Raises RuntimeError if no components are found.
    """
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary_mask, connectivity=8
    )
    if num_labels < 2:
        raise RuntimeError(
            "No bright regions found after thresholding and scale-bar exclusion."
        )

    # Label 0 is background; skip it.
    largest_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    largest_component = (labels == largest_label).astype(np.uint8) * 255

    contours, _ = cv2.findContours(
        largest_component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        raise RuntimeError("findContours returned nothing for the largest bright region.")

    return max(contours, key=cv2.contourArea)


def _fill_convex_hull(contour, img_h, img_w):
    """
    Compute the convex hull of contour and fill it into a binary mask.

    Returns
    -------
    hull_mask   : ndarray uint8  (255 inside hull, 0 outside)
    hull_points : ndarray        convex hull point array (for drawing)
    """
    hull_points = cv2.convexHull(contour)
    hull_mask = np.zeros((img_h, img_w), dtype=np.uint8)
    cv2.drawContours(hull_mask, [hull_points], -1, 255, thickness=cv2.FILLED)
    return hull_mask, hull_points


def _classify_dark_regions(hull_mask, otsu_mask):
    """
    Find every dark connected component inside hull_mask and classify it.

    Classification rule
    -------------------
    A dark region is an **edge_pit** if any of its pixels falls within
    HULL_BOUNDARY_DILATION_PX of the hull's boundary edge.
    Otherwise it is a **surface_pit** (fully interior to the hull).

    Parameters
    ----------
    hull_mask  : uint8 binary mask, 255 = inside hull
    otsu_mask  : uint8 binary mask, 255 = bright (Otsu output)

    Returns
    -------
    edge_pits, surface_pits : lists of dicts
        Each dict: {mask (uint8 full-image), area_px (int), bbox (x,y,w,h)}
    """
    # Dark pixels that are inside the hull.
    inside_hull_dark = cv2.bitwise_and(
        cv2.bitwise_not(otsu_mask),
        hull_mask
    )

    # Hull boundary: the outermost ring of hull pixels.
    eroded_hull = cv2.erode(
        hull_mask,
        np.ones((3, 3), np.uint8),
        iterations=1
    )
    hull_boundary = hull_mask - eroded_hull

    # Dilate the boundary to create a proximity zone.
    dil_size = HULL_BOUNDARY_DILATION_PX * 2 + 1
    boundary_zone = cv2.dilate(
        hull_boundary,
        np.ones((dil_size, dil_size), np.uint8),
        iterations=1
    )

    # Label all dark regions inside the hull.
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        inside_hull_dark, connectivity=8
    )

    edge_pits    = []
    surface_pits = []

    for label_id in range(1, num_labels):
        area = int(stats[label_id, cv2.CC_STAT_AREA])
        if area < MIN_DARK_REGION_AREA_PX:
            continue

        region_mask = (labels == label_id).astype(np.uint8) * 255

        entry = {
            "mask":    region_mask,
            "area_px": area,
            "bbox":    (
                int(stats[label_id, cv2.CC_STAT_LEFT]),
                int(stats[label_id, cv2.CC_STAT_TOP]),
                int(stats[label_id, cv2.CC_STAT_WIDTH]),
                int(stats[label_id, cv2.CC_STAT_HEIGHT]),
            ),
        }

        # Does any pixel of this region fall inside the boundary zone?
        if np.any(cv2.bitwise_and(region_mask, boundary_zone)):
            edge_pits.append(entry)
        else:
            surface_pits.append(entry)

    return edge_pits, surface_pits


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_roi(image_input, scale_um_per_px=1.0):
    """
    Extract the specimen ROI from a darkfield microscopy image.

    Parameters
    ----------
    image_input : str or numpy.ndarray
        Path to the image file or a BGR numpy array.
    scale_um_per_px : float
        Micrometers per pixel from Stage 1.  Defaults to 1.0.

    Returns
    -------
    specimen_mask : ndarray uint8
        Binary mask of the filled convex hull — 255 inside (including pits),
        0 outside.  Same spatial dimensions as the input image.
    specimen_crop : ndarray BGR
        Bounding-box crop of the original image; non-hull pixels are black.
    roi_dims : dict
        ``width_px``, ``height_px`` — bounding-box size in pixels
        ``width_um``, ``height_um`` — same values in micrometres
        ``edge_pits``    — list of dark-region dicts touching the hull boundary
        ``surface_pits`` — list of dark-region dicts fully interior to the hull
    debug_vis : ndarray BGR
        Colour-coded diagnostic image:
          Green outline  — convex hull boundary
          Red fill       — edge_pit candidates
          Yellow fill    — surface_pit candidates
          Blue rectangle — excluded scale-bar zone
          White text     — ROI dimensions and pit counts
    """
    image = _load_image(image_input)
    img_h, img_w = image.shape[:2]

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # --- 1. Gaussian blur + Otsu threshold ----------------------------------
    blurred = cv2.GaussianBlur(
        gray, (BLUR_KERNEL_SIZE, BLUR_KERNEL_SIZE), 0
    )
    _, otsu_mask = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    # --- 2. Morphological closing to fill tiny surface gaps -----------------
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (CLOSE_KERNEL_SIZE, CLOSE_KERNEL_SIZE)
    )
    closed_mask = cv2.morphologyEx(otsu_mask, cv2.MORPH_CLOSE, close_kernel)

    # --- 3. Exclude scale bar zone before contour detection -----------------
    # This prevents the bright scale bar pixels from merging with or distorting
    # the detected specimen shape.
    sb_y0 = int(img_h * SCALEBAR_Y_FRACTION)
    sb_x0 = int(img_w * SCALEBAR_X_FRACTION)
    closed_mask_no_sb = closed_mask.copy()
    closed_mask_no_sb[sb_y0:, sb_x0:] = 0

    # --- 4. Convex hull of the largest bright component --------------------
    main_contour = _largest_bright_contour(closed_mask_no_sb)
    hull_mask, hull_points = _fill_convex_hull(main_contour, img_h, img_w)

    # Also zero out the scale bar zone in the hull mask itself.
    hull_mask[sb_y0:, sb_x0:] = 0

    # --- 5. Classify dark regions inside the hull --------------------------
    # Use the original Otsu mask (not the closed one) so individual pits are
    # not merged together before classification.
    # Also mask out the scale bar zone from the Otsu mask first.
    otsu_no_sb = otsu_mask.copy()
    otsu_no_sb[sb_y0:, sb_x0:] = 255   # treat scale bar region as "bright"

    edge_pits, surface_pits = _classify_dark_regions(hull_mask, otsu_no_sb)

    # --- 6. Bounding box and crop ------------------------------------------
    nonzero_ys, nonzero_xs = np.where(hull_mask > 0)
    if len(nonzero_xs) == 0:
        raise RuntimeError(
            "Hull mask is empty after scale-bar exclusion. "
            "The specimen may lie entirely within the excluded corner."
        )

    x_min = int(nonzero_xs.min())
    x_max = int(nonzero_xs.max())
    y_min = int(nonzero_ys.min())
    y_max = int(nonzero_ys.max())

    width_px  = x_max - x_min + 1
    height_px = y_max - y_min + 1

    roi_dims = {
        "width_px":    width_px,
        "height_px":   height_px,
        "width_um":    round(width_px  * scale_um_per_px, 2),
        "height_um":   round(height_px * scale_um_per_px, 2),
        "edge_pits":   edge_pits,
        "surface_pits": surface_pits,
    }

    # Bounding-box crop with non-hull pixels blacked out.
    masked_image = image.copy()
    masked_image[hull_mask == 0] = 0
    specimen_crop = masked_image[y_min : y_max + 1, x_min : x_max + 1]

    # --- 7. Debug visualisation --------------------------------------------
    # Start from a copy of the original image, blend coloured region overlays,
    # then draw crisp outlines and text on top.

    # Build union masks for the two pit classes.
    edge_union    = np.zeros((img_h, img_w), dtype=np.uint8)
    surface_union = np.zeros((img_h, img_w), dtype=np.uint8)
    for pit in edge_pits:
        edge_union = cv2.bitwise_or(edge_union, pit["mask"])
    for pit in surface_pits:
        surface_union = cv2.bitwise_or(surface_union, pit["mask"])

    # Semi-transparent colour overlay.
    overlay = image.copy()
    overlay[edge_union > 0]    = (0,   0, 200)   # red   — edge_pit
    overlay[surface_union > 0] = (0, 220, 220)   # yellow — surface_pit
    debug_vis = cv2.addWeighted(image, 0.65, overlay, 0.35, 0)

    # Green convex hull outline.
    cv2.drawContours(debug_vis, [hull_points], -1, (0, 200, 0), 2)

    # Blue rectangle: excluded scale-bar zone.
    cv2.rectangle(
        debug_vis,
        (sb_x0, sb_y0), (img_w - 1, img_h - 1),
        (255, 0, 0), 2
    )

    # White text with shadow.
    text_lines = [
        f"ROI: {width_px} x {height_px} px"
        f"  ({roi_dims['width_um']:.0f} x {roi_dims['height_um']:.0f} um)",
        f"edge_pits: {len(edge_pits)}   surface_pits: {len(surface_pits)}",
    ]
    text_x = 10
    text_y = 35
    for line in text_lines:
        cv2.putText(debug_vis, line, (text_x + 1, text_y + 1),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(debug_vis, line, (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        text_y += 30

    return hull_mask, specimen_crop, roi_dims, debug_vis
