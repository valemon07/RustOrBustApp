"""
Flask server — Rust or Bust backend API

Endpoints:
    GET  /health           — liveness check
    POST /analyze          — process images, return ZIP (CSV + annotated images)
    GET  /flagged-images   — list images flagged during last analysis run

The /analyze response is a ZIP file containing:
    results.csv                — full results in the new researcher-facing format
    <stem>_processed.jpg       — Stage 3 annotated image per input image
"""

import csv
import io
import os
import sys
import zipfile
from datetime import datetime

import cv2
from flask import Flask, jsonify, request
from flask_cors import CORS

# Make backend importable regardless of working directory
_BACKEND_DIR = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, _BACKEND_DIR)

from run_pipeline import process_image                           # noqa: E402
from pipeline.stage6_csv_export import CSV_COLUMNS              # noqa: E402

# ---------------------------------------------------------------------------
# Detect PyInstaller bundle and set up paths
# ---------------------------------------------------------------------------
def _is_bundled():
    """Return True when running inside a PyInstaller bundle."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

def _setup_tesseract():
    """Point pytesseract at the bundled tesseract binary if we are frozen."""
    try:
        import pytesseract
    except ImportError:
        return

    if _is_bundled():
        # PyInstaller extracts bundled files into sys._MEIPASS
        tess_path = os.path.join(sys._MEIPASS, 'tesseract', 'tesseract.exe')
        if os.path.isfile(tess_path):
            pytesseract.pytesseract.tesseract_cmd = tess_path
            # tessdata lives next to the binary
            os.environ['TESSDATA_PREFIX'] = os.path.join(
                sys._MEIPASS, 'tesseract', 'tessdata'
            )
    else:
        # Development: check common Windows install path
        prog_files = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        if os.path.isfile(prog_files):
            pytesseract.pytesseract.tesseract_cmd = prog_files

_setup_tesseract()

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
# In production the Electron renderer loads from file:// or a local vite
# server — allow all origins so the request always succeeds.
CORS(app)

# Populated during /analyze; read by /flagged-images
_flagged_images: list = []


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/analyze", methods=["POST"])
def analyze():
    global _flagged_images
    _flagged_images = []

    data = request.get_json(silent=True)
    if not data or "paths" not in data:
        return jsonify({"error": "Request body must be JSON with a 'paths' key"}), 400

    paths = data["paths"]
    if not paths:
        return jsonify({"error": "paths list is empty"}), 400

    # Global run settings from the frontend settings panel
    settings = data.get("settings", {}) or {}

    results   = []   # list of row_data dicts (CSV rows)
    vis_map   = {}   # stem → BGR numpy array (annotated debug image)
    errors    = []

    for image_path in paths:
        filename = os.path.basename(image_path)
        print(f"Processing {filename} ...", end=" ", flush=True)

        if not os.path.isfile(image_path):
            msg = "File not found"
            print(f"ERROR — {msg}", flush=True)
            errors.append({"filename": filename, "error": msg})
            continue

        try:
            row_data  = process_image(image_path, settings=settings)
            debug_vis = row_data.pop("_debug_vis", None)

            stem = os.path.splitext(filename)[0]
            if debug_vis is not None:
                vis_map[stem] = debug_vis

            results.append(row_data)

            flag_str = (
                f" [FLAGGED: {row_data['reason_for_flag']}]"
                if row_data["flagged_for_review"] == "Yes" else ""
            )
            print(f"done — {row_data['pit_count']} macro pits{flag_str}", flush=True)

            if row_data["flagged_for_review"] == "Yes":
                _flagged_images.append({
                    "filename": filename,
                    "filepath": image_path,
                    "reasons": [
                        {"rule": r.strip(), "detail": r.strip()}
                        for r in row_data["reason_for_flag"].split(";")
                        if r.strip()
                    ],
                })

        except Exception as exc:
            print(f"ERROR — {exc}", flush=True)
            errors.append({"filename": filename, "error": str(exc)})

    if errors:
        print(
            f"\n{len(errors)} image(s) failed: {[e['filename'] for e in errors]}",
            flush=True,
        )

    # ── Build in-memory ZIP ───────────────────────────────────────────────────
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

        # results.csv
        csv_buf = io.StringIO()
        writer  = csv.DictWriter(csv_buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})
        zf.writestr("results.csv", csv_buf.getvalue())

        # one annotated JPEG per image
        for stem, vis in vis_map.items():
            ok, buf = cv2.imencode(".jpg", vis)
            if ok:
                zf.writestr(f"{stem}_processed.jpg", buf.tobytes())

    zip_buffer.seek(0)
    zip_bytes = zip_buffer.getvalue()

    run_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_name = f"rust_or_bust_{run_ts}.zip"

    print(
        f"\nReturning ZIP '{zip_name}' — "
        f"{len(results)} image(s), {len(vis_map)} annotated, {len(errors)} error(s).",
        flush=True,
    )

    return zip_bytes, 200, {
        "Content-Type":        "application/zip",
        "Content-Disposition": f"attachment; filename={zip_name}",
        "Content-Length":      str(len(zip_bytes)),
    }


@app.route("/flagged-images", methods=["GET"])
def flagged_images():
    return jsonify({"flaggedImages": _flagged_images})


if __name__ == "__main__":
    # When frozen, run without debug mode; in development, enable debug
    debug = not _is_bundled()
    app.run(debug=debug, port=5001, host='127.0.0.1')
