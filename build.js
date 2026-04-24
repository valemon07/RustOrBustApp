/**
 * Build script for RustOrBust App
 *
 * Orchestrates:
 *   1. PyInstaller — bundles the Flask backend + Tesseract into a standalone exe
 *   2. Electron Forge — packages the Electron app with the backend as an extra resource
 *
 * Usage:
 *   node build.js           # full build (backend + electron)
 *   node build.js --backend # only build the backend exe
 *   node build.js --electron # only build the electron app (assumes backend already built)
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const ROOT = __dirname;
const BACKEND_DIR = path.join(ROOT, 'backend');
const DIST_DIR = path.join(BACKEND_DIR, 'dist', 'rustorbust-backend');

const args = process.argv.slice(2);
const onlyBackend = args.includes('--backend');
const onlyElectron = args.includes('--electron');

function run(cmd, cwd = ROOT) {
  console.log(`\n> ${cmd}\n`);
  execSync(cmd, { cwd, stdio: 'inherit' });
}

// ── Step 1: Build backend with PyInstaller ──────────────────────────────
if (!onlyElectron) {
  console.log('=== Building Flask backend with PyInstaller ===');

  // Ensure pyinstaller is installed
  try {
    execSync('pyinstaller --version', { stdio: 'pipe' });
  } catch {
    console.log('Installing PyInstaller...');
    run('pip install pyinstaller');
  }

  // Clean previous build
  const buildDir = path.join(BACKEND_DIR, 'build');
  if (fs.existsSync(buildDir)) {
    fs.rmSync(buildDir, { recursive: true, force: true });
  }
  if (fs.existsSync(DIST_DIR)) {
    fs.rmSync(DIST_DIR, { recursive: true, force: true });
  }

  // Run PyInstaller
  run('pyinstaller backend.spec --clean', BACKEND_DIR);

  // Verify output
  const exePath = path.join(DIST_DIR, 'rustorbust-backend.exe');
  if (!fs.existsSync(exePath)) {
    console.error('ERROR: Backend exe not found at', exePath);
    process.exit(1);
  }
  console.log('Backend built successfully:', exePath);
}

// ── Step 2: Build Electron app ──────────────────────────────────────────
if (!onlyBackend) {
  // Verify backend exists before packaging Electron
  if (!fs.existsSync(DIST_DIR)) {
    console.error(
      'ERROR: Backend not found at', DIST_DIR,
      '\nRun "node build.js --backend" first, or "node build.js" for a full build.'
    );
    process.exit(1);
  }

  console.log('\n=== Building Electron app with Forge ===');
  run('npx electron-forge make');
  console.log('\nDone! Check the out/ directory for the installer.');
}
