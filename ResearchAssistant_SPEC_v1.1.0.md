# ResearchAssistant v1.1.0 SPEC

> 一个面向科研人员的本地 AI 文献精读与学术写作助手。解决网页版 AI 无法一次性处理大量文献的痛点, 支持多模型长上下文, 所有数据本地存储, 绝对私密。

---

## 版本基线对照

| 模块 | v1.0.1 现状 | v1.1.0 变更 |
|------|------------|-------------|
| 分组概念 | `batches` 表 + `batch_id` | 重命名为 `projects` 表 + `project_id`，增加 `is_default` |
| 删除功能 | API 有 `DELETE /{id}`，前端无入口 | 前端增加单篇/批量删除 + 二次确认 |
| 多模型 | 已完成 Moonshot/Kimi-Coding/DeepSeek/Custom 四 Provider + UI | 仅需补充 DeepSeek Key 实测 + 质量对比 |
| 更新检测 | electron-updater 自动检查 GitHub releases.atom（404） | 修复为 GitHub API 或正确配置 electron-updater |
| Prompt | 旧字段（background/methods/key_results/conclusion） | 升级为新字段（research_question/sample_source/sample_size/key_methods/key_data/limitations） |
| 默认模型 | moonshot-v1-128k | 保持不变 |

> 标注说明：下文 `[v1.0.1 已有]` 表示当前代码已实现；`[v1.1.0 新增/变更]` 表示本版本待开发或改造项。

---

## 1. 项目定位

**核心场景**: 一次性阅读 20-50 篇文献(批量上传->项目管理->跨文献问答->论文撰写)

**目标用户**:
- 生物技术/制药行业研发人员
- 高校及科研院所研究人员
- 需要同时推进多个课题、管理多组文献的理工科背景用户

**应用形态**:
- 桌面独立应用: Windows / macOS 双平台
- 打包格式: Windows `.exe`、macOS `.dmg`
- 一键安装, 无需配置环境

**核心能力**:
- 批量上传 20-50 篇 PDF, 自动提取结构化摘要(含样本量、方法、关键数据、局限性)
- **项目管理**: 按课题/项目分组管理文献, 支持跨项目独立分析
- 跨文献综合问答(基于结构化摘要拼接, 利用长上下文模型)
- 单篇深度精读(基于原文, 连续对话, 页码定位)
- 论文分块撰写(Markdown 编辑器 + 学术润色)
- **多模型支持**: Kimi / DeepSeek / 自定义 endpoint, 用户自由切换

---

## 2. 技术架构

```
+---------------------------------------------+
|              Electron (桌面壳)                 |
|  +-------------------------------------+    |
|  |    React + TypeScript + Tailwind      |    |
|  |   项目列表 / 文献库 / PDF预览 / 聊天面板 / 编辑器  |    |
|  +-------------------------------------+    |
|              v HTTP (localhost:8000)        |
|         Python 后端进程 (FastAPI)            |
|    pdfplumber + 多Provider API + SQLite + SSE      |
+---------------------------------------------+
```

### 技术选型

| 层级 | 技术 | 选型理由 |
|------|------|----------|
| **桌面框架** | Electron | 成熟生态, 打包 exe/dmg 一条命令 |
| **UI 框架** | React 18 + TypeScript | 组件生态成熟, Cursor 生成代码质量高 |
| **UI 组件** | shadcn/ui + Tailwind CSS | 按需引入, 风格统一 |
| **PDF 预览** | react-pdf / iframe | 前端直接渲染 |
| **后端框架** | FastAPI | 异步, 自动 OpenAPI 文档, SSE 原生支持 |
| **PDF 解析** | pdfplumber + pymupdf | 文本提取, 复杂排版 fallback |
| **AI 接口** | OpenAI 兼容 SDK | 统一封装, 支持 Kimi / DeepSeek / 自定义 |
| **数据库** | SQLite | 全部本地存储, 绝对私密 |
| **ORM** | SQLAlchemy 2.0 + Alembic | 数据库迁移、类型安全 |
| **数据验证** | Pydantic v2 | 前后端共用 schema |
| **打包工具** | PyInstaller + electron-builder | 分别打包后合并 |

### 通信协议

- 前端 -> 后端: HTTP REST + Server-Sent Events (SSE)
- AI 问答使用 SSE 流式响应, 前端逐字渲染
- 文件上传: multipart/form-data, 支持批量
- 本地地址: `http://127.0.0.1:8000`, Electron 主进程自动管理后端进程生命周期

### Electron 进程管理

**启动**:
1. Electron 主进程启动
2. spawn Python 后端进程
3. 轮询 `GET /health`(最多 30 次 x 500ms)
4. 后端就绪后加载 React 前端
5. 若 15 秒未就绪, 弹窗提示"后端启动失败"

**关闭**:
1. `app.on('before-quit')` 触发
2. 向 Python 进程发送 SIGTERM, 3 秒后未退出则 SIGKILL
3. 清理临时文件

**端口冲突**: 探测 8000 端口, 被占用则 fallback 到 8001-8010, 实际端口通过 IPC 传给前端

---

## 3. 项目目录

