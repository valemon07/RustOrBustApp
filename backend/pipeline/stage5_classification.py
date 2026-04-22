"""
Stage 5: Classification

Assigns a corrosion severity class to the specimen based on the density
metrics produced by Stage 4.  Uses a scikit-learn classifier trained on
labelled reference data stored in data/reference/.

Inputs:  metrics dict (from Stage 4)
Outputs: classification label (str), debug_vis (numpy.ndarray)
"""

import numpy as np


def classify_specimen(metrics):
    """
    Classify corrosion severity from pit density metrics.

    Parameters
    ----------
    metrics : dict
        Output of stage4_density.calculate_density — must contain at least
        pit_count, pit_density_per_cm2, mean_pit_width_um, max_pit_width_um.

    Returns
    -------
    classification : str
        Severity label, e.g. 'none', 'mild', 'moderate', 'severe'.
    debug_vis : numpy.ndarray
        BGR summary card image showing the assigned class and key metrics.
    """
    raise NotImplementedError("Stage 5 not yet implemented")
