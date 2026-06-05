# ResearchAssistant

> 一个面向科研人员的本地 AI 文献精读与学术写作助手。解决网页版 Kimi 无法一次性处理 30-50 篇文献的痛点，所有数据本地存储，绝对私密。

---

## 1. 项目定位

**核心场景**：一次性阅读 30-50 篇文献（批量上传→批次管理→跨文献问答→FTS5 搜索）

**目标用户**：
- 生物技术/制药行业研发人员
- 高校及科研院所研究人员
- 需要频繁处理文献、数据、论文的理工科背景用户

**应用形态**：
- 桌面独立应用：Windows / macOS 双平台
- 打包格式：Windows `.exe`、macOS `.dmg`
- 一键安装，无需配置环境

**核心能力**：
- 批量上传 30-50 篇 PDF，自动提取结构化摘要
- 跨文献综合问答（基于摘要拼接，利用 K2.6 的 256K 上下文）
- 单篇深度精读（基于原文，连续对话）
- 论文分块撰写（Markdown 编辑器 + 学术润色）

---

## 2. 技术架构

```
┌─────────────────────────────────────────────┐
│              Electron (桌面壳)                 │
│  ┌─────────────────────────────────────┐    │
│  │    React + TypeScript + Tailwind      │    │
│  │   文献列表 / PDF预览 / 聊天面板 / 编辑器  │    │
│  └─────────────────────────────────────┘    │
│              ↓ HTTP (localhost:8000)        │
│         Python 后端进程 (FastAPI)            │
│    pdfplumber + Kimi API + SQLite + SSE      │
└─────────────────────────────────────────────┘
```

### 技术选型

| 层级 | 技术 | 选型理由 |
|------|------|----------|
| **桌面框架** | Electron | 成熟生态，打包 exe/dmg 一条命令 |
| **UI 框架** | React 18 + TypeScript | 组件生态成熟，Cursor 生成代码质量高 |
| **UI 组件** | shadcn/ui + Tailwind CSS | 按需引入，风格统一 |
| **PDF 预览** | react-pdf / iframe | 前端直接渲染 |
| **后端框架** | FastAPI | 异步，自动 OpenAPI 文档，SSE 原生支持 |
| **PDF 解析** | pdfplumber + pymupdf | 文本提取，复杂排版 fallback |
| **AI 接口** | Kimi API (OpenAI 兼容) | K2.6 默认，模型名配置化，未来升级只改字符串 |
| **数据库** | SQLite | 全部本地存储，绝对私密 |
| **ORM** | SQLAlchemy 2.0 + Alembic | 数据库迁移、类型安全 |
| **数据验证** | Pydantic v2 | 前后端共用 schema |
| **打包工具** | PyInstaller + electron-builder | 分别打包后合并 |

### 通信协议

- 前端 → 后端：HTTP REST + Server-Sent Events (SSE)
- AI 问答使用 SSE 流式响应，前端逐字渲染
- 文件上传：multipart/form-data，支持批量
- 本地地址：`http://127.0.0.1:8000`，Electron 主进程自动管理后端进程生命周期

### Electron 进程管理

**启动**：
1. Electron 主进程启动
2. spawn Python 后端进程
3. 轮询 `GET /health`（最多 30 次 × 500ms）
4. 后端就绪后加载 React 前端
5. 若 15 秒未就绪，弹窗提示"后端启动失败"

**关闭**：
1. `app.on('before-quit')` 触发
2. 向 Python 进程发送 SIGTERM，3 秒后未退出则 SIGKILL
3. 清理临时文件

**端口冲突**：探测 8000 端口，被占用则 fallback 到 8001-8010，实际端口通过 IPC 传给前端

---

## 3. 项目目录