```
research-assistant/
├── README.md
├── package.json                # Electron + 前端依赖
├── requirements.txt            # Python 依赖
│
├── backend/                    # Python 后端(FastAPI)
│   ├── main.py                 # 应用入口(含 GET /health)
│   ├── config.py               # 配置: API Key / 模型 / 路径 / 超时
│   ├── alembic.ini             # 数据库迁移
│   ├── alembic/
│   ├── api/v1/
│   │   ├── projects.py         # [v1.1.0] 项目管理(替代 batches.py)
│   │   ├── batches.py          # [v1.0.1] 已废弃, v1.1.0 路由下线
│   │   ├── batch_extract.py    # [v1.0.1] 批量提取逻辑, v1.1.0 挂到 projects 路由
│   │   ├── literature_crud.py  # 上传/解析/列表/详情/删除/标签
│   │   ├── literature_extract.py # 单篇 SSE 提取
│   │   ├── literature_chat.py  # 跨文献问答 + 单篇问答
│   │   ├── literature_translate.py # 摘要翻译
│   │   ├── chat_sessions.py    # 会话历史
│   │   ├── paper.py            # 论文撰写分块 [v1.0.1 已有 blocks]
│   │   ├── settings.py         # API Key / 模型配置 / 测试连接
│   │   └── data.py             # 数据库管理
│   ├── services/
│   │   ├── pdf_parser.py       # PDF 文本提取
│   │   ├── kimi_client.py      # [v1.0.1] OpenAI 兼容 AI 客户端
│   │   ├── api_provider.py     # [v1.0.1] 多 Provider 解析
│   │   ├── secrets.py          # [v1.0.1] Fernet + keyring 密钥管理
│   │   ├── db.py               # SQLAlchemy 引擎
│   │   └── extract_prompt.py   # Prompt 模板(v1.1.0 工程化升级)
│   ├── models/
│   │   ├── schemas.py          # Pydantic Schema
│   │   └── tables.py           # SQLAlchemy 表定义
│   └── tests/                  # 单元测试
│
├── frontend/                   # React + TypeScript
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Projects.tsx        # [v1.1.0] 项目列表/管理
│   │   │   ├── Literature.tsx      # [v1.0.1] 文献库
│   │   │   ├── PaperWrite.tsx      # [v1.0.1] 论文撰写
│   │   │   ├── ChatHistory.tsx     # [v1.0.1] 会话历史
│   │   │   └── Settings.tsx        # [v1.0.1] 设置(含多 Provider)
│   │   ├── components/
│   │   │   ├── FileUploader.tsx   # 批量上传(支持选择项目)
│   │   │   ├── LiteratureList.tsx # 文献列表(支持删除/移动项目)
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
│   ├── main.js                 # 主进程(spawn/kill/health轮询)
│   └── preload.js              # IPC 暴露
│
└── data/                       # 运行时数据(gitignore)
    ├── papers/                 # 原始 PDF
    └── research-assistant.db   # SQLite
```

---

## 4. 功能需求

### 4.1 项目管理(核心新增)

**项目 = 科研课题/研究方向**, 替代原"批次"概念。

**项目 CRUD**:
- 创建项目: 名称(1-100 字)、描述(可选)、创建时间
- 项目列表: 显示名称、文献数量、最后更新时间
- 项目详情: 进入该项目, 显示该项目的文献列表
- 编辑项目: 修改名称/描述
- 删除项目: 确认后删除, **项目内文献全部移入"未分类"(默认项目)**, 不删除文献本身
- 默认项目: "未分类"(不可删除、不可重命名)

**文献与项目关系**:
- 上传文献时, 可选择放入某个项目(默认"未分类")
- 文献列表支持按项目筛选
- 支持将文献从一个项目移动到另一个项目(单篇/批量)
- 跨文献问答支持: 1)勾选多篇(不限项目) 2)选择某个项目(自动包含该项目全部文献)

### 4.2 文献批量处理

**批量 PDF 上传**
- 支持拖拽上传和文件多选(Ctrl/Cmd + 多选)
- 单次上限 50 个文件, 单个上限 50MB
- 上传时**必须选择目标项目**(默认"未分类")
- 上传进度条, 文件类型校验仅接受 `.pdf`
- 上传后自动触发解析(可配置手动触发)

**PDF 解析与存储**
- `pdfplumber` 提取每页文本, 按页存入 `paper_pages`
- 提取失败 fallback 到 `pymupdf`
- 检测扫描版: 单页文本 < 50 字符标记 `is_scanned = true`
- 提取元数据(标题/作者/年份/期刊), 优先 PDF 元数据, 缺失时 AI 补充

**删除文献**
- 单篇删除: 文献列表每行右侧"..."菜单 -> "删除" -> 二次确认弹窗
- 批量删除: 勾选多篇 -> 顶部操作栏"删除选中" -> 二次确认弹窗
- 删除后级联清理:
  - 删除 `papers` 记录
  - 删除 `paper_pages` 关联记录
  - 删除 `extracted_data` 关联记录
  - 删除 `paper_tags` 关联记录
  - 删除本地 PDF 文件
  - 更新所属项目的 `paper_count`
- 删除不可撤销, 但删除前可导出文献信息(P2)

**结构化摘要提取(JSON Mode, 工程化 Prompt)**

调用 AI 模型, 强制输出固定格式, **禁止泛泛而谈**:

```json
{
  "title": "string",
  "authors": ["string"],
  "year": "integer",
  "journal": "string",
  "research_question": "string(该研究要回答的科学问题, 50字内)",
  "sample_source": "string(样本来源: 如人血浆外泌体、小鼠骨髓间充质干细胞)",
  "sample_size": "string(样本量, 如n=30、3个独立批次)",
  "key_methods": ["string(核心技术, 如质谱分析、流式细胞术)"],
  "key_data": ["string(核心数据点, 必须含数值, 如PC使EV摄取增加2.3倍)"],
  "conclusion": "string(150字内)",
  "limitations": ["string(研究局限性, 如仅体外实验、样本量小)"],
  "keywords": ["string"]
}
```

**提取要求**:
- 每个字段必须基于原文, 禁止编造
- `key_data` 必须包含**具体数值/指标**, 禁止"显著增加"等模糊表述
- `limitations` 必须列出**至少 1 条**真实局限
- 输出必须是合法 JSON, 不要包含 markdown 代码块标记
- 提取失败重试 3 次, 3 次失败后标记 `extract_failed`, 记录错误日志

**批量提取**:
- `POST /projects/{project_id}/batch-extract` 一键提取该项目全部 pending 文献
- 串行执行, 间隔 >= 1 秒(避免 API 限流)
- SSE 流式进度: `{type: 'progress', current, total, paper_id, status, title}`
- 支持暂停/继续(P2)

**文献库管理**
- 列表视图: 标题 / 第一作者 / 年份 / 期刊 / 提取状态 / 所属项目
- 按项目、年份、期刊、标签、提取状态筛选
- 按年份/时间/标题排序
- FTS5 全文搜索(标题 + 摘要 + 关键词)
- 标签系统: 用户自定义标签, 多标签筛选

**跨文献综合问答(工程化 Prompt)**

