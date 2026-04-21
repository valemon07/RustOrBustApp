# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the RustOrBust Flask backend.

Bundles:
  - server.py + all Python dependencies
  - Tesseract OCR binary + required DLLs + tessdata (Windows)
  - On macOS/Linux: expects Tesseract to be installed via brew/apt

Usage:
  pyinstaller backend.spec
"""

import os
import glob
import platform
import sys

# ---------------------------------------------------------------------------
# Tesseract bundling (Windows only - other platforms use system Tesseract)
# ---------------------------------------------------------------------------
tesseract_binaries = []
tesseract_datas = []

if sys.platform == 'win32':
    TESSERACT_DIR = r'C:\Program Files\Tesseract-OCR'
    
    # Collect tesseract.exe + all DLLs it needs
    if os.path.isdir(TESSERACT_DIR):
        tesseract_binaries.append(
            (os.path.join(TESSERACT_DIR, 'tesseract.exe'), 'tesseract')
        )
        for dll in glob.glob(os.path.join(TESSERACT_DIR, '*.dll')):
            tesseract_binaries.append((dll, 'tesseract'))
        
        # Collect tessdata (language files)
        tessdata_dir = os.path.join(TESSERACT_DIR, 'tessdata')
        for f in ['eng.traineddata', 'osd.traineddata']:
            src = os.path.join(tessdata_dir, f)
            if os.path.isfile(src):
                tesseract_datas.append((src, 'tesseract/tessdata'))
        
        # Also include tessdata configs directory if it exists
        tessdata_configs = os.path.join(tessdata_dir, 'configs')
        if os.path.isdir(tessdata_configs):
            for f in os.listdir(tessdata_configs):
                src = os.path.join(tessdata_configs, f)
                if os.path.isfile(src):
                    tesseract_datas.append((src, 'tesseract/tessdata/configs'))
    else:
        print(f"WARNING: Tesseract not found at {TESSERACT_DIR}")
        print("Install from: https://github.com/UB-Mannheim/tesseract/wiki")
elif sys.platform == 'darwin':
    print("NOTE: macOS build expects Tesseract installed via: brew install tesseract")
elif sys.platform == 'linux':
    print("NOTE: Linux build expects Tesseract installed via: apt-get install tesseract-ocr")

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=tesseract_binaries,
    datas=tesseract_datas,
    hiddenimports=[
        'flask',
        'flask_cors',
        'cv2',
        'numpy',
        'pandas',
        'sklearn',
        'pytesseract',
        'engineio.async_drivers.threading',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'PyQt5', 'PyQt6',
        'PySide2', 'PySide6', 'IPython', 'notebook',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='rustorbust-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # Keep console for debugging; set False for release
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='rustorbust-backend',
)
