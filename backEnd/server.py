from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import csv
import io
import os
import sys

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


@app.route('/health', methods=['GET'])
def health():
    """Lightweight endpoint the Electron main process polls on startup."""
    return jsonify({"status": "ok"})


@app.route('/analyze', methods=['POST'])
def analyze():
    print("Request received", flush=True)

    if 'image' not in request.files:
        return jsonify({"error": "No image provided"}), 400

    image = request.files['image']

    if image.filename == '':
        return jsonify({"error": "No file selected"}), 400

    result = process_image(image)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["filename", "result"])
    writer.writerow([image.filename, result])
    output.seek(0)

    print("CSV has been returned", flush=True)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='results.csv'
    )


def process_image(image):
    return "image processed"


if __name__ == '__main__':
    # When frozen, run without debug mode and on all interfaces
    debug = not _is_bundled()
    app.run(debug=debug, port=5001, host='127.0.0.1')