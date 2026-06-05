# 安全规范文档

> 版本：v1.0  
> 日期：2026-06-04  
> 适用范围：ResearchAssistant 全部后端代码与数据存储

---

## 一、核心安全原则

1. **绝对私密**：所有用户数据（PDF、摘要、对话历史）仅本地存储，不上传云端
2. **API Key 零泄露**：API Key 绝不硬编码、不打印日志、不返回前端、不暴露于进程参数
3. **本地隔离**：网络请求仅限 `localhost`，拒绝任何远程访问
4. **最小权限**：Electron 主进程与 Python 后端进程权限最小化

---

## 二、API Key 存储方案（SPEC 6.9）

### 架构

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│  前端输入   │────▶│  后端 FastAPI   │────▶│ 系统 Keychain │
│  (HTTP)     │     │  (Fernet 加密)  │     │ (加密密钥)    │
└─────────────┘     └─────────────────┘     └─────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │  SQLite       │
                    │  settings表   │
                    │  api_key_enc  │
                    └───────────────┘
```

### 流程

**首次设置**：
1. 用户在前端输入 API Key
2. 后端通过 `keyring` 读取/生成 Fernet 密钥（如不存在则生成）
3. 使用 Fernet 密钥加密 API Key
4. 密文存入 SQLite `settings.api_key_encrypted`

**后续启动**：
1. 后端从 `keyring` 读取 Fernet 密钥
2. 从 SQLite 读取密文
3. 解密后使用 API Key 调用 Kimi API

### 技术细节

| 组件 | 技术 | 存储位置 |
|------|------|----------|
| Fernet 密钥 | `keyring` 库 | 系统 Keychain（Windows Credential Manager / macOS Keychain / Linux Secret Service） |
| 加密后 API Key | Fernet (AES-128-CBC + HMAC) | SQLite `settings.api_key_encrypted` (BLOB) |
| 解密后 API Key | 内存变量 | 仅存在于后端进程内存，不持久化 |

### 代码约束

```python
# 禁止事项（红线）
- 禁止在代码中硬编码 API Key
- 禁止将 API Key 打印到日志（即使 DEBUG 级别）
- 禁止将 API Key 返回给前端（GET /settings 必须脱敏）
- 禁止将 API Key 作为环境变量或命令行参数传递
- 禁止在错误堆栈中暴露 API Key
- 禁止将 API Key 存入前端 localStorage / sessionStorage
```

---

## 三、数据存储安全

### SQLite 文件

| 项目 | 要求 |
|------|------|
| 文件位置 | `data/research-assistant.db`（用户主目录下） |
| 文件权限 | 仅当前用户可读写（Unix: 600，Windows: 限制当前用户） |
| 备份 | 用户手动导出（通过 `/api/v1/data/export-db`） |
| 加密 | MVP 阶段不加密 SQLite 文件本身（依赖系统文件权限） |

### 原始 PDF 文件

| 项目 | 要求 |
|------|------|
| 存储位置 | `data/papers/` 目录 |
| 文件命名 | `{uuid}.pdf`（避免原始文件名泄露敏感信息） |
| 删除 | 硬删除（`DELETE /{id}` 时同步删除文件） |

---

## 四、网络隔离

### 通信范围

```
前端 (Electron)  ──HTTP──▶  后端 (FastAPI @ localhost:8000)
                              │
                              └──▶  Kimi API (api.moonshot.cn)
```

### 约束

- 后端仅监听 `127.0.0.1:8000`，禁止 `0.0.0.0`
- 数据管理 API（`/api/v1/data/*`）必须拒绝非 localhost 请求
- 前端通过 `fetch` 访问 `http://127.0.0.1:8000`，不暴露到外部网络
- Electron `webSecurity` 保持开启，禁止跨域到非 localhost

---

## 五、进程安全

### Electron 主进程

- `contextIsolation: true`（默认）
- `preload.js` 仅暴露必要 IPC 通道
- 禁止在 `preload.js` 中暴露 Node.js 全局对象

### Python 后端进程

- 通过 `spawn` 启动，工作目录限制在项目目录
- 关闭时 `SIGTERM` → 3 秒 → `SIGKILL`，防止孤儿进程
- 禁止后端进程直接访问用户文件系统（除 `data/` 目录）

---

## 六、敏感信息处理清单

| 信息类型 | 存储方式 | 日志中 | 前端可见 | 加密 |
|----------|----------|--------|----------|------|
| Kimi API Key | keyring + Fernet + SQLite | ❌ 绝不 | ❌ 脱敏 | ✅ |
| 用户 PDF 内容 | 本地文件系统 | ❌ 绝不 | ✅ 预览 | ❌ 依赖系统权限 |
| 结构化摘要 | SQLite | ❌ 绝不 | ✅ 展示 | ❌ 依赖系统权限 |
| 对话历史 | SQLite | ❌ 绝不 | ✅ 展示 | ❌ 依赖系统权限 |
| 论文草稿 | SQLite | ❌ 绝不 | ✅ 展示 | ❌ 依赖系统权限 |
| 错误堆栈 | 日志文件 | ✅ 可记录 | ❌ 脱敏 | ❌ |

---

## 七、安全事件响应

| 场景 | 响应措施 |
|------|----------|
| SQLite 文件泄露 | 由于 API Key 密文依赖系统 keychain 中的密钥，单独泄露 SQLite 无法解密 |
| API Key 泄露 | 立即更换 Key；检查日志确认泄露途径；更新加密密钥 |
| 进程残留 | 启动时检测端口占用；关闭时强制 kill；定期清理孤儿进程 |
| 远程访问尝试 | 拒绝非 localhost 请求；记录审计日志 |

---

## 八、禁止清单（开发红线）

- ❌ 禁止将 API Key 写入任何配置文件（`.env`、`.ini`、`config.py`）
- ❌ 禁止在 Git 中提交任何含 API Key 的文件
- ❌ 禁止在 Issue / PR 中粘贴 API Key
- ❌ 禁止在调试输出中打印完整 API Key（即使截断也不允许）
- ❌ 禁止将用户数据发送到除 Kimi API 之外的任何外部服务
- ❌ 禁止在 AI 上下文中输入 API Key（包括 coding agent 的 prompt）
- ❌ 禁止后端监听 `0.0.0.0` 或公网 IP
- ❌ 禁止前端直接调用 Kimi API（必须通过后端代理）
