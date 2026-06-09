/** 更新状态 */
export interface UpdateStatus {
  state: 'idle' | 'checking' | 'available' | 'downloading' | 'downloaded' | 'error' | 'no-update'
  version: string | null
  error: string | null
}

/** 下载进度 */
export interface DownloadProgress {
  percent: number
}

/** Electron preload API 类型声明 */
export interface ElectronAPI {
  /** 获取实际后端端口（8000-8010 fallback），返回 Promise<number> */
  getBackendPort: () => Promise<number>
  /** 后端健康检查通过后触发，回调参数为实际端口号 */
  onBackendReady: (callback: (port: number) => void) => void
  /** 后端启动失败时触发，回调参数为错误消息 */
  onBackendError: (callback: (message: string) => void) => void

  // ── 自动更新 ──
  /** 获取应用版本号 */
  getAppVersion: () => Promise<string>
  /** 获取当前更新状态 */
  getUpdateStatus: () => Promise<UpdateStatus>
  /** 手动检查更新 */
  checkForUpdates: () => Promise<UpdateStatus>
  /** 安装已下载的更新（重启应用） */
  installUpdate: () => Promise<void>
  /** 监听更新状态变化 */
  onUpdateStatus: (callback: (status: UpdateStatus) => void) => void
  /** 监听下载进度 */
  onUpdateDownloadProgress: (callback: (progress: DownloadProgress) => void) => void
  /** 移除所有更新相关监听 */
  removeUpdateStatusListeners: () => void
}

declare global {
  interface Window {
    electron?: ElectronAPI
  }
}

export {}
