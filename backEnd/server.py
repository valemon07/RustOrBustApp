# backend/server.py
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import csv
import io

app = Flask(__name__)
CORS(app)  # allows requests from Electron/Vite

# -----------------------------------------------
# Route: POST /analyze
# Receives: an image file
# Returns: a CSV file with results
# -----------------------------------------------
@app.route('/analyze', methods=['POST'])
def analyze():
    # 1. Validate that an image was sent
    if 'image' not in request.files:
        return jsonify({"error": "No image provided"}), 400
    
    image = request.files['image']

    if image.filename == '':
        return jsonify({"error": "No file selected"}), 400

    # 2. Process the image (swap this out later for real analysis)
    result = process_image(image)

    # 3. Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["filename", "result"])        # header row
    writer.writerow([image.filename, result])      # data row
    output.seek(0)

    # 4. Return CSV as a downloadable file
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='results.csv'
    )

# -----------------------------------------------
# Placeholder processing function
# Replace the insides of this with your real work
# -----------------------------------------------
def process_image(image):
    return "image processed"

# -----------------------------------------------
# Health check route — useful for confirming
# the server is running from Electron's main.js
# -----------------------------------------------
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "server is running"}), 200


if __name__ == '__main__':
    app.run(debug=True, port=5000)