系统 Prompt 模板(后端拼接所选文献的结构化摘要后发送):

```
你是一位严谨的[领域]文献综述专家。以下提供了 {n} 篇文献的**结构化摘要**, 请严格基于提供的数据进行深度对比分析。

【禁止事项】
- 禁止"具有重要意义"、"为后续研究奠定基础"、"有待进一步研究"等空话
- 禁止无引用总结(每个观点必须标注 [作者 年份])
- 禁止将 A 文献的数据/结论安到 B 文献上(幻觉交叉污染)

【输出要求】(必须按以下结构输出)

### 1. 研究脉络(时间顺序)
按发表时间排列, 每篇必须标注:
- 研究目标(该文献要解决什么问题)
- 与前篇的关系(继承/反驳/扩展/无关)

### 2. 方法对比矩阵(Markdown 表格)
| 文献 | 样本来源 | 样本量 | 关键技术 | 检测指标 |
|------|---------|--------|---------|---------|
| [作者 年份] | ... | ... | ... | ... |

### 3. 结果矛盾点(必须找出)
明确指出两篇及以上文献在哪些结论上不一致:
- "[作者A 年份] 发现 X(数据: ...), 但 [作者B 年份] 发现 Y(数据: ...), 矛盾可能源于..."

### 4. 核心数据汇总
列出所有文献的关键数据点(必须含数值):
- [作者 年份]: 关键发现 + 具体数值

### 5. 研究空白(基于局限性)
基于各文献的 limitations, 指出该领域尚未回答的问题:
- "目前所有研究均为体外实验([作者A 年份], [作者B 年份]), 缺乏体内验证"

### 6. 临床/产业启示(具体、可落地)
- 具体建议, 禁止"有待进一步研究"

【文献数据】
{structured_summaries}

【用户问题】
{question}
```

**交互设计**:
- 顶部选择项目(自动包含该项目全部文献)或勾选 N 篇(不限项目)
- SSE 流式响应, 前端逐字渲染
- 支持追问, 历史保存到 `chat_sessions`
- 20 篇结构化摘要 ~= 15K-25K tokens, 远低于 256K/1M 限制

**单篇深度精读(工程化 Prompt)**

系统 Prompt:
```
你是一位专业的文献精读助手。用户正在阅读以下论文, 请基于原文回答。

【回答要求】
- 引用原文时标注页码(如"第3页提到...")
- 涉及数据时必须给出具体数值
- 如果用户问的是图表内容, 请描述图表展示的核心趋势/对比关系
- 如果问题超出原文范围, 明确说明"原文未涉及"

【论文全文】
{paper_fulltext}
```

- 左侧 PDF 预览, 右侧 ChatPanel 连续对话
- 基于原文(`paper_pages` 全文)或摘要(`extracted_data`)
- 支持"定位到页": AI 引用页码时前端可跳转

**中英互译**
- 单篇翻译全文摘要, 保留段落结构
- 结果存入 `extracted_data.translation`

**导出报告**
- 跨文献问答结果导出为 Markdown
- 包含文献列表 + 问答内容 + 时间戳

### 4.3 论文撰写辅助

**分块 Markdown 编辑器**
- 五个标签页: 摘要 / 引言 / 方法 / 结果 / 讨论
- 左侧输入, 右侧实时预览(Markdown 渲染, 无 LaTeX)
- 停止输入 3 秒后自动保存到 `paper_blocks`

**学术润色**
- 选中段落调用润色 API
- 方向: 学术化表达 / 中英互润 / 逻辑连贯性检查
- 支持接受/拒绝/对比查看

**参考文献格式化(P2)**
- 输入 DOI 或标题获取元数据, 输出 GB/T 7714 格式

### 4.4 设置与多模型支持

**API Provider 选择**
- 下拉选项: Moonshot 通用平台 / Kimi For Coding / DeepSeek / 自定义
- 选择后自动填充对应 base_url 和默认模型
- 用户可手动修改 base_url 和模型名

**Provider 配置**

| Provider | Base URL(默认) | 默认模型 | 上下文 | 特点 |
|----------|----------------|---------|--------|------|
| Moonshot 通用平台 | `https://api.moonshot.cn/v1` | `moonshot-v1-128k` | 128K | 通用, 适合大多数场景 |
| Kimi For Coding | `https://api.kimi.com/coding/v1` | `kimi-k2.6` | 256K | 仅限 Coding Agent, 科研场景可能 403 |
| DeepSeek | `https://api.deepseek.com` | `deepseek-v4-pro` | 1M | 超长上下文, 价格低, Thinking 模式 |
| 自定义 | 用户输入 | 用户输入 | 视模型 | 私有化部署 |

**模型自动推断逻辑**:
- `sk-kimi-` 开头 -> 自动推断为 `kimi-coding`, base_url 指向 `api.kimi.com`
- `sk-` 开头(非 kimi) -> 自动推断为 `moonshot`, base_url 指向 `api.moonshot.cn`
- DeepSeek Key 也是 `sk-` 开头, **无法自动推断**, 必须用户手动选择 Provider
- 用户手动选择 Provider 时, base_url 和模型按上表自动填充, 但允许修改

**API Key 测试连接**
- 测试时根据当前 Provider 和 base_url 发送测试请求
- 返回结果中携带实际使用的 `provider` 和 `base_url`
- 错误分类:
  - 401/403 -> "API Key 无效或已过期"
  - 404 + "Not found the model" -> "当前账号无权使用模型 [model], 请更换模型后重试"
  - 429 -> "请求过于频繁, 请稍后重试"
  - 其他 -> 显示具体错误信息

**设置页其他配置**
- temperature、max_tokens、timeout
- 主题(light/dark/system)
- 数据管理: 数据库大小、导出/重置数据库

### 4.5 更新检测(修复)

**当前实现**: `electron-updater`（`electron/main.js` + `autoUpdater`），由 Electron 主进程检查 GitHub Release。

**问题**: `releases.atom` 返回 404，可能因 `package.json` 中 `build.publish` 的 `owner`/`repo` 配置错误或尚未发布 Release。

