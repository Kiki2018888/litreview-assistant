# API 契约文档

> 状态：核心接口已锁定（v1.0），前端可据此动工  
> 作用：前后端开发合同，后端验证通过后锁定，前端据此动工  
> 基于：SPEC 文档第 6 章 API 接口

---

## 变更记录

| 日期 | 版本 | 变更说明 | 锁定状态 |
|------|------|----------|----------|
| 2026-06-04 | v0.1 | 框架初始化，仅列路径和状态 | 🔓 未锁定 |
| 2026-06-08 | v1.0 | 锁定 10 个核心接口，填充完整 Schema | 🔒 已锁定 |
| 2026-06-08 | v1.1 | 修正 SSE 事件类型（对齐后端实际实现）、Chat 请求体字段、Settings 响应字段 | 🔒 已锁定 |
| 2026-06-15 | v1.3.0 | 批次→项目迁移完成：第二节改写为 projects，batch_id 标注 deprecated 兼容别名，刷新各节实际状态 | 🔒 已锁定 |

---

## 一、健康检查

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| GET | `/health` | ✅ 已验证 | 2026-06-15 | Postman |

**响应 Schema**：
```json
{
  "status": "ok",
  "version": "string"
}
```

---

## 二、项目管理（`/api/v1/projects`）

> **历史说明**：v1.1.0 前称为"批次管理"（`/api/v1/batches`），现已彻底下线并由 `/api/v1/projects` 替代。

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| POST | `/` | ✅ 已验证 | 2026-06-15 | pytest |
| GET | `/` | ✅ 已验证 | 2026-06-15 | pytest |
| GET | `/{project_id}` | ✅ 已验证 | 2026-06-15 | pytest |
| PUT | `/{project_id}` | ✅ 已验证 | 2026-06-15 | pytest |
| DELETE | `/{project_id}` | ✅ 已验证 | 2026-06-15 | pytest |
| POST | `/{project_id}/move-papers` | ✅ 已验证 | 2026-06-15 | pytest |
| POST | `/{project_id}/batch-extract` | ✅ 已验证 | 2026-06-15 | pytest + SSE |

### GET `/` —— 项目列表

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | number | ❌ | 1 | 页码，从 1 开始 |
| page_size | number | ❌ | 20 | 每页条数，最大 100 |

**响应 Schema**：

