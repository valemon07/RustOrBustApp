"""
Stage 6: CSV Export

Appends one row per processed image to the output CSV file.

Output columns (as specified in CLAUDE.md):
    filename, sample_id, scale_um_per_px, pit_count,
    pit_density_per_cm2, classification,
    mean_pit_width_um, max_pit_width_um

Inputs:  row data dict, output csv path (str)
Outputs: None (side-effect: writes/appends to CSV)
"""

import csv
import os


CSV_COLUMNS = [
    "filename",
    "sample_id",
    "scale_um_per_px",
    "pit_count",
    "pit_density_per_cm2",
    "classification",
    "mean_pit_width_um",
    "max_pit_width_um",
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
    raise NotImplementedError("Stage 6 not yet implemented")