```
research-assistant/
├── README.md
├── package.json                # Electron + 前端依赖
├── requirements.txt            # Python 依赖
│
├── backend/                    # Python 后端（FastAPI）
│   ├── main.py                 # 应用入口
│   ├── config.py               # 配置：API Key / 模型名 / 路径 / 超时
│   ├── alembic.ini             # 数据库迁移
│   ├── alembic/
│   ├── api/v1/
│   │   ├── health.py           # 健康检查
│   │   ├── batches.py          # 批次管理
│   │   ├── literature_crud.py  # 上传/解析/列表/详情/删除/标签
│   │   ├── literature_chat.py  # 跨文献问答 + 单篇问答
│   │   ├── literature_export.py # 翻译 + 导出
│   │   ├── batches.py            # 批量提取
│   │   ├── chat_sessions.py    # 会话历史
│   │   ├── paper.py            # 论文撰写/润色
│   │   ├── settings.py         # API Key / 模型配置
│   │   └── data.py             # 数据库管理
│   ├── services/
│   │   ├── pdf_parser.py       # PDF 文本提取
│   │   ├── kimi_client.py      # Kimi API 封装
│   │   ├── db.py               # SQLAlchemy 引擎
│   │   └── extract_prompt.py   # Prompt 模板
│   ├── models/
│   │   ├── schemas.py          # Pydantic Schema
│   │   └── tables.py           # SQLAlchemy 表定义
│   └── tests/                  # 单元测试
│
├── frontend/                   # React + TypeScript
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Literature.tsx      # 文献库
│   │   │   ├── PaperWrite.tsx     # 论文撰写
│   │   │   └── Settings.tsx       # 设置
│   │   ├── components/
│   │   │   ├── FileUploader.tsx   # 批量上传
│   │   │   ├── LiteratureList.tsx # 文献列表
│   │   │   ├── LiteratureDetail.tsx # 单篇详情
│   │   │   ├── ChatPanel.tsx      # AI 对话面板
│   │   │   ├── MultiSelectBar.tsx  # 跨文献多选
│   │   │   ├── MarkdownEditor.tsx  # Markdown 编辑器
│   │   │   └── PdfViewer.tsx      # PDF 预览
│   │   ├── api/client.ts          # HTTP 客户端
│   │   └── hooks/
│   │       ├── useSSE.ts          # SSE Hook
│   │       └── useLiterature.ts   # 数据管理 Hook
│   └── public/
│
├── electron/
│   ├── main.js                 # 主进程（spawn/kill/health轮询）
│   └── preload.js              # IPC 暴露
│
└── data/                       # 运行时数据（gitignore）
    ├── papers/                 # 原始 PDF
    └── research-assistant.db   # SQLite
```

---

## 4. 功能需求

### 4.1 文献批量处理（核心）

**批量 PDF 上传**
- 支持拖拽上传和文件多选（Ctrl/Cmd + 多选）
- 单次上限 50 个文件，单个上限 50MB
- 上传进度条，文件类型校验仅接受 `.pdf`
- 上传后自动触发解析（可配置手动触发）
- 上传时支持创建/选择批次

**PDF 解析与存储**
- `pdfplumber` 提取每页文本，按页存入 `paper_pages`
- 提取失败 fallback 到 `pymupdf`
- 检测扫描版：单页文本 < 50 字符标记 `is_scanned = true`
- 提取元数据（标题/作者/年份/期刊），优先 PDF 元数据，缺失时 AI 补充

**结构化摘要提取（JSON Mode）**
- 调用 Kimi K2.6，强制输出固定格式：
  ```json
  {
    "title": "string",
    "authors": ["string"],
    "year": "integer",
    "journal": "string",
    "background": "string",
    "methods": "string",
    "key_results": ["string"],
    "conclusion": "string",
    "keywords": ["string"]
  }
  ```
- 存入 `extracted_data` 表
- 批量提取：`POST /batch-extract` 串行执行 pending 文献，间隔 ≥ 1 秒
- 失败重试 3 次，3 次失败后锁定为 `extract_failed`

**文献库管理**
- 列表视图：标题 / 第一作者 / 年份 / 期刊 / 提取状态 / 标签
- FTS5 全文搜索（标题 + 摘要 + 关键词），所有规模统一使用
- 按年份、期刊、标签、提取状态筛选；按年份/时间/标题排序
- 标签系统：用户自定义标签，多标签筛选
- 删除文献：硬删除数据库记录 + 本地 PDF + 关联摘要

