# 错误处理规范

> 版本：v1.0  
> 日期：2026-06-04  
> 适用范围：后端 API、SSE 流、前端交互

---

## 一、错误码体系

### HTTP 状态码

| 状态码 | 使用场景 | 前端处理 |
|--------|----------|----------|
| 200 | 成功 | 正常渲染 |
| 400 | 请求参数错误（Bad Request） | 展示具体字段错误 |
| 401 | API Key 无效或缺失 | 跳转设置页提示配置 |
| 404 | 资源不存在（文献/批次/会话） | 展示"未找到"空状态 |
| 422 | 验证失败（Pydantic Validation） | 展示字段校验错误 |
| 429 | Kimi API 限流 | 提示"请求过于频繁，请稍后重试" |
| 500 | 服务端内部错误 | 展示友好错误页，记录日志 |
| 503 | 后端服务未启动 | Electron 显示"服务启动中" |

### 错误响应体格式

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "detail": "object | null",
    "request_id": "string"
  }
}
```

| 字段 | 说明 |
|------|------|
| `code` | 业务错误码（如 `EXTRACT_FAILED`、`PDF_PARSE_ERROR`） |
| `message` | 用户友好的错误描述（中文） |
| `detail` | 技术详情（仅 DEBUG 模式展示，生产环境可为 null） |
| `request_id` | 唯一请求 ID，用于日志追溯 |

---

## 二、业务错误码

| 错误码 | 场景 | HTTP 状态 | 用户提示 |
|--------|------|-----------|----------|
| `UPLOAD_FILE_TOO_LARGE` | 单个文件 > 50MB | 400 | "文件过大，单个文件上限 50MB" |
| `UPLOAD_TOO_MANY_FILES` | 单次上传 > 50 个 | 400 | "单次最多上传 50 个文件" |
| `UPLOAD_INVALID_TYPE` | 非 PDF 文件 | 400 | "仅支持 PDF 格式" |
| `PDF_PARSE_ERROR` | pdfplumber + pymupdf 均失败 | 500 | "PDF 解析失败，可能是扫描版或加密文件" |
| `PDF_SCANNED_DETECTED` | 单页 < 50 字符 | 200（标记） | "检测到扫描版 PDF，已跳过自动提取" |
| `EXTRACT_FAILED` | 摘要提取 3 次均失败 | 500 | "摘要提取失败，请检查 PDF 质量或手动输入" |
| `EXTRACT_TIMEOUT` | 提取请求超时 120s | 504 | "提取超时，请稍后重试" |
| `KIMI_API_ERROR` | Kimi API 返回错误 | 502 | "AI 服务暂时不可用，请稍后重试" |
| `KIMI_API_RATE_LIMIT` | 触发限流 | 429 | "请求过于频繁，请等待 1 分钟后重试" |
| `BATCH_NOT_FOUND` | 批次 ID 不存在 | 404 | "批次不存在" |
| `PAPER_NOT_FOUND` | 文献 ID 不存在 | 404 | "文献不存在" |
| `SESSION_NOT_FOUND` | 会话 ID 不存在 | 404 | "会话不存在" |
| `INVALID_API_KEY` | API Key 无效或过期 | 401 | "API Key 无效，请检查设置" |
| `DB_CONNECTION_ERROR` | SQLite 连接失败 | 500 | "数据库连接异常，请重启应用" |
| `SERVER_NOT_READY` | 后端未启动 | 503 | "服务启动中，请稍候..." |

---

## 三、SSE 错误流规范

### 标准 SSE 事件格式

```
data: {"type": "chunk", "content": "...", "seq": 1}



data: {"type": "chunk", "content": "...", "seq": 2}



data: {"type": "done", "seq": 99}



```

### 错误事件格式

```
data: {"type": "error", "code": "KIMI_API_ERROR", "message": "AI 服务暂时不可用", "seq": 42}



```

### SSE 错误处理规则

| 场景 | 后端行为 | 前端行为 |
|------|----------|----------|
| Kimi API 流中断 | 发送 `type: error` 事件，关闭 SSE 连接 | 展示错误信息，保留已接收内容 |
| 客户端断开 | 取消 asyncio 协程，释放资源 | 无需处理（已断开） |
| 网络超时 | 发送 `type: error` 事件，带 `code: TIMEOUT` | 展示超时提示，提供"重试"按钮 |
| 限流触发 | 发送 `type: error` 事件，带 `code: RATE_LIMIT` | 展示倒计时，自动重试或手动重试 |
| 服务端异常 | 发送 `type: error` 事件，带 `code: INTERNAL_ERROR` | 展示友好错误页，保留上下文 |

### 批量提取 SSE 进度事件

```
data: {"type": "progress", "current": 3, "total": 50, "paper_id": "uuid", "status": "extracting", "title": "论文标题"}