```json
{
  "items": [
    {
      "id": "string (UUID)",
      "name": "string",
      "description": "string | null",
      "paper_count": 0,
      "is_default": false,
      "created_at": "string (ISO 8601 datetime)",
      "updated_at": "string (ISO 8601 datetime)"
    }
  ],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| items[].id | string (UUID) | ✅ | 项目唯一标识 |
| items[].name | string | ✅ | 项目名称，1-100 字符 |
| items[].description | string \| null | ❌ | 项目描述 |
| items[].paper_count | number | ✅ | 项目内文献数量 |
| items[].is_default | boolean | ✅ | 是否为默认项目「未分类」（不可删除/不可改名） |
| items[].created_at | string (datetime) | ✅ | 创建时间 ISO 8601 |
| items[].updated_at | string (datetime) | ✅ | 更新时间 ISO 8601 |

> **默认项目**：系统初始化时自动创建「未分类」项目（is_default=true），文献上传未指定 project_id 时自动归入该项目。该默认项目不可删除、不可重命名。

### POST `/` —— 创建项目

**请求 Schema**：

```json
{
  "name": "string",
  "description": "string | null"
}
```

**响应 Schema**：同列表项（`ProjectResponse`），状态码 201。

### GET `/{project_id}` —— 项目详情

响应用于列表项的 `ProjectResponse` 基础字段外追加：

| 字段 | 类型 | 说明 |
|------|------|------|
| paper_ids | string[] (UUID) | 该项目下所有文献 ID 列表 |

### PUT `/{project_id}` —— 更新项目

**请求 Schema**：

```json
{
  "name": "string | null",
  "description": "string | null"
}
```

> **约束**：默认项目（is_default=true）不可重命名，传入不同的 name 返回 400。

### DELETE `/{project_id}` —— 删除项目

**响应 Schema**：

```json
{
  "success": true,
  "moved_count": 5
}
```

> **约束**：默认项目不可删除（400）。删除后项目内文献自动移入「未分类」项目，不丢失任何文献。

### POST `/{project_id}/move-papers` —— 批量移动文献到项目

**请求 Schema**：

```json
{
  "paper_ids": ["uuid1", "uuid2"]
}
```

**响应 Schema**：

```json
{
  "success": true,
  "moved_count": 2
}
```

### POST `/{project_id}/batch-extract` —— 一键提取项目全部文献

无请求体，SSE 流式响应（进度事件同第五节）。

---

## 三、文献 CRUD（`/api/v1/literature`）

### GET `/` —— 文献列表 🔒

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| GET | `/` | ✅ 已验证 | 2026-06-08 | Postman |

**查询参数**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | number | ❌ | 1 | 页码，从 1 开始 |
| page_size | number | ❌ | 20 | 每页条数，最大 100 |
| status | string | ❌ | — | 筛选状态：pending / extracting / completed / failed / extract_failed |
| project_id | string (UUID) | ❌ | — | 按项目筛选（正名）；`batch_id` 作为已废弃兼容别名仍受支持，计划在未来版本移除 |
| search | string | ❌ | — | 全文搜索关键词 |
| tag | string | ❌ | — | 按标签筛选 |

**响应 Schema**：

```json
{
  "items": [
    {
      "id": "string (UUID)",
      "title": "string | null",
      "authors": ["string"] | null,
      "year": 2024 | null,
      "journal": "string | null",
      "status": "pending",
      "tags": ["string"],
      "project_id": "string (UUID) | null",
      "created_at": "string (ISO 8601 datetime)"
    }
  ],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| items[].id | string (UUID) | ✅ | 文献唯一标识 |
| items[].title | string \| null | ❌ | 文献标题（从 PDF 解析） |
| items[].authors | string[] \| null | ❌ | 作者列表 |
| items[].year | number \| null | ❌ | 出版年份 |
| items[].journal | string \| null | ❌ | 期刊名称 |
| items[].status | string (enum) | ✅ | 状态：pending \| extracting \| completed \| failed \| extract_failed |
| items[].tags | string[] | ✅ | 标签列表（可为空数组 []） |
| items[].project_id | string (UUID) \| null | ❌ | 所属项目 ID（正名）；`batch_id` 为已废弃兼容别名，计划在未来版本移除 |
| items[].created_at | string (datetime) | ✅ | 创建时间 ISO 8601 |

---

### GET `/{id}` —— 文献详情 🔒

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| GET | `/{id}` | ✅ 已验证 | 2026-06-08 | Postman |

**响应 Schema**：

```json
{
  "id": "string (UUID)",
  "file_path": "string",
  "file_size": 102400 | null,
  "page_count": 12 | null,
  "title": "string | null",
  "authors": ["Author A", "Author B"] | null,
  "year": 2024 | null,
  "journal": "Nature | null",
  "doi": "10.xxx/xxx | null",
  "status": "completed",
  "project_id": "string (UUID) | null",
  "is_scanned": false,
  "extraction_attempts": 1,
  "last_error": "string | null",
  "created_at": "string (ISO 8601 datetime)",
  "extracted_at": "string (ISO 8601 datetime) | null",
  "updated_at": "string (ISO 8601 datetime)",
  "tags": ["tag1", "tag2"],
  "extracted_data": {
    "id": "string (UUID)",
    "paper_id": "string (UUID)",
    "background": "string | null",
    "methods": "string | null",
    "key_results": ["result1", "result2"] | null,
    "conclusion": "string | null",
    "keywords": ["keyword1", "keyword2"] | null,
    "raw_json": {} | null,
    "translation": "string | null",
    "extracted_at": "string (ISO 8601 datetime) | null"
  } | null
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string (UUID) | ✅ | 文献唯一标识 |
| file_path | string | ✅ | PDF 文件存储路径 |
| file_size | number \| null | ❌ | 文件大小（字节） |
| page_count | number \| null | ❌ | 总页数 |
| title | string \| null | ❌ | 文献标题 |
| authors | string[] \| null | ❌ | 作者列表 |
| year | number \| null | ❌ | 出版年份 |
| journal | string \| null | ❌ | 期刊名称 |
| doi | string \| null | ❌ | DOI |
| status | string (enum) | ✅ | 状态：pending \| extracting \| completed \| failed \| extract_failed |
| project_id | string (UUID) \| null | ❌ | 所属项目 ID（正名）；`batch_id` 为已废弃兼容别名，计划在未来版本移除 |
| is_scanned | boolean | ✅ | 是否为扫描版 PDF |
| extraction_attempts | number | ✅ | 提取尝试次数 |
| last_error | string \| null | ❌ | 最近一次错误信息 |
| created_at | string (datetime) | ✅ | 创建时间 |
| extracted_at | string (datetime) \| null | ❌ | 提取完成时间 |
| updated_at | string (datetime) | ✅ | 更新时间 |
| tags | string[] | ✅ | 标签列表 |
| extracted_data.extracted_at | string (datetime) \| null | ❌ | 提取完成时间 |

---

### POST `/upload` —— 批量上传 🔒

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| POST | `/upload` | ✅ 已验证 | 2026-06-08 | Postman |

**请求（multipart/form-data）**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| files | File[] | ✅ | PDF 文件列表（多文件） |
| project_id | string (UUID) | ❌ | 可选，指定所属项目（正名）；`batch_id` 作为已废弃兼容别名仍受支持，计划在未来版本移除 |

**响应 Schema**：

```json
{
  "uploaded": [
    {
      "id": "string (UUID)",
      "title": "string | null",
      "status": "pending",
      "page_count": 12 | null
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| uploaded[].id | string (UUID) | 上传后的文献 ID |
| uploaded[].title | string \| null | 从 PDF 解析的标题 |
| uploaded[].status | string | 固定 "pending" |
| uploaded[].page_count | number \| null | 解析出的页数 |

---

### POST `/{id}/extract` —— 单篇 AI 提取 🔒

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| POST | `/{id}/extract` | ✅ 已验证 | 2026-06-08 | Postman + SSE |

**请求**：无请求体（paper_id 在 URL 路径中）。

**SSE 事件类型**（按顺序出现）：

| 事件 type | 字段 | 出现条件 | 说明 |
|-----------|------|----------|------|
| `status` | status, attempt, max_retries | 始终 | 提取开始通知 |
| `retry` | attempt, max_retries, delay | API 调用失败重试时 | 指数退避重试通知 |
| `chunk` | content | API 调用成功 | Kimi JSON Mode 完整响应 |
| `result` | paper_id, title, keywords | 提取成功 | 提取结果摘要 |
| `error` | code, message, attempt? | 提取失败 / JSON 解析失败 | 错误信息（EXTRACT_FAILED / EXTRACT_JSON_PARSE_ERROR） |
| `cancelled` | message | 客户端断开 | 客户端主动断开连接 |
| `done` | (无额外字段) | 始终（终止事件） | SSE 流结束标记 |

**SSE 流示例**（成功路径）：

```
data: {"type":"status","status":"extracting","attempt":1,"max_retries":2}

data: {"type":"chunk","content":"{\"background\":\"...\",\"methods\":\"...\"}"}

data: {"type":"result","paper_id":"uuid","title":"论文标题","keywords":["词1","词2"]}

data: {"type":"done"}
```

**SSE 流示例**（错误路径）：

```
data: {"type":"status","status":"extracting","attempt":1,"max_retries":2}

data: {"type":"retry","attempt":1,"max_retries":2,"delay":3}

data: {"type":"error","code":"EXTRACT_FAILED","message":"...","attempt":1}

data: {"type":"done"}
```

---

## 四、文献问答（`/api/v1/literature`）

### POST `/chat` —— 跨文献对话 🔒

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| POST | `/chat` | ✅ 已验证 | 2026-06-08 | Postman + SSE |

**请求 Schema**：

```json
{
  "question": "string",
  "paper_ids": ["uuid1", "uuid2"] | null,
  "project_id": "string (UUID) | null",
  "session_id": "string (UUID) | null"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | ✅ | 用户提问 |
| paper_ids | string[] (UUID) | ❌ | 文献 ID 列表（与 project_id 二选一） |
| project_id | string (UUID) | ❌ | 项目 ID（正名，与 paper_ids 二选一）；`batch_id` 作为已废弃兼容别名仍受支持，内部会自动转换为 project_id |
| session_id | string (UUID) | ❌ | 续接已有会话，不传则新建 |

**SSE 事件类型**：

| 事件 type | 字段 | 说明 |
|-----------|------|------|
| `chunk` | content | AI 回复片段（流式） |
| `result` | session_id, answer_length | 完成摘要 |
| `error` | code, message | 错误信息 |
| `done` | (无额外字段) | SSE 流结束标记 |

**SSE 流示例**：

```
data: {"type":"chunk","content":"根据您提供的文献摘要..."}

data: {"type":"chunk","content":"进一步分析表明..."}

data: {"type":"result","session_id":"uuid","answer_length":1234}

data: {"type":"done"}
```

---

### POST `/{id}/chat` —— 单篇精读 🔒

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| POST | `/{id}/chat` | ✅ 已验证 | 2026-06-08 | Postman + SSE |

**请求 Schema**：

```json
{
  "question": "string",
  "use_fulltext": false,
  "session_id": "string (UUID) | null"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | ✅ | 用户提问 |
| use_fulltext | boolean | ❌ | 是否使用全文（默认 false=使用摘要） |
| session_id | string (UUID) | ❌ | 续接已有会话 |

**SSE 流格式**：同 `/chat`（chunk / result / error / done）

---

## 五、批量提取（`/api/v1/projects/{project_id}/batch-extract`）

> **历史说明**：v1.1.0 前位于 `/api/v1/batches/batch-extract`，现已迁至 projects 子路由。该项目下的 pending 文献会被依次提取。

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| POST | `/api/v1/projects/{project_id}/batch-extract` | ✅ 已验证 | 2026-06-15 | pytest + SSE |

**请求**：无请求体（project_id 在 URL 路径中）。

**SSE 进度事件格式**：

```
data: {"type": "progress", "current": 3, "total": 50, "paper_id": "uuid", "status": "extracting", "title": "论文标题"}

data: {"type": "progress", "current": 3, "total": 50, "paper_id": "uuid", "status": "completed", "title": "论文标题"}

data: {"type": "progress", "current": 4, "total": 50, "paper_id": "uuid", "status": "failed", "title": "论文标题", "error": "错误信息"}

data: {"type": "done", "success_count": 48, "fail_count": 2}

data: {"type": "done", "success_count": 0, "fail_count": 0, "message": "没有待处理的文献"}
```

| 事件类型 | 字段 | 说明 |
|------|------|------|
| progress | current | 当前处理的文献序号（1-based） |
| progress | total | 总文献数 |
| progress | paper_id | 当前文献 ID |
| progress | status | 当前文献状态：extracting / completed / failed |
| progress | title | 文献标题 |
| progress | error | 错误信息（仅 status=failed 时） |
| done | success_count | 成功数量 |
| done | fail_count | 失败数量 |
| done | message | 可选消息（如"没有待处理的文献"） |

---

## 六、文献导出（`/api/v1/literature/export`）

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| GET | `/export` | ⬜ 待开发 | — | — |

---

## 七、会话历史（`/api/v1/chat-sessions`）

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| GET | `/` | ✅ 已验证 | 2026-06-15 | pytest |
| GET | `/{session_id}` | ✅ 已验证 | 2026-06-15 | pytest |
| DELETE | `/{session_id}` | ✅ 已验证 | 2026-06-15 | pytest |

---

## 八、论文撰写（`/api/v1/paper`）

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| GET | `/blocks` | ⬜ 待开发 | — | — |
| PUT | `/blocks/{block_name}` | ⬜ 待开发 | — | — |
| POST | `/polish` | ⬜ 待开发 | — | — |
| POST | `/citation` | ⬜ 待开发 | — | — |

---

## 九、设置（`/api/v1/settings`）

### GET `/` —— 获取设置 🔒

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| GET | `/` | ✅ 已验证 | 2026-06-08 | Postman |

**响应 Schema**：

```json
{
  "id": 1,
  "has_api_key": true,
  "api_key_preview": "sk-****xxxx",
  "default_model": "kimi-latest | null",
  "available_models": ["kimi-latest", "kimi-thinking"],
  "temperature": 0.7 | null,
  "max_tokens": 4096 | null,
  "theme": "light | null",
  "updated_at": "string (ISO 8601 datetime)"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | number | 设置记录 ID（单用户始终为 1） |
| has_api_key | boolean | 是否已配置 API Key（不返回明文） |
| api_key_preview | string | API Key 脱敏预览：sk-****xxxx |
| default_model | string \| null | 默认模型 |
| available_models | string[] | 可用模型列表（来自 config） |
| temperature | number \| null | 温度参数 0-2 |
| max_tokens | number \| null | 最大 token 数 |
| theme | string \| null | 界面主题 |
| updated_at | string (datetime) | 最后更新时间 |

---

### PUT `/` —— 更新设置 🔒

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| PUT | `/` | ✅ 已验证 | 2026-06-08 | Postman |

**请求 Schema**：

```json
{
  "api_key": "string | null",
  "default_model": "string | null",
  "temperature": 0.7 | null,
  "max_tokens": 4096 | null,
  "theme": "string | null"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| api_key | string \| null | ❌ | Kimi API Key（后端 Fernet 加密存储，不返回明文） |
| default_model | string \| null | ❌ | 默认模型名称 |
| temperature | number \| null | ❌ | 温度参数 0-2 |
| max_tokens | number \| null | ❌ | 最大 token 数 |
| theme | string \| null | ❌ | 界面主题 |

**API Key 存储方案**：
- 加密密钥：系统 keychain（`keyring`）
- 密文：Fernet 加密后存 SQLite `settings` 表
- 首次设置：前端 HTTP → 后端从 keychain 读取/生成密钥 → 加密 → 存 SQLite
- 后续启动：后端从 keychain 读取密钥 → 解密 → 使用

---

## 十、数据管理（`/api/v1/data`）

> ⚠️ **仅限 localhost 访问**，拒绝远程请求。

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| GET | `/db-stats` | ✅ 已验证 | 2026-06-15 | pytest |
| POST | `/export-db` | ✅ 已验证 | 2026-06-15 | pytest |
| POST | `/reset-db` | ✅ 已验证 | 2026-06-15 | pytest |

---

## 锁定规则

1. **后端开发完成** → Postman 验证通过 → 填写 Schema → 标记 🔒 锁定
2. **锁定后** → 前端才能依据此文档动工
3. **如需变更** → 先修改后端 → 重新验证 → 更新本文档 → 通知前端适配
4. **禁止前端在锁定前依据推断开发**