**跨文献综合问答**
- 顶部选择批次或勾选 N 篇文献（建议上限 30 篇）
- 后端拼接所选文献的结构化摘要送入 K2.6
- SSE 流式响应，前端逐字渲染
- 30 篇摘要 ≈ 20K-30K tokens，远低于 256K 限制
- 支持追问，历史保存到 `chat_sessions`

**单篇深度精读**
- 左侧 PDF 预览，右侧 ChatPanel 连续对话
- 基于原文（`paper_pages` 全文）或摘要（`extracted_data`）
- 支持"定位到页"：AI 引用页码时前端可跳转

**中英互译**
- 单篇翻译全文摘要，保留段落结构
- 结果存入 `extracted_data.translation`

**导出报告**
- 跨文献问答结果导出为 Markdown
- 包含文献列表 + 问答内容 + 时间戳

### 4.2 论文撰写辅助

**分块 Markdown 编辑器**
- 五个标签页：摘要 / 引言 / 方法 / 结果 / 讨论
- 左侧输入，右侧实时预览（Markdown 渲染，无 LaTeX）
- 停止输入 3 秒后自动保存到 `paper_blocks`

**学术润色**
- 选中段落调用润色 API
- 方向：学术化表达 / 中英互润 / 逻辑连贯性检查
- 支持接受/拒绝/对比查看

**参考文献格式化（P2）**
- 输入 DOI 或标题获取元数据，输出 GB/T 7714 格式

### 4.3 通用功能

**设置页**
- API Key 输入：Fernet 加密，密钥存系统 keychain（Python `keyring`），密文存 SQLite
- 模型选择：K2.5 / K2.6，默认 K2.6
- 高级配置：temperature、max_tokens、timeout
- 数据管理：数据库大小、导出/重置数据库

**会话历史**
- 文献问答和润色历史本地保存
- 支持查看列表、继续对话、删除会话

---

## 5. 数据库设计

### 5.1 表结构

#### `papers` — 文献元数据
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| file_path | VARCHAR | 本地 PDF 路径 |
| file_size | INTEGER | 文件大小（字节） |
| page_count | INTEGER | 页数 |
| title | VARCHAR | 标题 |
| authors | JSON | 作者列表 |
| year | INTEGER | 发表年份 |
| journal | VARCHAR | 期刊名 |
| doi | VARCHAR | DOI |
| status | ENUM | `pending` / `extracting` / `completed` / `failed` / `extract_failed` |
| batch_id | UUID FK | 关联 batches（可为 NULL） |
| is_scanned | BOOLEAN | 是否扫描版 |
| created_at | DATETIME | 上传时间 |
| extraction_attempts | INTEGER | 提取尝试次数（默认 0） |
| last_error | TEXT | 最后一次提取错误信息 |
| extracted_at | DATETIME | 最后一次提取尝试时间 |
| updated_at | DATETIME | 更新时间 |

#### `paper_pages` — 按页原文
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| paper_id | UUID FK | 关联 papers |
| page_number | INTEGER | 页码（从 1 开始） |
| text_content | TEXT | 该页提取的文本 |
| char_count | INTEGER | 该页字符数 |

#### `extracted_data` — 结构化摘要
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| paper_id | UUID FK | 关联 papers（UNIQUE） |
| background | TEXT | 研究背景 |
| methods | TEXT | 研究方法 |
| key_results | JSON | 核心结果列表 |
| conclusion | TEXT | 结论 |
| keywords | JSON | 关键词列表 |
| raw_json | JSON | API 返回的原始 JSON（备份） |
| translation | TEXT | 中文翻译 |
| extracted_at | DATETIME | 提取时间 |

#### `paper_blocks` — 论文撰写分块
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| block_name | VARCHAR(20) | `abstract` / `introduction` / `methods` / `results` / `discussion` |
| content | TEXT | Markdown 内容 |
| updated_at | DATETIME | 最后更新时间 |
| UNIQUE(block_name) | — | MVP 单用户单论文假设 |

#### `batches` — 文献批次
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| name | VARCHAR(100) | 批次名称 |
| description | TEXT | 可选描述 |
| paper_count | INTEGER | 文献数量（冗余） |
| updated_at | DATETIME | 最后更新时间 |
| created_at | DATETIME | 创建时间 |

