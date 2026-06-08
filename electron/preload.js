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
});
