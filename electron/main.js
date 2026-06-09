/**
 * ResearchAssistant Electron 主进程
 *
 * 开发模式：spawn python -m uvicorn → 加载 http://localhost:5173
 * 生产模式：spawn 嵌入的 backend.exe → 加载 frontend/dist/index.html
 *
 * 关闭时终止后端进程，避免孤儿 Python 进程。
 */
const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const net = require('net');
const fs = require('fs');
const { autoUpdater } = require('electron-updater');

const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_PORT = 8000;
const MAX_PORT = 8010;
const HEALTH_POLL_INTERVAL_MS = 500;
const HEALTH_POLL_MAX_ATTEMPTS = 30;
const BACKEND_KILL_TIMEOUT_MS = 3000;

const isDev = !app.isPackaged;
const FRONTEND_DEV_URL = 'http://localhost:5173';
const PYTHON = process.platform === 'win32' ? 'python' : 'python3';

/** @type {import('child_process').ChildProcess | null} */
let backendProcess = null;
/** @type {number} */
let backendPort = DEFAULT_PORT;
/** @type {BrowserWindow | null} */
let mainWindow = null;
/** @type {string[]} */
const tempFiles = [];

// ---------------------------------------------------------------------------
// 自动更新（electron-updater）
// 配置从 package.json build.publish 读取，无需手动 setFeedURL
// ---------------------------------------------------------------------------

/** 当前更新状态，通过 IPC 同步到前端 */
let updateStatus = {
  state: 'idle',          // idle | checking | available | downloading | downloaded | error | no-update
  version: null,          // 新版本号（available/downloaded 时有值）
  error: null,            // 错误信息（error 状态时有值）
};

/**
 * 向前端推送更新状态
 */
function sendUpdateStatus() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('update-status', updateStatus);
  }
}

/**
 * 静默日志（仅写入 stderr，不弹窗打扰用户）
 * @param {string} message
 */
function logUpdate(message) {
  console.error(`[autoUpdater] ${message}`);
}

// 配置更新源（开发模式跳过检测，避免误触）
if (!isDev) {
  // 检查更新出错：静默（不打扰用户）
  autoUpdater.on('error', (err) => {
    logUpdate(`更新出错: ${err.message}`);
    updateStatus = { state: 'error', version: null, error: err.message };
    sendUpdateStatus();
  });

  // 开始检查更新
  autoUpdater.on('checking-for-update', () => {
    logUpdate('正在检查更新...');
    updateStatus = { state: 'checking', version: null, error: null };
    sendUpdateStatus();
  });

  // 没有可用更新（静默）
  autoUpdater.on('update-not-available', (_info) => {
    logUpdate('已是最新版本');
    updateStatus = { state: 'no-update', version: null, error: null };
    sendUpdateStatus();
  });

  // 有可用更新（后台自动下载）
  autoUpdater.on('update-available', (info) => {
    logUpdate(`发现新版本 v${info.version}，后台下载中...`);
    updateStatus = { state: 'downloading', version: info.version, error: null };
    sendUpdateStatus();
  });

  // 下载进度（向前端报告）
  autoUpdater.on('download-progress', (progress) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('update-download-progress', {
        percent: Math.round(progress.percent),
      });
    }
  });

  // 下载完成 → 提示用户重启
  autoUpdater.on('update-downloaded', (info) => {
    logUpdate(`v${info.version} 下载完成，等待用户确认重启`);
    updateStatus = { state: 'downloaded', version: info.version, error: null };
    sendUpdateStatus();

    // 弹出提示框
    dialog
      .showMessageBox({
        type: 'info',
        title: '更新就绪',
        message: `新版本 v${info.version} 已下载完成，是否立即重启以安装更新？`,
        buttons: ['现在重启', '稍后'],
        defaultId: 0,
        cancelId: 1,
      })
      .then(({ response }) => {
        if (response === 0) {
          logUpdate('用户确认重启，安装更新...');
          // 退出并安装
          setImmediate(() => autoUpdater.quitAndInstall());
        } else {
          logUpdate('用户选择稍后重启');
        }
      });
  });
}