**paper_count 维护**：上传文献到批次时 +1，移除/删除时 -1，清空时设为 0，事务保证。

#### `paper_tags` — 标签关联表
| 字段 | 类型 | 说明 |
|------|------|------|
| paper_id | UUID FK | 关联 papers |
| tag | VARCHAR(50) | 标签名 |
| PRIMARY KEY (paper_id, tag) | — | 联合主键 |

#### `chat_sessions` — 对话会话
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| session_type | ENUM | `literature_multi` / `literature_single` / `paper_polish` |
| paper_ids | JSON | 关联文献 ID 列表 |
| primary_paper_id | UUID FK | 单篇场景主文献 ID |
| title | VARCHAR | 会话标题 |
| messages | JSON | 对话历史（OpenAI 消息格式） |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 最后更新时间 |

#### `paper_audit_logs` — 调试日志（可选）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| paper_id | UUID FK | 关联 papers（可为 NULL） |
| action | VARCHAR(50) | 操作类型 |
| detail | JSON | 详情 |
| created_at | DATETIME | 时间 |

> **可选写入**：不强制记录所有操作。建议 batch_extract 失败时记录 1 条供排错。

#### `settings` — 应用配置
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 固定为 1 |
| api_key_encrypted | BLOB | 加密后的 API Key（Fernet + keyring） |
| default_model | VARCHAR | 默认模型名 |
| temperature | FLOAT | 默认温度 |
| max_tokens | INTEGER | 默认最大 tokens |
| theme | VARCHAR | 主题（light/dark/system） |
| updated_at | DATETIME | 更新时间 |

### 5.2 FTS5 全文搜索

```sql
CREATE VIRTUAL TABLE papers_fts USING fts5(
    title, authors, journal, keywords, background, methods, conclusion,
    content='papers', content_rowid='rowid'
);
```

- FTS5 默认启用，所有规模统一使用
- 通过触发器保持 `papers` 表与 `papers_fts` 同步

### 5.3 约束与索引
- `paper_pages.paper_id` + `page_number`：联合唯一
- `papers`：`title`、`year`、`status`、`batch_id` 索引
- `extracted_data.paper_id`：唯一
- `chat_sessions.primary_paper_id`：索引
- `paper_tags.tag`：索引
- 外键：ON DELETE CASCADE（删除文献时级联删除 pages、extracted_data、paper_tags）

---

## 6. API 接口

### 6.1 健康检查
| 方法 | 路径 | 说明 | 响应 |
|------|------|------|------|
| GET | `/health` | 健康检查 | `{"status": "ok", "version": config.VERSION}` |

### 6.2 批次模块 (`/api/v1/batches`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/` | 创建批次 | `{name: string(1-100), description?: string}` | `{id, name, created_at}` |
| GET | `/` | 获取批次列表 | query: page, page_size | `{items[], total, page}` |
| GET | `/{id}` | 获取批次详情 | - | `{id, name, papers: [...]}` |
| PUT | `/{id}` | 更新批次 | `{name?, description?}` | `{id, name}` |
| DELETE | `/{id}` | 删除批次（文献保留，batch_id 设为 NULL） | - | `{success}` |

### 6.3 文献 CRUD (`/api/v1/literature`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/upload` | 批量上传 PDF | multipart: files[], batch_id? | `{uploaded: [{id, title, status}]}` |
| POST | `/{id}/parse` | 手动触发解析 | - | `{paper_id, page_count, status}` |
| GET | `/` | 获取文献列表 | query: search, tag, year, status, sort, page | `{items[], total, page}` |
| GET | `/{id}` | 获取单篇详情 | - | PaperDetail + pages[] + extracted_data |
| GET | `/{id}/pages` | 批量获取全部页面 | - | `{pages: [...]}` |
| GET | `/{id}/page/{page_num}` | 获取单页原文 | - | `{text_content}` |
| PUT | `/{id}/tags` | 更新标签 | `{tags: string[]}` | `{id, tags}` |
| DELETE | `/{id}` | 删除文献 | - | `{success}` |
| GET | `/tags` | 获取所有标签汇总 | - | `{tags[], counts}` |
| GET | `/stats` | 文献统计 | - | `{total, completed, pending, failed, extract_failed}` |
| POST | `/{id}/extract` | 手动触发摘要提取 | - | SSE 流。状态机：pending→extracting→completed/failed（3次失败锁定 extract_failed） |
| POST | `/{id}/translate` | 翻译摘要 | - | `{translation}` |