**修复方案**:
- 检查 `package.json` → `build.publish`，确认 `owner`/`repo` 指向正确的 GitHub 仓库
- 在 GitHub 创建至少一个 Release（含安装包或 `latest.yml`）
- 备选：改为调用 `https://api.github.com/repos/{owner}/{repo}/releases/latest` 获取版本信息

**前端行为**: 发现新版本时提示「前往下载」，**不自动安装**（关闭 `autoUpdater` 的静默安装或仅展示下载链接）。

---

## 5. 数据库设计

### 5.1 表结构

#### `projects` -- 项目(替代原 batches)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| name | VARCHAR(100) | 项目名称 |
| description | TEXT | 可选描述 |
| paper_count | INTEGER | 文献数量(冗余, 维护见规则) |
| is_default | BOOLEAN | 是否为默认"未分类"项目 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 最后更新时间 |

**paper_count 维护**:
- 上传文献到项目时 +1
- 从项目移出/删除文献时 -1
- 清空项目时设为 0
- 事务保证

#### `papers` -- 文献元数据
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| file_path | VARCHAR | 本地 PDF 路径 |
| file_size | INTEGER | 文件大小(字节) |
| page_count | INTEGER | 页数 |
| title | VARCHAR | 标题 |
| authors | JSON | 作者列表 |
| year | INTEGER | 发表年份 |
| journal | VARCHAR | 期刊名 |
| doi | VARCHAR | DOI |
| status | ENUM | `pending` / `extracting` / `completed` / `failed` / `extract_failed` |
| project_id | UUID FK | 关联 projects(默认指向"未分类") |
| is_scanned | BOOLEAN | 是否扫描版 |
| created_at | DATETIME | 上传时间 |
| extraction_attempts | INTEGER | 提取尝试次数(默认 0) |
| last_error | TEXT | 最后一次提取错误信息 |
| extracted_at | DATETIME | 最后一次提取尝试时间 |
| updated_at | DATETIME | 更新时间 |

#### `paper_pages` -- 按页原文
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| paper_id | UUID FK | 关联 papers |
| page_number | INTEGER | 页码(从 1 开始) |
| text_content | TEXT | 该页提取的文本 |
| char_count | INTEGER | 该页字符数 |

#### `extracted_data` -- 结构化摘要
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| paper_id | UUID FK | 关联 papers(UNIQUE) |
| research_question | TEXT | 研究问题 |
| sample_source | TEXT | 样本来源 |
| sample_size | TEXT | 样本量 |
| key_methods | JSON | 核心技术列表 |
| key_data | JSON | 核心数据点列表(必须含数值) |
| background | TEXT | 研究背景 |
| methods | TEXT | 研究方法 |
| key_results | JSON | 核心结果列表 |
| conclusion | TEXT | 结论 |
| limitations | JSON | 局限性列表 |
| keywords | JSON | 关键词列表 |
| raw_json | JSON | API 返回的原始 JSON(备份) |
| translation | TEXT | 中文翻译 |
| extracted_at | DATETIME | 提取时间 |

#### `paper_blocks` -- 论文撰写分块
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| block_name | VARCHAR(20) | `abstract` / `introduction` / `methods` / `results` / `discussion` |
| content | TEXT | Markdown 内容 |
| updated_at | DATETIME | 最后更新时间 |
| UNIQUE(block_name) | -- | MVP 单用户单论文假设 |

#### `paper_tags` -- 标签关联表
| 字段 | 类型 | 说明 |
|------|------|------|
| paper_id | UUID FK | 关联 papers |
| tag | VARCHAR(50) | 标签名 |
| PRIMARY KEY (paper_id, tag) | -- | 联合主键 |

#### `chat_sessions` -- 对话会话
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| session_type | ENUM | `literature_multi` / `literature_single` / `paper_polish` |
| paper_ids | JSON | 关联文献 ID 列表 |
| project_id | UUID FK | 关联 projects(跨项目问答时可为 NULL) |
| primary_paper_id | UUID FK | 单篇场景主文献 ID |
| title | VARCHAR | 会话标题 |
| messages | JSON | 对话历史(OpenAI 消息格式) |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 最后更新时间 |

#### `paper_audit_logs` -- 调试日志(可选)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| paper_id | UUID FK | 关联 papers(可为 NULL) |
| action | VARCHAR(50) | 操作类型 |
| detail | JSON | 详情 |
| created_at | DATETIME | 时间 |

#### `settings` -- 应用配置
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 固定为 1 |
| api_key_encrypted | BLOB | 加密后的 API Key(Fernet + keyring) |
| api_provider | VARCHAR | `auto` / `moonshot` / `kimi-coding` / `deepseek` / `custom` |
| api_base_url | VARCHAR | 实际请求的 endpoint |
| default_model | VARCHAR | 默认模型名 |
| temperature | FLOAT | 默认温度 |
| max_tokens | INTEGER | 默认最大 tokens |
| theme | VARCHAR | 主题(light/dark/system) |
| updated_at | DATETIME | 更新时间 |

### 5.2 FTS5 全文搜索

```sql
-- v1.0.1 实际实现：触发器同步（非 content= 外部内容表模式）
CREATE VIRTUAL TABLE papers_fts USING fts5(
    title, authors, journal, keywords, background, methods, conclusion
);
```

- FTS5 默认启用, 所有规模统一使用
- 通过 6 个触发器保持 `papers` + `extracted_data` 与 `papers_fts` 同步（见 `data.py` `_init_fts5()`）

### 5.3 约束与索引
- `paper_pages.paper_id` + `page_number`: 联合唯一
- `papers`: `title`、`year`、`status`、`project_id` 索引
- `extracted_data.paper_id`: 唯一
- `chat_sessions.primary_paper_id`: 索引
- `paper_tags.tag`: 索引
- 外键: ON DELETE CASCADE(删除文献时级联删除 pages、extracted_data、paper_tags)

### 5.4 数据迁移方案（v1.0.1 -> v1.1.0）

**迁移 1：batches -> projects**
- Alembic revision: 重命名表 `batches` -> `projects`
- 增加列 `is_default` (BOOLEAN, default false)
- 插入默认项目「未分类」(`is_default=true`)
- 将 `papers.batch_id IS NULL` 的文献指向默认项目
- 重命名 `papers.batch_id` -> `papers.project_id`（外键指向 `projects.id`）
- 原 `batches` 数据保留，名称变为项目名

