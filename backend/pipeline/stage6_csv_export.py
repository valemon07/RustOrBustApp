"""
Stage 6: CSV Export

Appends one row per processed image to the output CSV file.

Output columns:
    file_name             - image filename
    specimen_id           - specimen ID parsed from filename
    scale_bar_um          - scale bar value in µm (for manual verification)
    pit_count             - macro pit count (area ≥ 1500 µm²)
    pit_density_per_cm    - macro pits per linear cm of ROI width
    mean_pit_depth        - mean width of confirmed macro pits (µm)
    max_pit_depth         - max width of confirmed macro pits (µm)
    all_pit_depths        - semicolon-separated depths of all macro pits (µm)
    flagged_for_review    - "Yes" or "No"
    reason_for_flag       - semicolon-separated flag names (blank if not flagged)
    exposure_contrast_used - gamma value used for mask generation
    R1_rejections         - count of candidates rejected by rule R1
    R2_rejections         - count of candidates rejected by rule R2
    R3_rejections         - count of candidates rejected by rule R3
    R4_rejections         - count of candidates rejected by rule R4
    R5_rejections         - count of candidates rejected by rule R5
    R6_rejections         - count of candidates rejected by rule R6
    R7_rejections         - count of candidates rejected by rule R7
    R8_rejections         - count of candidates rejected by rule R8

Inputs:  row data dict, output csv path (str)
Outputs: None (side-effect: writes/appends to CSV)
"""

import csv
import os


CSV_COLUMNS = [
    "file_name",
    "specimen_id",
    "scale_bar_um",
    "pit_count",
    "pit_density_per_cm",
    "mean_pit_depth",
    "max_pit_depth",
    "all_pit_depths",
    "flagged_for_review",
    "reason_for_flag",
    "exposure_contrast_used",
    "R1_rejections",
    "R2_rejections",
    "R3_rejections",
    "R4_rejections",
    "R5_rejections",
    "R6_rejections",
    "R7_rejections",
    "R8_rejections",
]


def export_row(row_data, csv_path):
    """
    Write or append a single result row to the CSV.

    Parameters
    ----------
    row_data : dict
        Must contain all keys listed in CSV_COLUMNS.
    csv_path : str
        Destination CSV file path (created if it doesn't exist).

    Returns
    -------
    None
    """
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    write_header = not os.path.isfile(csv_path) or os.path.getsize(csv_path) == 0

    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({col: row_data.get(col, "") for col in CSV_COLUMNS})