### 6.4 文献问答 (`/api/v1/literature/chat`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/chat` | 跨文献问答 | `{paper_ids[]?, batch_id?, question, session_id?}` | SSE 流式文本。`batch_id` 与 `paper_ids` 二选一，batch_id 自动展开为该批次全部文献 |
| POST | `/{id}/chat` | 单篇精读问答 | `{question, session_id?, use_fulltext?}` | SSE 流式文本。`use_fulltext=true` 时调取全文，false 时仅用摘要，默认 false |

### 6.5 批量提取 (`/api/v1/batches`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/batches/batch-extract` | 一键提取所有 pending 文献 | - | SSE 流：`{type: 'progress', current, total, paper_id, status, title}` / `{type: 'done', success_count, fail_count}` / `{type: 'error', paper_id, error, attempt}` |

### 6.6 文献导出 (`/api/v1/literature/export`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/export` | 导出报告 | query: `session_id`, `format` | File download |

### 6.7 会话历史 (`/api/v1/chat-sessions`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/chat-sessions` | 获取会话列表 | query: type, page | `{items[], total, page}` |
| GET | `/chat-sessions/{id}` | 获取会话详情 | - | `{id, title, messages, created_at}` |
| DELETE | `/chat-sessions/{id}` | 删除会话 | - | `{success}` |

### 6.8 论文撰写 (`/api/v1/paper`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/blocks` | 获取五个分块 | - | `{abstract, introduction, methods, results, discussion}` |
| PUT | `/blocks/{block_name}` | 保存分块 | `{content: string}` | `{block_name, updated_at}` |
| POST | `/polish` | 润色段落 | `{text, direction}` | `{polished_text, diff?}` |
| POST | `/citation` | 格式化参考文献 | `{doi? or title?}` | `{citation_gb7714}` |

### 6.9 设置 (`/api/v1/settings`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/` | 获取配置 | - | Settings（api_key 脱敏） |
| PUT | `/` | 更新配置 | `{api_key?, model?, temperature?, max_tokens?}` | Settings |
| POST | `/test` | 测试 API Key | - | `{valid, model, balance?}` |

**API Key 存储**：
- 加密密钥：Python `keyring` 库存系统 keychain（Windows Credential Manager / macOS Keychain）
- 密文：Fernet 加密后的 API Key 存 SQLite
- 首次设置：前端 HTTP → 后端从 keychain 读取/生成密钥 → 加密 → 存 SQLite
- 后续启动：后端从 keychain 读取密钥 → 解密 → 使用
- SQLite 文件泄露也无法解密，没有系统 keychain 中的密钥

### 6.10 数据管理 (`/api/v1/data`)
> **仅限 localhost 访问**，拒绝远程请求。

| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/db-stats` | 数据库统计 | - | `{db_size, table_counts}` |
| POST | `/export-db` | 导出数据库 | - | File download |
| POST | `/reset-db` | 重置数据库（需二次确认） | `{confirm: true}` | `{success}` |

---

## 7. Kimi API 调用

### 模型配置
```python
VERSION = "1.0.0"
KIMI_BASE_URL = "https://api.moonshot.cn/v1"
DEFAULT_MODEL = "kimi-k2-6"
AVAILABLE_MODELS = ["kimi-k2-5", "kimi-k2-6"]
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 8192
REQUEST_TIMEOUT = 120
BATCH_EXTRACT_CONCURRENCY = 1  # MVP 默认串行，未来可调
```

### 结构化提取 Prompt（JSON Mode）
```
你是一位专业的科研文献分析助手。请仔细阅读以下论文全文，提取关键信息并以 JSON 格式返回。