**迁移 2：extracted_data 字段扩展**
- Alembic revision: 增加列：
  - `research_question` (TEXT)
  - `sample_source` (TEXT)
  - `sample_size` (TEXT)
  - `key_methods` (JSON)
  - `key_data` (JSON)
  - `limitations` (JSON)
- 保留旧列（background, methods, key_results, conclusion）用于兼容
- 新提取的文献写入新字段，旧文献在下次重新提取时更新
- `raw_json` 列保留原始 API 返回，作为备份

**迁移 3：settings 表扩展**
- **已于 v1.0.1 完成**（revision `a1b2c3d4e5f6`）：`api_provider`、`api_base_url`
- v1.1.0 无需重复迁移；新库默认值：`api_provider='auto'`, `api_base_url='https://api.moonshot.cn/v1'`

---

## 6. API 接口

### 6.1 健康检查 [v1.0.1 已有]
| 方法 | 路径 | 说明 | 响应 |
|------|------|------|------|
| GET | `/health` | 健康检查 | `{"status": "ok", "version": config.VERSION}` |

### 6.2 项目模块 (`/api/v1/projects`) [v1.1.0 新增，替代 `/api/v1/batches`]
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/` | 创建项目 | `{"name": "string(1-100)", "description?": "string"}` | `{"id", "name", "created_at"}` |
| GET | `/` | 获取项目列表 | query: page, page_size | `{"items": [{id, name, paper_count, updated_at}], total, page}` |
| GET | `/{id}` | 获取项目详情(含文献) | - | `{"id", "name", "papers": [...]}` |
| PUT | `/{id}` | 更新项目 | `{"name?", "description?"}` | `{"id", "name"}` |
| DELETE | `/{id}` | 删除项目(文献移入"未分类") | - | `{"success", "moved_count"}` |
| POST | `/{id}/batch-extract` | 一键提取该项目全部 pending | - | SSE 流 |
| POST | `/{id}/move-papers` | 批量移动文献到本项目 | `{"paper_ids": ["uuid"]}` | `{"success", "moved_count"}` |

### 6.3 文献 CRUD (`/api/v1/literature`) [v1.0.1 已有，v1.1.0 增量：project_id 筛选、批量删除、移动项目]

> v1.0.1 已有：`GET /{id}/file`（PDF 二进制下载），未在下表重复列出。
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/upload` | 批量上传 PDF | multipart: files[], project_id? | `{"uploaded": [{id, title, status}]}` |
| POST | `/{id}/parse` | 手动触发解析 | - | `{"paper_id", "page_count", "status"}` |
| GET | `/` | 获取文献列表 | query: search, tag, year, status, project_id, sort, page | `{"items": [{id, title, authors, year, status, project_name}], total, page}` |
| GET | `/{id}` | 获取单篇详情 | - | PaperDetail + pages[] + extracted_data |
| GET | `/{id}/pages` | 批量获取全部页面 | - | `{"pages": [...]}` |
| GET | `/{id}/page/{page_num}` | 获取单页原文 | - | `{"text_content"}` |
| PUT | `/{id}/tags` | 更新标签 | `{"tags": ["string"]}` | `{"id", "tags"}` |
| PUT | `/{id}/project` | 移动文献到指定项目 | `{"project_id": "uuid"}` | `{"id", "project_id", "project_name"}` |
| DELETE | `/{id}` | 删除文献(级联清理) | - | `{"success"}` |
| POST | `/batch-delete` | 批量删除文献 | `{"paper_ids": ["uuid"]}` | `{"success", "deleted_count"}` |
| GET | `/tags` | 获取所有标签汇总 | - | `{"tags": [{tag, count}]}` |
| GET | `/stats` | 文献统计 | - | `{"total", "completed", "pending", "failed", "extract_failed", "by_project": [...]}` |
| POST | `/{id}/extract` | 手动触发摘要提取 | - | SSE 流 |
| POST | `/{id}/translate` | 翻译摘要 | - | `{"translation"}` |

### 6.4 文献问答 (`/api/v1/literature`) [v1.0.1 已有，v1.1.0：`batch_id` 改为 `project_id`]
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/chat` | 跨文献问答 | `{"paper_ids[]?", "project_id?", "question", "session_id?"}` | SSE 流。`project_id` 与 `paper_ids` 二选一, project_id 自动展开为该项目全部文献 |
| POST | `/{id}/chat` | 单篇精读问答 | `{"question", "session_id?", "use_fulltext?"}` | SSE 流。`use_fulltext=true` 时调取全文, false 时仅用摘要, 默认 false |

### 6.5 会话历史 (`/api/v1/chat-sessions`) [v1.0.1 已有]
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/` | 获取会话列表 | query: type, page | `{"items": [{id, title, session_type, created_at}], total, page}` |
| GET | `/{id}` | 获取会话详情 | - | `{"id", "title", "messages", "created_at"}` |
| DELETE | `/{id}` | 删除会话 | - | `{"success"}` |

### 6.6 论文撰写 (`/api/v1/paper`) [v1.0.1 已有 blocks；polish/citation 为 v1.1.0/P2]
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/blocks` | 获取五个分块 | - | `{"abstract", "introduction", "methods", "results", "discussion"}` |
| PUT | `/blocks/{block_name}` | 保存分块 | `{"content": "string"}` | `{"block_name", "updated_at"}` |
| POST | `/polish` | 润色段落 | `{"text", "direction"}` | `{"polished_text", "diff?"}` |
| POST | `/citation` | 格式化参考文献 | `{"doi?" or "title?"}` | `{"citation_gb7714"}` |

### 6.7 设置 (`/api/v1/settings`) [v1.0.1 已有，含多 Provider]
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/` | 获取配置 | - | Settings(api_key 脱敏) |
| PUT | `/` | 更新配置 | `{"api_key?", "api_provider?", "api_base_url?", "default_model?", "temperature?", "max_tokens?"}` | Settings |
| POST | `/test` | 测试 API Key | - | `{"valid", "provider", "base_url", "message?"}` |