/**
 * @param {number} ms
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 检测端口是否已被占用（127.0.0.1）
 * @param {number} port
 */
function isPortInUse(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(true));
    server.once('listening', () => {
      server.close();
      resolve(false);
    });
    server.listen(port, '127.0.0.1');
  });
}

/**
 * 从 8000 起寻找可用端口（最多到 8010）
 */
async function findAvailablePort() {
  for (let port = DEFAULT_PORT; port <= MAX_PORT; port += 1) {
    // eslint-disable-next-line no-await-in-loop
    const inUse = await isPortInUse(port);
    if (!inUse) {
      return port;
    }
  }
  throw new Error(`端口 ${DEFAULT_PORT}-${MAX_PORT} 均不可用`);
}

/**
 * 轮询后端健康检查
 * @param {number} port
 */
async function waitForBackendReady(port) {
  for (let attempt = 0; attempt < HEALTH_POLL_MAX_ATTEMPTS; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/health`);
      if (response.ok) {
        const body = await response.json();
        if (body && body.status === 'ok') {
          return true;
        }
      }
    } catch {
      // 后端尚未就绪
    }
    // eslint-disable-next-line no-await-in-loop
    await sleep(HEALTH_POLL_INTERVAL_MS);
  }
  return false;
}

/**
 * 返回生产模式下嵌入的 backend.exe 路径
 */
function getBackendExePath() {
  const exeName = process.platform === 'win32' ? 'backend.exe' : 'backend';
  return path.join(process.resourcesPath, 'backend', exeName);
}

/**
 * 启动后端进程
 *
 * 开发模式：spawn python -m uvicorn backend.main:app
 * 生产模式：spawn 嵌入的 backend.exe（PyInstaller 打包）
 *
 * @param {number} port
 */
function startBackendProcess(port) {
  const env = {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    RA_PORT: String(port),
  };

  if (isDev) {
    // 开发模式：通过 Python + uvicorn 启动
    const args = [
      '-m',
      'uvicorn',
      'backend.main:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(port),
    ];
    env.PYTHONPATH = PROJECT_ROOT;

    backendProcess = spawn(PYTHON, args, {
      cwd: PROJECT_ROOT,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
  } else {
    // 生产模式：启动嵌入的 PyInstaller 打包后端
    const exePath = getBackendExePath();
    if (!fs.existsSync(exePath)) {
      throw new Error(`后端可执行文件未找到: ${exePath}`);
    }

    backendProcess = spawn(exePath, [], {
      cwd: path.dirname(exePath),
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
  }

  backendProcess.stdout?.on('data', (chunk) => {
    process.stdout.write(`[backend] ${chunk}`);
  });

  backendProcess.stderr?.on('data', (chunk) => {
    process.stderr.write(`[backend] ${chunk}`);
  });

  backendProcess.on('exit', (code, signal) => {
    if (code !== null && code !== 0) {
      console.error(`[backend] 进程退出 code=${code} signal=${signal}`);
    }
    backendProcess = null;
  });
}

/**
 * 终止后端进程（Windows 使用 taskkill /T）
 */
function stopBackendProcess() {
  if (!backendProcess || backendProcess.killed) {
    backendProcess = null;
    return Promise.resolve();
  }

  const pid = backendProcess.pid;
  if (!pid) {
    backendProcess = null;
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      backendProcess = null;
      resolve();
    };

    backendProcess.once('exit', finish);

    if (process.platform === 'win32') {
      try {
        execSync(`taskkill /PID ${pid} /T`, { stdio: 'ignore' });
      } catch {
        // 进程可能已退出
      }

      setTimeout(() => {
        if (backendProcess && !backendProcess.killed) {
          try {
            execSync(`taskkill /PID ${pid} /T /F`, { stdio: 'ignore' });
          } catch {
            try {
              backendProcess.kill();
            } catch {
              // ignore
            }
          }
        }
        finish();
      }, BACKEND_KILL_TIMEOUT_MS);
      return;
    }

    try {
      backendProcess.kill('SIGTERM');
    } catch {
      finish();
      return;
    }

    setTimeout(() => {
      if (backendProcess && !backendProcess.killed) {
        try {
          backendProcess.kill('SIGKILL');
        } catch {
          // ignore
        }
      }
      finish();
    }, BACKEND_KILL_TIMEOUT_MS);
  });
}

/** 清理主进程创建的临时文件 */
function cleanupTempFiles() {
  for (const filePath of tempFiles) {
    try {
      if (fs.existsSync(filePath)) {
        fs.unlinkSync(filePath);
      }
    } catch {
      // ignore
    }
  }
  tempFiles.length = 0;
}

/**
 * @param {string} message
 */
function notifyBackendError(message) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('backend-error', message);
  }
  dialog.showErrorBox('后端启动失败', message);
}

async function bootstrapBackend() {
  backendPort = await findAvailablePort();
  startBackendProcess(backendPort);

  const ready = await waitForBackendReady(backendPort);
  if (!ready) {
    const message = '后端在 15 秒内未能就绪，请检查 Python 环境与依赖是否已安装。';
    notifyBackendError(message);
    throw new Error(message);
  }

  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('backend-ready', backendPort);
  }
}

function getFrontendUrl() {
  if (isDev) {
    return FRONTEND_DEV_URL;
  }
  return path.join(PROJECT_ROOT, 'frontend', 'dist', 'index.html');
}

async function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show();
  });

  try {
    await bootstrapBackend();
  } catch (error) {
    console.error(error);
    // 仍加载前端，便于开发调试 UI
  }

  if (isDev) {
    await mainWindow.loadURL(FRONTEND_DEV_URL);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    await mainWindow.loadFile(getFrontendUrl());
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
    stopBackendProcess(); // 确保窗口关闭时停止后端（macOS 尤其重要）
  });
}

ipcMain.handle('get-backend-port', () => backendPort);

// ── 自动更新 IPC ──
ipcMain.handle('get-app-version', () => app.getVersion());
ipcMain.handle('get-update-status', () => updateStatus);

// 手动触发更新检查
ipcMain.handle('check-for-updates', async () => {
  if (isDev) {
    updateStatus = { state: 'error', version: null, error: '开发模式暂不支持更新检测' };
    sendUpdateStatus();
    return updateStatus;
  }
  updateStatus = { state: 'checking', version: null, error: null };
  sendUpdateStatus();
  try {
    const result = await autoUpdater.checkForUpdates();
    // checkForUpdates 返回 UpdateCheckResult；实际状态由事件驱动
    return updateStatus;
  } catch (err) {
    logUpdate(`手动检查失败: ${err.message}`);
    updateStatus = { state: 'error', version: null, error: err.message };
    sendUpdateStatus();
    return updateStatus;
  }
});

// 用户确认后安装更新
ipcMain.handle('install-update', () => {
  autoUpdater.quitAndInstall();
});

app.whenReady().then(async () => {
  await createMainWindow();

  // 启动后 5 秒静默检测更新（仅生产模式）
  if (!isDev) {
    setTimeout(() => {
      logUpdate('启动后静默检测更新...');
      autoUpdater.checkForUpdatesAndNotify().catch((err) => {
        logUpdate(`静默检测失败: ${err.message}`);
      });
    }, 5000);
  }

  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      // 仅后端已停止时重新启动
      if (!backendProcess || backendProcess.killed) {
        await bootstrapBackend();
      }
      await createMainWindow();
    }
  });
});

app.on('before-quit', (event) => {
  if (!backendProcess) {
    cleanupTempFiles();
    return;
  }

  event.preventDefault();
  stopBackendProcess()
    .then(() => {
      cleanupTempFiles();
      app.exit(0);
    })
    .catch(() => {
      cleanupTempFiles();
      app.exit(1);
    });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