要求字段：
- title: 论文标题
- authors: 作者列表（数组）
- year: 发表年份（整数）
- journal: 期刊名
- background: 研究背景（200字内）
- methods: 核心研究方法（200字内）
- key_results: 核心结果列表（3-5条，每条100字内）
- conclusion: 结论（150字内）
- keywords: 关键词列表（5-8个）

注意：
1. 如果某字段信息缺失，返回空字符串或空数组，不要编造
2. 保持学术准确性，不要过度概括
3. 输出必须是合法 JSON，不要包含 markdown 代码块标记

论文全文：
{paper_text}
```

### 跨文献问答 Prompt
```
你是一位专业的科研综述助手。以下是 {n} 篇文献的结构化摘要，请基于这些信息回答用户的问题。

注意：
1. 回答必须基于提供的文献，不要引入外部知识
2. 如果多篇文献观点冲突，请明确指出分歧
3. 引用文献时标注 [作者 年份]
4. 如果信息不足以回答问题，请明确说明

{concatenated_abstracts}

用户问题：{question}
```

### 容错
- 批量提取串行执行，间隔 ≥ 1 秒
- 单请求超时 120 秒，失败重试 3 次，指数退避（1s, 2s, 4s）
- 网络异常时返回友好错误，不崩溃
- SSE 流：客户端断开时正确取消 asyncio 协程，防止资源泄漏

---

## 8. SSE 流式响应

### 后端 SSE 规范
- Content-Type: `text/event-stream`
- 消息格式：`data: {"type": "chunk", "content": "..."}

`
- 进度事件（批量提取）：`data: {"type": "progress", "current": 3, "total": 50, "paper_id": "...", "status": "extracting", "title": "..."}

`
- 结束：`data: {"type": "done"}

`
- 错误：`data: {"type": "error", "message": "..."}

`

### 前端 useSSE Hook
使用 `fetch + ReadableStream`（EventSource 不支持 POST 请求体）：

```typescript
// 实现要点：
// 1. fetch POST 请求，获取 response.body ReadableStream
// 2. TextDecoder 逐块解码，按 "

