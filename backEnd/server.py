from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import csv
import io
import sys

app = Flask(__name__)
CORS(app, origins="http://localhost:5173")

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
    app.run(debug=True, port=5001)