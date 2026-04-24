"""
Stage 7: Pit-depth scatter plot.

Builds a categorical scatter plot of pit depth per specimen — one column per
specimen, with a red dot for the mean pit depth and a blue dot for the max
pit depth. Returned as PNG bytes so the caller can drop it straight into the
output ZIP (server.py) or write it to disk (run_pipeline.py).
"""

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def build_pit_depth_scatter(results):
    """
    Args:
        results: list of row_data dicts (each with 'specimen_id',
                 'mean_pit_depth', 'max_pit_depth').

    Returns:
        PNG bytes, or None if results is empty / plotting fails.
    """
    if not results:
        return None

    try:
        specimen_labels = [str(r.get("file_name", "") or r.get("specimen_id", "")) for r in results]
        mean_depths     = [float(r.get("mean_pit_depth", 0) or 0) for r in results]
        max_depths      = [float(r.get("max_pit_depth",  0) or 0) for r in results]
        positions       = list(range(len(results)))

        fig_width = max(8.0, 0.5 * len(results) + 4.0)
        fig, ax = plt.subplots(figsize=(fig_width, 6.0), dpi=150)

        ax.scatter(positions, mean_depths, color="red",  s=60, alpha=0.85,
                   label="Mean pit depth", zorder=3)
        ax.scatter(positions, max_depths,  color="blue", s=60, alpha=0.85,
                   label="Max pit depth",  zorder=3)

        ax.set_xticks(positions)
        ax.set_xticklabels(specimen_labels, rotation=45, ha="right")

        ax.set_xlabel("Specimen")
        ax.set_ylabel("Pit depth (µm)")
        ax.set_title("Pit Depth by Specimen")
        ax.grid(True, axis="y", linestyle="--", alpha=0.4)
        ax.legend(loc="upper right")

        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        return buf.getvalue()
    except Exception as exc:
        print(f"[stage7_scatter_plot] failed to render plot: {exc}", flush=True)
        return None