data: {"type": "error", "paper_id": "uuid", "error": "提取失败", "attempt": 3}



data: {"type": "done", "success_count": 48, "fail_count": 2}



```

---

## 四、重试策略

### Kimi API 调用

| 场景 | 重试次数 | 退避间隔 | 说明 |
|------|----------|----------|------|
| 网络超时 | 3 次 | 1s → 2s → 4s（指数退避） | 第 3 次失败后标记失败 |
| 限流 (429) | 3 次 | 1s → 2s → 4s | 如仍限流，提示用户等待 |
| 服务端错误 (5xx) | 3 次 | 1s → 2s → 4s | 第 3 次失败后标记失败 |
| 客户端错误 (4xx) | 0 次 | 不重试 | 立即返回错误 |

### SSE 连接

| 场景 | 重试次数 | 退避间隔 | 说明 |
|------|----------|----------|------|
| 连接断开 | 3 次 | 1s → 2s → 4s | 传递 `last_seq` 断点续传 |
| 网络异常 | 3 次 | 1s → 2s → 4s | 保留已接收内容 |

---

## 五、前端错误展示规范

### Toast 通知（轻量错误）

- 位置：右上角
- 持续时间：3-5 秒（错误）/ 2 秒（成功）
- 样式：红色（错误）/ 黄色（警告）/ 绿色（成功）
- 适用场景：上传失败、标签更新失败、翻译失败

### 内联错误（表单/输入）

- 位置：输入框下方或右侧
- 样式：红色文字 + 图标
- 适用场景：参数校验失败、空值提示

### 错误页面（严重错误）

- 适用场景：后端未启动、数据库连接失败、批量提取全部失败
- 内容：错误图标 + 友好文案 + "重试"按钮 + "查看日志"链接（DEBUG 模式）

### 加载状态

| 场景 | 组件 | 说明 |
|------|------|------|
| 上传中 | 进度条 | 显示当前文件 / 总文件 |
| 解析中 | Skeleton / Spinner | 文献列表项占位 |
| 提取中 | 进度条 + 状态标签 | 显示 `extracting` / `completed` / `failed` |
| SSE 流式输出 | 打字机效果 + 停止按钮 | 显示"AI 正在思考..." |
| 批量提取 | 全局进度条 | 显示 `current/total` + 成功/失败计数 |

---

## 六、日志规范

### 日志级别

| 级别 | 使用场景 | 是否包含敏感信息 |
|------|----------|------------------|
| DEBUG | 开发调试（SQL 语句、请求体） | ❌ 绝不包含 API Key |
| INFO | 正常业务流程（上传完成、提取完成） | ❌ 绝不包含 API Key |
| WARNING | 可恢复异常（解析 fallback、重试） | ❌ 绝不包含 API Key |
| ERROR | 业务错误（提取失败、API 错误） | ❌ 绝不包含 API Key |
| CRITICAL | 系统级错误（数据库损坏、进程崩溃） | ❌ 绝不包含 API Key |

### 日志格式

```
[YYYY-MM-DD HH:MM:SS] [LEVEL] [request_id] [module] message
```

示例：
```
[2026-06-04 14:32:01] [ERROR] [req_abc123] [literature_crud] PDF parse failed for paper_id=xxx: pdfplumber error + pymupdf error
```

### 日志文件

- 位置：`logs/research-assistant.log`
- 轮转：按天轮转，保留 7 天
- 大小：单文件上限 10MB

---

## 七、开发约束

### 后端

- 所有异常必须捕获，禁止裸抛未处理异常
- 错误响应必须包含 `request_id`，便于追溯
- SSE 流错误必须使用 `type: error` 事件，禁止直接断开连接
- 禁止在错误响应中暴露堆栈跟踪（生产环境）
- 禁止在日志中打印 API Key（即使截断）

### 前端

- 所有 API 调用必须处理错误分支（`try/catch` 或 `.catch()`）
- SSE 连接必须处理 `error` 事件和 `close` 事件
- 用户操作失败时必须提供明确的反馈（Toast / 内联错误）
- 禁止在控制台打印 API Key 或敏感数据
- 禁止将错误堆栈直接展示给用户（生产环境）