**API Key 存储**:
- 加密密钥: Python `keyring` 库存系统 keychain(Windows Credential Manager / macOS Keychain)
- 密文: Fernet 加密后的 API Key 存 SQLite
- 首次设置: 前端 HTTP -> 后端从 keychain 读取/生成密钥 -> 加密 -> 存 SQLite
- 后续启动: 后端从 keychain 读取密钥 -> 解密 -> 使用
- SQLite 文件泄露也无法解密, 没有系统 keychain 中的密钥

### 6.8 更新检测 [删除后端 `/api/v1/update`，改为 electron-updater 配置]

不新增后端 REST 端点。更新逻辑由 **Electron 主进程** `electron-updater` 完成；修复重点为 `package.json` → `build.publish` 与 GitHub Release 配置（见 §4.5）。

### 6.9 数据管理 (`/api/v1/data`) [v1.0.1 已有]
> **仅限 localhost 访问**, 拒绝远程请求。

| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/db-stats` | 数据库统计 | - | `{"db_size", "table_counts"}` |
| POST | `/export-db` | 导出数据库 | - | File download |
| POST | `/reset-db` | 重置数据库(需二次确认) | `{"confirm": true}` | `{"success"}` |

---

## 7. AI 客户端与模型配置

### 7.1 统一 AI 客户端

后端使用 OpenAI 兼容 SDK, 通过 `base_url` 和 `api_key` 区分不同 Provider:

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key=settings.api_key,
    base_url=settings.api_base_url,  # 从 settings 读取, 不再硬编码
)
```

**所有调用点统一使用上述客户端**, 包括:
- `test_api_key()` -- 测试连接
- `extract_paper()` -- 结构化摘要提取
- `chat_literature()` -- 跨文献/单篇问答
- `polish_text()` -- 学术润色

### 7.2 Provider 配置

```python
# backend/config.py
VERSION = "1.1.0"  # 打包发布时 bump，当前开发基线 1.0.1

# Provider 默认配置
PROVIDER_CONFIGS = {
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-128k",
        "available_models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "moonshot-v1-auto"],
    },
    "kimi-coding": {
        "base_url": "https://api.kimi.com/coding/v1",
        "default_model": "kimi-k2.6",
        "available_models": ["kimi-k2.5", "kimi-k2.6"],
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-pro",
        "available_models": ["deepseek-v4-pro", "deepseek-v4-flash"],
    },
    "custom": {
        "base_url": "",  # 用户输入
        "default_model": "",  # 用户输入
        "available_models": [],  # 用户输入
    },
}

# 全局默认
DEFAULT_PROVIDER = "moonshot"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 8192
REQUEST_TIMEOUT = 120
BATCH_EXTRACT_CONCURRENCY = 1  # MVP 默认串行, 未来可调
```

### 7.3 模型自动推断

```python
def infer_provider(api_key: str) -> tuple[str, str]:
    """根据 Key 前缀推断 Provider, 返回 (provider, base_url)"""
    if api_key.startswith("sk-kimi-"):
        return "kimi-coding", PROVIDER_CONFIGS["kimi-coding"]["base_url"]
    elif api_key.startswith("sk-"):
        # 注意: sk- 开头可能是 Moonshot 或 DeepSeek, 无法区分
        # 默认返回 moonshot, 用户可手动切换
        return "moonshot", PROVIDER_CONFIGS["moonshot"]["base_url"]
    else:
        return "custom", ""
```

**规则**:
- `api_provider = "auto"` 时, 每次使用 Key 都重新执行 `infer_provider()`
- `api_provider = "moonshot" / "kimi-coding" / "deepseek" / "custom"` 时, 固定使用对应配置, 不自动推断
- `api_base_url` 始终可手动覆盖, 优先级最高

### 7.4 测试连接逻辑

```python
async def test_api_key(settings: Settings) -> dict:
    provider = settings.api_provider
    base_url = settings.api_base_url
    model = settings.default_model
    api_key = settings.api_key

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
        )
        return {
            "valid": True,
            "provider": provider,
            "base_url": base_url,
            "model": model,
        }
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            message = "API Key 无效或已过期"
        elif "404" in error_msg and "Not found the model" in error_msg:
            message = f"当前账号无权使用模型 [{model}], 请更换模型后重试"
        elif "429" in error_msg:
            message = "请求过于频繁, 请稍后重试"
        else:
            message = f"连接失败: {error_msg}"

        return {
            "valid": False,
            "provider": provider,
            "base_url": base_url,
            "message": message,
        }
```

---

## 8. Prompt 工程化(v1.1.0 核心升级)

### 8.1 结构化提取 Prompt

```
你是一位专业的科研文献分析助手。请仔细阅读以下论文全文, 提取关键信息并以 JSON 格式返回。

【字段要求】(必须全部填写, 缺失时返回空字符串/空数组, 禁止编造)

1. title: 论文标题
2. authors: 作者列表(数组)
3. year: 发表年份(整数)
4. journal: 期刊名
5. research_question: 该研究要回答的科学问题(50字内)
6. sample_source: 样本来源(如'人血浆外泌体'、'小鼠骨髓间充质干细胞')
7. sample_size: 样本量(如'n=30'、'3个独立批次')
8. key_methods: 核心技术列表(如['质谱分析', '流式细胞术'])
9. key_data: 核心数据点列表(必须含具体数值, 如'PC使EV摄取增加2.3倍(p<0.01)')
10. conclusion: 结论(150字内)
11. limitations: 研究局限性列表(至少1条, 如['仅体外实验', '样本量小(n=5)'])
12. keywords: 关键词列表(5-8个)

【质量要求】
- key_data 必须包含具体数值/指标, 禁止'显著增加'、'明显降低'等模糊表述
- limitations 必须基于原文真实局限, 禁止编造
- 输出必须是合法 JSON, 不要包含 markdown 代码块标记

论文全文:
{paper_text}
```

### 8.2 跨文献问答 Prompt

