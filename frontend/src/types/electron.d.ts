/** Electron preload API 类型声明 */
export interface ElectronAPI {
  /** 获取实际后端端口（8000-8010 fallback），返回 Promise<number> */
  getBackendPort: () => Promise<number>
  /** 后端健康检查通过后触发，回调参数为实际端口号 */
  onBackendReady: (callback: (port: number) => void) => void
  /** 后端启动失败时触发，回调参数为错误消息 */
  onBackendError: (callback: (message: string) => void) => void
}

declare global {
  interface Window {
    electron?: ElectronAPI
  }
}

export {}
