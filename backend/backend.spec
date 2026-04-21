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
import shutil

# ---------------------------------------------------------------------------
# Tesseract bundling (Windows only - other platforms use system Tesseract)
# ---------------------------------------------------------------------------
tesseract_binaries = []
tesseract_datas = []

if sys.platform == 'win32':
    # Resolve Tesseract install directory from env, PATH, or common defaults.
    env_tess = os.environ.get('TESSERACT_DIR')
    path_tess = shutil.which('tesseract')
    candidate_dirs = [
        env_tess,
        os.path.dirname(path_tess) if path_tess else None,
        os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Tesseract-OCR'),
        os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), 'Tesseract-OCR'),
    ]
    
    print("[backend.spec] Searching for Tesseract...")
    print(f"[backend.spec] TESSERACT_DIR env var: {env_tess}")
    print(f"[backend.spec] shutil.which('tesseract'): {path_tess}")
    
    valid_dirs = []
    for d in candidate_dirs:
        if not d:
            continue
        exe = os.path.join(d, 'tesseract.exe')
        tessdata = os.path.join(d, 'tessdata')
        eng = os.path.join(tessdata, 'eng.traineddata')
        osd = os.path.join(tessdata, 'osd.traineddata')
        exe_exists = os.path.isfile(exe)
        tessdata_exists = os.path.isdir(tessdata)
        eng_exists = os.path.isfile(eng)
        osd_exists = os.path.isfile(osd)
        print(f"[backend.spec] Candidate: {d}")
        print(f"  exe: {exe_exists}, tessdata: {tessdata_exists}, eng.traineddata: {eng_exists}, osd.traineddata: {osd_exists}")
        if exe_exists:
            score = (tessdata_exists, eng_exists, osd_exists)
            valid_dirs.append((score, d))
            print(f"  => Added with score {score}")

    valid_dirs.sort(key=lambda item: item[0], reverse=True)
    if not valid_dirs:
        print("[backend.spec] ERROR: No valid Tesseract installation found!")
        print(f"[backend.spec] Candidates checked: {[d for d in candidate_dirs if d]}")
        sys.exit(1)
    
    TESSERACT_DIR = valid_dirs[0][1]
    # Normalize to backslashes for proper Windows path handling
    TESSERACT_DIR = os.path.normpath(TESSERACT_DIR)
    print(f"[backend.spec] Selected: {TESSERACT_DIR} (score={valid_dirs[0][0]})")
    print(f"[backend.spec] Normalized path: {TESSERACT_DIR}")
    
    # Collect tesseract.exe + all DLLs it needs
    if TESSERACT_DIR and os.path.isdir(TESSERACT_DIR):
        exe_src = os.path.join(TESSERACT_DIR, 'tesseract.exe')
        tesseract_binaries.append((exe_src, 'tesseract'))
        print(f"[backend.spec] Added binary: {exe_src} -> tesseract")
        
        dll_count = 0
        for dll in glob.glob(os.path.join(TESSERACT_DIR, '*.dll')):
            tesseract_binaries.append((dll, 'tesseract'))
            dll_count += 1
        print(f"[backend.spec] Added {dll_count} DLLs")
        
        # Collect tessdata (language files) — use tree collection instead of individual files
        # This ensures the entire tessdata directory with subdirs is copied correctly
        tessdata_dir = os.path.join(TESSERACT_DIR, 'tessdata')
        if os.path.isdir(tessdata_dir):
            # Collect the entire tessdata tree as a single entry
            # (source_dir, dest_name) — PyInstaller will recursively copy source_dir to dest_name
            tesseract_datas.append((tessdata_dir, 'tesseract/tessdata'))
            print(f"[backend.spec] Added tessdata tree: {tessdata_dir} -> tesseract/tessdata")
        else:
            print(f"[backend.spec] ERROR: tessdata directory not found at {tessdata_dir}")
            sys.exit(1)
        
        # Also include tessdata configs directory if it exists
        tessdata_configs = os.path.join(tessdata_dir, 'configs')
        if os.path.isdir(tessdata_configs):
            tesseract_datas.append((tessdata_configs, 'tesseract/tessdata/configs'))
            print(f"[backend.spec] Added tessdata configs tree: {tessdata_configs} -> tesseract/tessdata/configs")
    else:
        print("[backend.spec] ERROR: No valid Tesseract install directory")
        sys.exit(1)
elif sys.platform == 'darwin':
    print("NOTE: macOS build expects Tesseract installed via: brew install tesseract")
elif sys.platform == 'linux':
    print("NOTE: Linux build expects Tesseract installed via: apt-get install tesseract-ocr")

print(f"[backend.spec] Summary: {len(tesseract_binaries)} binaries, {len(tesseract_datas)} datas to bundle")
if tesseract_binaries:
    for src, dest in tesseract_binaries[:3]:
        print(f"[backend.spec]   bin: {src} -> {dest}")
if len(tesseract_binaries) > 3:
    print(f"[backend.spec]   ... and {len(tesseract_binaries) - 3} more")
if tesseract_datas:
    for src, dest in tesseract_datas[:3]:
        print(f"[backend.spec]   data: {src} -> {dest}")
if len(tesseract_datas) > 3:
    print(f"[backend.spec]   ... and {len(tesseract_datas) - 3} more")

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
