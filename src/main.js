import { app, BrowserWindow, ipcMain, dialog } from 'electron';
import path from 'node:path';
import started from 'electron-squirrel-startup';
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import net from 'node:net';

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
    const venvPython = path.join(appRoot, 'backend', '.venv', 'Scripts', 'python.exe');
    const pythonCmd = fs.existsSync(venvPython) ? venvPython : 'python';
    return {
      command: pythonCmd,
      args: [path.join(appRoot, 'backend', 'server.py')],
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

  flaskProcess.stdout.on('data', (d) => console.log(`[Flask] ${d.toString().trimEnd()}`));
  flaskProcess.stderr.on('data', (d) => console.error(`[Flask] ${d.toString().trimEnd()}`));
  flaskProcess.on('error', (err) => console.error('[Flask] Failed to start:', err.message));
  flaskProcess.on('exit', (code) => console.log(`[Flask] Exited with code ${code}`));
}

/**
 * Poll port 5001 until it accepts a connection (Flask is ready) or we give up.
 * Resolves when ready; resolves (with a warning) if max attempts exceeded so
 * the window still opens even if Flask is slow to start.
 */
function waitForFlask(maxAttempts = 40, delayMs = 250) {
  return new Promise((resolve) => {
    let attempts = 0;

    const check = () => {
      const socket = new net.Socket();
      socket.setTimeout(150);

      socket.on('connect', () => {
        socket.destroy();
        console.log('[Flask] Server is ready.');
        resolve();
      });

      const retry = () => {
        socket.destroy();
        if (++attempts >= maxAttempts) {
          console.warn('[Flask] Did not respond in time — opening window anyway.');
          resolve();
        } else {
          setTimeout(check, delayMs);
        }
      };

      socket.on('error', retry);
      socket.on('timeout', retry);
      socket.connect(5001, '127.0.0.1');
    };

    check();
  });
}

function stopFlaskServer() {
  if (flaskProcess) {
    flaskProcess.kill();
    flaskProcess = null;
  }
}

// ── Window ────────────────────────────────────────────────────────────────────

const createWindow = () => {
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

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`));
  }

  mainWindow.webContents.openDevTools();
};

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  startFlaskServer();
  await waitForFlask();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  stopFlaskServer();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('will-quit', () => {
  stopFlaskServer();
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