```
你是一位严谨的[领域]文献综述专家。以下提供了 {n} 篇文献的**结构化摘要**, 请严格基于提供的数据进行深度对比分析。

【禁止事项】
- 禁止'具有重要意义'、'为后续研究奠定基础'、'有待进一步研究'等空话
- 禁止无引用总结(每个观点必须标注 [作者 年份])
- 禁止将 A 文献的数据/结论安到 B 文献上(幻觉交叉污染)

【输出要求】(必须按以下结构输出)

### 1. 研究脉络(时间顺序)
按发表时间排列, 每篇必须标注:
- 研究目标(该文献要解决什么问题)
- 与前篇的关系(继承/反驳/扩展/无关)

### 2. 方法对比矩阵(Markdown 表格)
| 文献 | 样本来源 | 样本量 | 关键技术 | 检测指标 |
|------|---------|--------|---------|---------|
| [作者 年份] | ... | ... | ... | ... |

### 3. 结果矛盾点(必须找出)
明确指出两篇及以上文献在哪些结论上不一致:
- '[作者A 年份] 发现 X(数据: ...), 但 [作者B 年份] 发现 Y(数据: ...), 矛盾可能源于...'

### 4. 核心数据汇总
列出所有文献的关键数据点(必须含数值):
- [作者 年份]: 关键发现 + 具体数值

### 5. 研究空白(基于局限性)
基于各文献的 limitations, 指出该领域尚未回答的问题:
- '目前所有研究均为体外实验([作者A 年份], [作者B 年份]), 缺乏体内验证'

### 6. 临床/产业启示(具体、可落地)
- 具体建议, 禁止'有待进一步研究'

【文献数据】
{structured_summaries}

【用户问题】
{question}
```

### 8.3 单篇精读 Prompt

```
你是一位专业的文献精读助手。用户正在阅读以下论文, 请基于原文回答。

【回答要求】
- 引用原文时标注页码(如'第3页提到...')
- 涉及数据时必须给出具体数值
- 如果用户问的是图表内容, 请描述图表展示的核心趋势/对比关系
- 如果问题超出原文范围, 明确说明'原文未涉及'

【论文全文】
{paper_fulltext}
```

### 8.4 学术润色 Prompt

```
你是一位学术写作专家。请对以下段落进行润色, 方向: {direction}。

【润色方向】
- academic: 学术化表达(去除口语化, 使用专业术语)
- bilingual: 中英互润(保持学术准确性)
- logic: 逻辑连贯性(检查段落衔接、论证链条)

【要求】
- 保持原意不变
- 只修改表达, 不添加原文没有的观点
- 输出修改后的完整段落
- 如有修改, 用【】标注修改处并简要说明原因

原文:
{text}
```

---

## 9. SSE 流式响应

### 9.1 后端 SSE 规范
- Content-Type: `text/event-stream`
- 消息格式: `data: {"type": "chunk", "content": "..."}\n\n`
- 进度事件(批量提取): `data: {"type": "progress", "current": 3, "total": 50, "paper_id": "...", "status": "extracting", "title": "..."}\n\n`
- 结束: `data: {"type": "done"}\n\n`
- 错误: `data: {"type": "error", "message": "..."}\n\n`

### 9.2 前端 useSSE Hook
使用 `fetch + ReadableStream`(EventSource 不支持 POST 请求体):

```typescript
// 实现要点:
// 1. fetch POST 请求, 获取 response.body ReadableStream
// 2. TextDecoder 逐块解码, 按 "\n\n" 分割 SSE 事件
// 3. 解析每行 "data: {...}" 格式, 提取 JSON
// 4. 事件分发: type='chunk'/'progress' -> 累加文本; type='done' -> 结束; type='error' -> 终止
// 5. 断线检测: reader.read() 抛异常时触发重连
// 6. 重连: 最多 3 次, 间隔 1s/2s/4s（仅网络错误；HTTP 4xx/5xx 不重连, disableRetry 选项）
// 7. 组件卸载时 abortController.abort() 关闭连接
// 8. 禁止并发 SSE 流（per-url Lock）
// 9. 批量提取场景: progress 事件更新进度条(current/total)
//
// P2 增强（未实现）: seq 序号去重、last_seq 断点续传
```

---

## 10. 开发规范

### 开发原则
1. **先查后改**: 新模块、重构、Bug 修复先排查根因, 再动手
2. **先后端再前端**: 后端接口契约(OpenAPI 文档)确认后, 前端才能动工
3. **独立模块**: 新模块独立路由/独立文件, 禁止塞进已有文件
4. **字段前瞻性**: DB 建模和 API 设计提前布局未来字段
5. **代码清理**: 旧逻辑直接删除, 无需标记 DEPRECATED
6. **Git 提交**: 验证完成后再统一提交
7. **模块分工**: Cursor 负责后端重构/新建模块/数据库迁移; CodeBuddy 负责前端主力及小后端改动
8. **路由注册顺序**: FastAPI 固定路径(如 `POST /chat`)必须在动态路径(如 `POST /{id}/chat`)之前注册

### 安全注意事项
- API Key 通过 `keyring` 加密存储, 不硬编码
- 本地 SQLite 数据文件仅当前用户可访问
- 网络请求仅限 localhost, 不暴露外部端口
- 敏感信息绝不输入 AI 上下文

---

## 11. 开发阶段(v1.1.0)

### Step 1: 项目管理 + 删除功能(后端)
**目标**: 实现 projects 模块, 替代原 batches

**交付物**:
- [ ] 数据库迁移: batches 表 -> projects 表(增加 is_default 字段)
- [ ] `POST /api/v1/projects` -- 创建项目
- [ ] `GET /api/v1/projects` -- 项目列表
- [ ] `GET /api/v1/projects/{id}` -- 项目详情(含文献)
- [ ] `PUT /api/v1/projects/{id}` -- 更新项目
- [ ] `DELETE /api/v1/projects/{id}` -- 删除项目(文献移入未分类)
- [ ] `POST /api/v1/projects/{id}/move-papers` -- 批量移动文献
- [ ] 修改 `POST /upload`: 支持 project_id 参数
- [ ] 修改 `GET /literature`: 支持 project_id 筛选
- [ ] 修改 `DELETE /literature/{id}`: 级联删除(PDF 文件 + DB 记录)
- [ ] `POST /literature/batch-delete`: 批量删除
- [ ] pytest 单元测试

