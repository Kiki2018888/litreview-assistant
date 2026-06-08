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

---

## 一、健康检查

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| GET | `/health` | ⬜ 待开发 | — | — |

**响应 Schema**：
```json
{
  "status": "ok",
  "version": "string"
}
```

---

## 二、批次管理（`/api/v1/batches`）

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| POST | `/` | ⬜ 待开发 | — | — |
| GET | `/` | ✅ 已验证 | — | Postman |
| GET | `/{id}` | ⬜ 待开发 | — | — |
| PUT | `/{id}` | ⬜ 待开发 | — | — |
| DELETE | `/{id}` | ⬜ 待开发 | — | — |

### GET `/` —— 批次列表

**响应 Schema**：
```json
{
  "items": [
    {
      "id": "string (UUID)",
      "name": "string",
      "description": "string | null",
      "paper_count": 0,
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
| items[].id | string (UUID) | ✅ | 批次唯一标识 |
| items[].name | string | ✅ | 批次名称，1-100 字符 |
| items[].description | string \| null | ❌ | 批次描述 |
| items[].paper_count | number | ✅ | 批次内文献数量 |
| items[].created_at | string (datetime) | ✅ | 创建时间 ISO 8601 |
| items[].updated_at | string (datetime) | ✅ | 更新时间 ISO 8601 |

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
| batch_id | string (UUID) | ❌ | — | 按批次筛选 |
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
      "batch_id": "string (UUID) | null",
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
| items[].batch_id | string (UUID) \| null | ❌ | 所属批次 ID |
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
  "batch_id": "string (UUID) | null",
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
| batch_id | string (UUID) \| null | ❌ | 所属批次 ID |
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
| batch_id | string (UUID) | ❌ | 可选，指定所属批次 |

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

**SSE 流格式**：

```
data: {"type": "extract_chunk", "chunk": "..."}

data: {"type": "extract_done", "data": {...}}

data: {"type": "extract_error", "message": "..."}
```

**extract_done 中 data 结构**（同 ExtractedDataResponse）：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string (UUID) | 提取记录 ID |
| paper_id | string (UUID) | 关联文献 ID |
| background | string \| null | 研究背景 |
| methods | string \| null | 研究方法 |
| key_results | string[] \| null | 关键结果列表 |
| conclusion | string \| null | 结论 |
| keywords | string[] \| null | 关键词列表 |
| raw_json | object \| null | AI 原始 JSON 输出 |
| translation | string \| null | 摘要翻译 |
| extracted_at | string (datetime) \| null | 提取时间 |

---

## 四、文献问答（`/api/v1/literature`）

### POST `/chat` —— 跨文献对话 🔒

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| POST | `/chat` | ✅ 已验证 | 2026-06-08 | Postman + SSE |

**请求 Schema**：

```json
{
  "paper_ids": ["uuid1", "uuid2"],
  "message": "string",
  "use_fulltext": true,
  "session_id": "string (UUID) | null"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| paper_ids | string[] (UUID) | ✅ | 参与问答的文献 ID 列表 |
| message | string | ✅ | 用户问题 |
| use_fulltext | boolean | ✅ | 是否使用全文（true=全文，false=摘要） |
| session_id | string (UUID) \| null | ❌ | 续接已有会话，不传则新建 |

**SSE 流格式**：

```
data: {"type": "chunk", "content": "AI 回复片段..."}

data: {"type": "done", "session_id": "uuid"}

data: {"type": "error", "message": "错误描述"}
```

---

### POST `/{id}/chat` —— 单篇精读 🔒

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| POST | `/{id}/chat` | ✅ 已验证 | 2026-06-08 | Postman + SSE |

**请求 Schema**：

```json
{
  "message": "string",
  "use_fulltext": true,
  "session_id": "string (UUID) | null"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | ✅ | 用户问题 |
| use_fulltext | boolean | ✅ | 是否使用全文 |
| session_id | string (UUID) \| null | ❌ | 续接已有会话 |

**SSE 流格式**：同上（chunk / done / error）

---

## 五、批量提取（`/api/v1/batches/batch-extract`）

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| POST | `/batch-extract` | ✅ 已验证 | 2026-06-08 | Postman + SSE |

**请求（可选）**：

```json
{
  "batch_id": "string (UUID) | null"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| batch_id | string (UUID) \| null | ❌ | 指定批次，不传则提取全部 pending 文献 |

**SSE 进度事件格式**：

```
data: {"type": "progress", "current": 3, "total": 50, "paper_id": "uuid", "status": "extracting", "title": "论文标题"}

data: {"type": "done", "success_count": 48, "fail_count": 2}

data: {"type": "error", "message": "..."}
```

| 事件类型 | 字段 | 说明 |
|------|------|------|
| progress | current | 当前处理的文献序号（1-based） |
| progress | total | 总文献数 |
| progress | paper_id | 当前文献 ID |
| progress | status | 当前文献状态：extracting \| extract_failed \| completed |
| progress | title | 文献标题 |
| done | success_count | 成功数量 |
| done | fail_count | 失败数量 |

---

## 六、文献导出（`/api/v1/literature/export`）

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| GET | `/export` | ⬜ 待开发 | — | — |

---

## 七、会话历史（`/api/v1/chat-sessions`）

| 方法 | 路径 | 状态 | 锁定日期 | 验证方式 |
|------|------|------|----------|----------|
| GET | `/` | ⬜ 待开发 | — | — |
| GET | `/{id}` | ⬜ 待开发 | — | — |
| DELETE | `/{id}` | ⬜ 待开发 | — | — |

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
  "default_model": "kimi-latest | null",
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
| default_model | string \| null | 默认模型 |
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
| GET | `/db-stats` | ⬜ 待开发 | — | — |
| POST | `/export-db` | ⬜ 待开发 | — | — |
| POST | `/reset-db` | ⬜ 待开发 | — | — |

---

## 锁定规则

1. **后端开发完成** → Postman 验证通过 → 填写 Schema → 标记 🔒 锁定
2. **锁定后** → 前端才能依据此文档动工
3. **如需变更** → 先修改后端 → 重新验证 → 更新本文档 → 通知前端适配
4. **禁止前端在锁定前依据推断开发**
