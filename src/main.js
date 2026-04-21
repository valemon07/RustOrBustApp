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

// ── Flask server lifecycle ────────────────────────────────────────────────────

let flaskProcess = null;

function startFlaskServer() {
  const appRoot = app.getAppPath();
  const serverScript = path.join(appRoot, 'backEnd', 'server.py');

  // Use the project venv that has cv2, numpy, flask, etc.
  // Falls back to system python3 if neither venv path exists.
  const venvCandidates = [
    // rust_or_bust/venv has all required packages (cv2, flask, numpy, etc.)
    path.join(require('os').homedir(), 'rust_or_bust', 'venv', 'bin', 'python'),
    path.join(appRoot, 'backendDev', 'venv', 'bin', 'python'),
  ];
  const systemPython = process.platform === 'win32' ? 'python' : 'python3';
  const pythonCmd = venvCandidates.find((p) => fs.existsSync(p)) ?? systemPython;

  console.log(`[Flask] Starting: ${pythonCmd} ${serverScript}`);

  flaskProcess = spawn(pythonCmd, [serverScript], {
    cwd: appRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
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
    const data = fs.readFileSync(filePath);
    const base64 = data.toString('base64');
    const ext = path.extname(filePath).toLowerCase();
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
