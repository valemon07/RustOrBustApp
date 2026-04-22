# Installation Guide

This document covers two paths: **running a pre-built release** (recommended for most
researchers) and **running from source** (for developers or when no release is available).

---

## Option A — Pre-Built Application (Recommended)

A packaged version of the app can be distributed as a `.zip` or `.dmg` (macOS) /
`.exe` installer (Windows). If you have received one of these files:

1. **macOS:** Open the `.dmg` and drag the app into your Applications folder.
   On first launch, right-click the app → **Open** to bypass Gatekeeper.
2. **Windows:** Run the installer `.exe` and follow the prompts.

Even with the pre-built app, you still need to install the Python backend separately
(see [Python Setup](#python-setup) below), because the image analysis pipeline runs
in Python and is not bundled with the Electron app.

---

## Option B — Running from Source

Use this if no pre-built release is available.

### 1. Prerequisites

Install the following before proceeding:

| Dependency | Version | Download |
|---|---|---|
| Node.js + npm | 18 or later | https://nodejs.org |
| Python | 3.11 or later | https://www.python.org/downloads |
| Tesseract OCR | Any recent | See below |

#### Installing Tesseract OCR

Tesseract is required to read the scale bar label from images.

- **macOS (Homebrew):**
  ```
  brew install tesseract
  ```
- **Windows:** Download the installer from the
  [UB Mannheim Tesseract releases page](https://github.com/UB-Mannheim/tesseract/wiki)
  and add the install directory to your `PATH`.
- **Linux (Debian/Ubuntu):**
  ```
  sudo apt install tesseract-ocr
  ```

### 2. Clone or Download the Repository

```
git clone https://github.com/valemon07/RustOrBustApp.git
cd RustOrBustApp
```

Or download and extract the ZIP from GitHub.

### 3. Install Node.js Dependencies

```
npm install
```

### 4. Python Setup

Create a virtual environment and install the Python packages:

```
cd backendDev
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# or: venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

### 5. Start the App

From the project root:

```
npm start
```

---

## Python Setup

> This section applies to both Option A and Option B.

The image analysis pipeline runs in Python. The app launches a Python subprocess
when processing images, so Python must be installed on the same machine.

### Required Python Packages

| Package | Purpose |
|---|---|
| `opencv-python` | Image processing (masking, contour detection, morphology) |
| `numpy` | Numerical array operations |
| `pandas` | Data handling |
| `scikit-learn` | Classification |
| `pytesseract` | OCR reading of scale bar labels |

Install all at once:

```
pip install opencv-python numpy pandas scikit-learn pytesseract
```

### Required System Dependency

`pytesseract` is a Python wrapper around the Tesseract binary. The binary must also
be installed (see [Installing Tesseract OCR](#installing-tesseract-ocr) above).

---

## Verifying Your Installation

After setup, you can verify the Python environment is working by running the
pipeline directly on a test image:

```
cd backendDev
python run_pipeline.py --help
```

If Tesseract is missing, you will see an error like:
```
TesseractNotFoundError: tesseract is not installed or it's not in your PATH
```
Follow the Tesseract installation steps above and ensure it is on your system `PATH`.

---

## Summary of What Researchers Need

| What | Required By |
|---|---|
| The Rust or Bust app (pre-built or from source) | All users |
| Python 3.11+ | All users |
| Tesseract OCR | All users |
| `opencv-python`, `numpy`, `pandas`, `scikit-learn`, `pytesseract` | All users |
| Node.js + npm | Source-build users only |
| Git | Source-build users only |