**验收**: Postman 完成项目 CRUD + 文献移动 + 删除级联验证

### Step 2: 项目管理 + 删除功能(前端)
**目标**: 实现 Projects 页面和文献删除入口

**交付物**:
- [ ] Projects.tsx: 项目列表/创建/编辑/删除
- [ ] LiteratureList.tsx: 增加项目筛选、删除按钮(单篇/批量)
- [ ] FileUploader.tsx: 上传时选择目标项目
- [ ] 二次确认弹窗(删除项目/删除文献)
- [ ] 移动端适配(P2)

**验收**: 创建项目 -> 上传文献到项目 -> 移动文献 -> 删除文献 -> 级联清理验证

### Step 3: DeepSeek 实测 + 质量对比（已完成：UI + 后端配置）
**目标**: 用真实 DeepSeek Key 验证全链路，对比 Moonshot 128K 质量

**已完成（v1.0.1）**:
- [x] 后端 `PROVIDER_DEEPSEEK`、`api_provider.py`
- [x] 前端 Settings 下拉、base_url / 模型自动填充
- [x] 默认模型 `moonshot-v1-128k`

**待完成**:
- [ ] 申请 DeepSeek API Key（用户侧）
- [ ] DeepSeek Key 填入后测试连接
- [ ] 同一篇文献用 Moonshot 128K vs DeepSeek 1M 提取，对比质量

**验收**: DeepSeek 全链路通过，输出质量不低于 Moonshot

### Step 4: Prompt 工程化升级
**目标**: 替换所有 Prompt 为工程化版本

**交付物**:
- [ ] 替换 `extract_prompt.py`: 强制字段精度(样本量、关键数据、局限性)
- [ ] 替换跨文献问答 Prompt: 强制矩阵输出、矛盾点识别、数据引用
- [ ] 替换单篇精读 Prompt: 页码定位、方法复现步骤
- [ ] 替换学术润色 Prompt: 方向选择、修改标注
- [ ] A/B 测试: 同一组文献, 旧 Prompt vs 新 Prompt, 对比输出质量

**验收**: 新 Prompt 输出不再"敷衍", 有具体数据、有矛盾点、有矩阵表格

### Step 5: 更新检测修复
**目标**: 修复 electron-updater / GitHub Release 404

**交付物**:
- [ ] 检查并修正 `package.json` → `build.publish`（owner/repo）
- [ ] 在 GitHub 发布 Release（含 `latest.yml` 或安装包）
- [ ] 备选：主进程改用 GitHub API 获取最新版本
- [ ] Settings 页：有新版本时提示「前往下载」，不自动安装

**验收**: 检查更新返回正确版本信息，无 404

### Step 6: 打包与发布
**目标**: 生成 v1.1.0 安装包, 准备 GitHub 开源

**交付物**:
- [ ] PyInstaller 打包后端
- [ ] electron-builder 打包前端
- [ ] 版本号 bump 到 1.1.0
- [ ] README.md 更新: 功能介绍、安装说明、多模型配置、项目/分组管理
- [ ] CHANGELOG.md: v1.0.1 -> v1.1.0 变更记录
- [ ] LICENSE: MIT 或 Apache-2.0

**验收**: 安装包可正常安装/启动/使用, GitHub Release 发布

---

## 12. 已知风险

| 风险 | 影响 | 应对 |
|------|------|------|
| Kimi API 限流(批量提取) | 高 | 串行 + 1秒间隔 + 重试; Coding Plan 用户限额较高 |
| DeepSeek API 稳定性 | 中 | 备用 Moonshot 128K, 用户可切换 |
| 大 PDF 解析超时(>50MB 扫描版) | 中 | 文件上限 50MB; 扫描版标记后跳过 AI 提取 |
| Electron 打包体积大 | 低 | 预期 150-200MB, 可接受 |
| Windows Defender 误杀 | 中 | 首次启动可能触发 SmartScreen, README 说明 |
| 模型迭代适配 | 低 | 模型名配置化, 升级只改 config.py 一行 |
| SSE 断线 | 中 | useSSE.ts 内置断线重连, 最多 3 次 |
| 孤儿进程残留 | 高 | SIGTERM + SIGKILL 双保险 |
| 多项目数据复杂度 | 中 | 删除项目时文献移入未分类, 不级联删除文献 |

---

## 13. 验收标准

### 项目管理
- [ ] 创建 3 个项目, 分别上传文献
- [ ] 项目间移动文献, paper_count 正确更新
- [ ] 删除项目, 文献移入"未分类", 不丢失
- [ ] 按项目筛选文献, 跨项目问答正常

### 文献助手
- [ ] 批量上传 30 篇 PDF, 全部正确解析
- [ ] 30 篇结构化摘要提取完成, JSON 正确(含 sample_size、key_data、limitations)
- [ ] 跨文献问答: 选择 10 篇提问, 输出含方法对比矩阵、矛盾点、数据引用
- [ ] 单篇精读: PDF 预览 + 连续对话, AI 引用页码和具体数值
- [ ] 删除文献: 单篇删除 + 批量删除, 级联清理正确
- [ ] 翻译: 英文文献一键翻译, 保留段落结构
- [ ] 会话历史: 可查看、继续、删除

### 论文撰写
- [ ] 五个分块正常输入、预览、保存
- [ ] 润色: 学术化改写版本, 标注修改处
- [ ] 自动保存: 停止输入 3 秒后保存

### 多模型支持
- [ ] Moonshot 128K: 测试连接通过, 提取/问答正常
- [ ] DeepSeek V4 Pro: 测试连接通过, 提取/问答正常, 输出质量对比
- [ ] Provider 切换: base_url 和模型自动填充, 可手动修改

### 通用
- [ ] Windows 打包为 `.exe`, 双击启动
- [ ] API Key 配置并持久化(加密存储)
- [ ] 更新检测: 正常返回版本信息, 无 404
- [ ] 网络异常友好提示, 不崩溃
- [ ] 关闭后无 Python 孤儿进程
