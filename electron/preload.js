/**
 * Preload：通过 contextBridge 安全暴露 IPC 通道
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electron', {
  /** 获取实际后端端口（8000-8010 fallback 后的值） */
  getBackendPort: () => ipcRenderer.invoke('get-backend-port'),

  /** 后端健康检查通过后触发 */
  onBackendReady: (callback) => {
    if (typeof callback !== 'function') return;
    ipcRenderer.on('backend-ready', (_event, port) => {
      callback(port);
    });
  },

  /** 后端启动失败时触发 */
  onBackendError: (callback) => {
    if (typeof callback !== 'function') return;
    ipcRenderer.on('backend-error', (_event, message) => {
      callback(message);
    });
  },

  // ── 自动更新 ──

  /** 获取应用版本号 */
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),

  /** 获取当前更新状态 */
  getUpdateStatus: () => ipcRenderer.invoke('get-update-status'),

  /** 手动检查更新 */
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),

  /** 安装已下载的更新（重启应用） */
  installUpdate: () => ipcRenderer.invoke('install-update'),

  /** 监听更新状态变化（主进程推送） */
  onUpdateStatus: (callback) => {
    if (typeof callback !== 'function') return;
    ipcRenderer.on('update-status', (_event, status) => {
      callback(status);
    });
  },

  /** 监听下载进度 */
  onUpdateDownloadProgress: (callback) => {
    if (typeof callback !== 'function') return;
    ipcRenderer.on('update-download-progress', (_event, progress) => {
      callback(progress);
    });
  },

  /** 移除更新状态监听 */
  removeUpdateStatusListeners: () => {
    ipcRenderer.removeAllListeners('update-status');
    ipcRenderer.removeAllListeners('update-download-progress');
  },
});