" 分割 SSE 事件
// 3. 解析每行 "data: {...}" 格式，提取 JSON
// 4. 事件分发：type='chunk'/'progress' → 累加文本；type='done' → 结束；type='error' → 终止
// 5. 断线检测：reader.read() 抛异常时触发重连
// 6. 重连：最多 3 次，间隔 1s/2s/4s，传递 last_seq 断点续传
// 7. 消息序号去重：每条消息带 seq 字段
// 8. 组件卸载时 abortController.abort() 关闭连接
// 9. 禁止并发 SSE 流
// 10. 批量提取场景：progress 事件更新进度条（current/total）
```

---

## 9. 开发规范

### 开发原则
1. **先查后改**：新模块、重构、Bug 修复先排查根因，再动手
2. **先后端再前端**：后端接口契约（OpenAPI 文档）确认后，前端才能动工
3. **独立模块**：新模块独立路由/独立文件，禁止塞进已有文件
4. **字段前瞻性**：DB 建模和 API 设计提前布局未来字段
5. **代码清理**：旧逻辑直接删除，无需标记 DEPRECATED
6. **Git 提交**：验证完成后再统一提交
7. **模块分工**：Cursor 负责后端重构/新建模块/数据库迁移；CodeBuddy 负责前端主力及小后端改动
8. **路由注册顺序**：FastAPI 固定路径（如 `POST /chat`）必须在动态路径（如 `POST /{id}/chat`）之前注册

### 安全注意事项
- API Key 通过 `keyring` 加密存储，不硬编码
- 本地 SQLite 数据文件仅当前用户可访问
- 网络请求仅限 localhost，不暴露外部端口
- 敏感信息绝不输入 AI 上下文

---

## 10. 开发阶段

### Step 1：后端骨架（Python FastAPI）
**目标**：打通"上传 PDF → 解析 → 提取摘要 → 问答"核心链路

**交付物**：
- [ ] FastAPI 项目骨架（main.py + config + db）
- [ ] 数据库表创建（Alembic）：papers / paper_pages / extracted_data / paper_blocks / batches / paper_tags / chat_sessions / paper_audit_logs / settings / papers_fts
- [ ] `GET /health`
- [ ] `POST /upload` — 批量上传，支持批次
- [ ] `POST /{id}/parse` — pdfplumber 解析
- [ ] `POST /{id}/extract` — JSON Mode 提取摘要
- [ ] `POST /batches/batch-extract` — 批量提取，SSE 进度
- [ ] `POST /chat` — 跨文献问答，支持 batch_id
- [ ] `POST /{id}/chat` — 单篇精读问答
- [ ] `GET/PUT /settings` — API Key 配置
- [ ] 启动幂等逻辑：extracting → pending 重置
- [ ] pytest 单元测试

**验收**：Postman 完成上传→解析→提取→问答完整流程；/docs 可访问；所有表存在

### Step 2：前端骨架（React + Electron）
**目标**：文献库 UI 和核心交互

**交付物**：
- [ ] Electron 主进程：spawn 后端 + health 轮询 + kill 进程
- [ ] React 路由 + 布局
- [ ] 文献库：FileUploader + LiteratureList
- [ ] 单篇精读：PdfViewer + ChatPanel
- [ ] 跨文献问答：MultiSelectBar + ChatPanel
- [ ] 设置页：API Key + 模型选择 + 测试
- [ ] useSSE.ts：fetch + ReadableStream + 断线重连
- [ ] 会话历史页面

**验收**：拖拽上传 5 篇 → 自动提取 → 列表展示 → 单篇问答 → 跨文献问答；SSE 正常；关闭无孤儿进程

### Step 3：论文撰写模块
**目标**：分块 Markdown 编辑器 + 润色

**交付物**：
- [ ] MarkdownEditor：5 个标签页，自动保存
- [ ] 润色功能：调用 `/polish`，对比查看/接受
- [ ] 参考文献格式化（P2，可选）

**验收**：五个分块正常输入/预览/保存；润色返回学术化改写

### Step 4：打包与发布
**目标**：生成可安装包，推 GitHub 开源

**交付物**：
- [ ] PyInstaller 打包后端为 `backend.exe`（--onedir）
- [ ] electron-builder 打包前端，extraResources 嵌入 backend
- [ ] 安装包合并（Windows: Inno Setup / macOS: DMG）
- [ ] README.md：安装说明、使用教程、API Key 获取指南
- [ ] LICENSE：MIT 或 Apache-2.0

---

## 11. 已知风险

| 风险 | 影响 | 应对 |
|------|------|------|
| Kimi API 限流（50 篇批量提取） | 高 | 串行 + 1秒间隔 + 重试；Coding Plan 用户限额较高 |
| 大 PDF 解析超时（>50MB 扫描版） | 中 | 文件上限 50MB；扫描版标记后跳过 AI 提取 |
| Electron 打包体积大 | 低 | 预期 150-200MB，可接受 |
| Windows Defender 误杀 | 中 | 首次启动可能触发 SmartScreen，README 说明 |
| 模型迭代适配 | 低 | 模型名配置化，升级只改 config.py 一行 |
| SSE 断线 | 中 | useSSE.ts 内置断线重连，最多 3 次 |
| 孤儿进程残留 | 高 | SIGTERM + SIGKILL 双保险 |

---

## 12. 验收标准

### 文献助手
- [ ] 批量上传 30 篇 PDF，全部正确解析
- [ ] 30 篇结构化摘要提取完成，JSON 正确
- [ ] 跨文献问答：选择 10 篇提问，5 秒内开始流式响应
- [ ] 单篇精读：PDF 预览 + 连续对话，AI 引用原文
- [ ] 翻译：英文文献一键翻译，保留段落结构
- [ ] 会话历史：可查看、继续、删除

### 论文撰写
- [ ] 五个分块正常输入、预览、保存
- [ ] 润色：学术化改写版本
- [ ] 自动保存：停止输入 3 秒后保存

### 通用
- [ ] Windows 打包为 `.exe`，双击启动
- [ ] API Key 配置并持久化（加密存储）
- [ ] 网络异常友好提示，不崩溃
- [ ] 关闭后无 Python 孤儿进程
