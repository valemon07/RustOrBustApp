import { app, BrowserWindow, ipcMain, dialog } from 'electron';
import path from 'node:path';
import started from 'electron-squirrel-startup';
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import http from 'node:http';

// Handle creating/removing shortcuts on Windows when installing/uninstalling.
if (started) {
  app.quit();
}

// ---------------------------------------------------------------------------
// Backend process management
// ---------------------------------------------------------------------------
let backendProcess = null;
const BACKEND_PORT = 5001;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

function getBackendPath() {
  const isDev = !!MAIN_WINDOW_VITE_DEV_SERVER_URL;

  if (isDev) {
    // Development: use merged backend folder with venv
    const appRoot = app.getAppPath();
    const venvPython = path.join(appRoot, 'backEnd', '.venv', 'Scripts', 'python.exe');
    const pythonCmd = fs.existsSync(venvPython) ? venvPython : 'python';
    return {
      command: pythonCmd,
      args: [path.join(appRoot, 'backEnd', 'server.py')],
    };
  }

  // Production: use the PyInstaller-built exe bundled as extraResource
  const exeName = process.platform === 'win32'
    ? 'rustorbust-backend.exe'
    : 'rustorbust-backend';

  // extraResource files land in resources/ next to the app.asar, but some
  // packagers/setups may flatten or relocate this folder. Try common layouts.
  const candidatePaths = [
    path.join(process.resourcesPath, 'rustorbust-backend', exeName),
    path.join(process.resourcesPath, exeName),
    path.join(path.dirname(process.execPath), 'resources', 'rustorbust-backend', exeName),
  ];

  const foundExe = candidatePaths.find((p) => fs.existsSync(p));
  if (!foundExe) {
    console.error('[backend] Executable not found. Tried:', candidatePaths);
  }

  return { command: foundExe || candidatePaths[0], args: [] };
}

function startBackend() {
  const { command, args } = getBackendPath();
  console.log(`[backend] Starting: ${command} ${args.join(' ')}`);

  backendProcess = spawn(command, args, {
    stdio: ['ignore', 'pipe', 'pipe'],
    // Prevent the backend window from appearing on Windows
    windowsHide: true,
    cwd: path.isAbsolute(command) ? path.dirname(command) : undefined,
  });

  backendProcess.stdout.on('data', (data) => {
    console.log(`[backend] ${data.toString().trim()}`);
  });

  backendProcess.stderr.on('data', (data) => {
    console.error(`[backend] ${data.toString().trim()}`);
  });

  backendProcess.on('error', (err) => {
    console.error('[backend] Failed to start:', err.message);
  });

  backendProcess.on('exit', (code) => {
    console.log(`[backend] Exited with code ${code}`);
    backendProcess = null;
  });
}

function stopBackend() {
  if (!backendProcess) return;
  console.log('[backend] Stopping...');

  if (process.platform === 'win32') {
    // On Windows, spawn taskkill to ensure the process tree is killed
    spawn('taskkill', ['/pid', String(backendProcess.pid), '/f', '/t'], {
      windowsHide: true,
    });
  } else {
    backendProcess.kill('SIGTERM');
  }
  backendProcess = null;
}

/**
 * Poll the backend /health endpoint until it responds (or timeout).
 * Returns a promise that resolves when the backend is ready.
 */
function waitForBackend(timeoutMs = 30000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      const req = http.get(`${BACKEND_URL}/health`, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else {
          retry();
        }
      });
      req.on('error', retry);
      req.setTimeout(1000, () => { req.destroy(); retry(); });
    };

    const retry = () => {
      if (Date.now() - start > timeoutMs) {
        reject(new Error('Backend did not start within timeout'));
        return;
      }
      setTimeout(check, 500);
    };

    check();
  });
}

// ---------------------------------------------------------------------------
// Window creation
// ---------------------------------------------------------------------------
const createWindow = () => {
  const isDev = !!MAIN_WINDOW_VITE_DEV_SERVER_URL;
  
  const mainWindow = new BrowserWindow({
    width: 800,
    height: 600,
    minHeight: 600,
    minWidth: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Hide menu bar in production, show in development
  if (!isDev) {
    mainWindow.removeMenu();
  }

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`));
  }

  // Only open DevTools in development
  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.webContents.openDevTools();
  }
};

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(async () => {
  startBackend();

  try {
    await waitForBackend();
    console.log('[backend] Ready — opening window');
  } catch (err) {
    console.error('[backend]', err.message, '— opening window anyway');
  }

  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('will-quit', () => {
  stopBackend();
});

// ── IPC handlers ──────────────────────────────────────────────────────────────

ipcMain.handle('dialog:openFile', async () => {
  const result = await dialog.showOpenDialog({
    filters: [
      { name: 'Images', extensions: ['jpg', 'jpeg', 'png', 'tif', 'tiff'] },
      { name: 'All Files', extensions: ['*'] },
    ],
    properties: ['openFile', 'multiSelections'],
  });
  return result; // { canceled, filePaths }
});

ipcMain.handle('file:readImageAsDataUrl', async (event, filePath) => {
  try {
    // Ensure we have an absolute path
    const absolutePath = path.isAbsolute(filePath) ? filePath : path.resolve(filePath);
    
    const data = fs.readFileSync(absolutePath);
    const base64 = data.toString('base64');
    const ext = path.extname(absolutePath).toLowerCase();
    const mimeType = {
      '.jpg': 'image/jpeg',
      '.jpeg': 'image/jpeg',
      '.png': 'image/png',
      '.gif': 'image/gif',
      '.webp': 'image/webp',
    }[ext] || 'image/jpeg';
    return `data:${mimeType};base64,${base64}`;
  } catch (err) {
    console.error('Error reading image:', err);
    throw err;
  }
});
