# ResearchAssistant SPEC（目标架构 · v1.3.0）

> 一个面向生物医药研发人员的**本地私密文献二次分析与研发立项工作台**。起点是用户已搜集好的一包文献(≤50 篇), 终点是用户署名的研发方向与立项材料; 中间每一步的判断权都在人手里。所有数据本地存储, 绝对私密。

---

## 关于本文档

本 SPEC 是**当前目标架构的稳定快照**, 描述系统"应该是什么样", 而非"某个版本改了什么"。

- **版本历史 / 迁移记录 / 每日决策** 不进本文档, 归 `CHANGELOG.md` 与 `项目日志.md`。
- **架构级决策**（改动成本高、多模块依赖）记录在"核心架构决策（ADR）"一节。
- **实现细节**（库选型、内部抽象命名、计数维护机制等）不进本文档, 留给代码与 code review。
- 已落地的实现进度以 `项目日志.md` 的里程碑表为准; 本文档不再用 `[已有]` / `[新增]` 标注, 一律按目标态描述。

> 写作判据: 只有"改起来很贵、且多个模块都依赖"的决策才写进 SPEC。能在一次 code review 里改掉的实现细节不写。

---

## 1. 项目定位

**核心场景**: 对一包已搜集的领域文献(≤50 篇)做二次分析——批量上传 → 项目管理 → 结构化精读 → 机会矩阵与信号发现 → 立项材料导出

**目标用户**:
- 生物技术/制药行业研发人员
- 高校及科研院所研究人员
- 需要同时推进多个课题、管理多组文献的理工科背景用户

**应用形态**:
- 桌面独立应用: Windows / macOS 双平台
- 打包格式: Windows `.exe`、macOS `.dmg`
- 一键安装, 无需配置环境

**核心能力**:
- 批量上传 ≤50 篇 PDF, 自动提取结构化摘要与**原子论断**(含样本量、方法、关键数据、局限性、带出处的可比对论断)
- **项目管理**: 按课题/项目分组管理文献, 支持跨项目独立分析
- **机会矩阵与信号发现**: 把文献铺成"论文 × 维度"矩阵, 自动surface机会信号(局限聚类 / 矛盾点 / 稀疏格 / 方法迁移), 每条可追溯、由人裁决(详见"产品定位"节与 ADR-6)
- 单篇深度精读(整篇全文入上下文, 连续对话, 页码定位)
- **立项材料导出**: 把人在矩阵上做出的判断与证据链, 投影为 proposal / 可行性计划 / proposal 性质 PPT / 数据表
- **多模型支持**: Kimi / DeepSeek / 自定义 endpoint, 用户自由切换

---

## 产品定位与机会发现哲学

> 本节是定位真相源, 凌驾于功能之上。任何功能取舍, 先回到本节判断"是否服务于这个定位"。

### 一句话定位

**一个本地私密的研发立项工作台——把你已经攒下的一摞文献, 变成一张你和 AI 共建的机会矩阵, 再把你在矩阵上做出的判断, 导出成能直接拿去立项的 proposal。起点是文献包, 终点是你署名的研发方向, 中间每一步的决策权都在你手里。**

### 边界: 明确不做什么

定位的一半是克制。下列均为**非目标**, 不在任何版本规划内:
- **不做学术检索 / 文献发现**。起点是用户已搜集好的闭合语料; 检索/推荐由用户的现有工具(Semantic Scholar、Elicit 等)完成。这也是隐私故事的前提。
- **不做参考文献管理器、不做成稿论文写作器**。输出聚焦"立项材料"(forward-looking), 而非"成稿论文"(backward-looking, 且赛道拥挤)。
- **不做分子建模 / 靶点预测 / de novo 设计**。那是计算发现层, 是另一个资本密集的赛道; 本产品处在其上游——人的思路与规划层。
- **不做 agentic"自动研究"**。见下文"哲学"。

### 哲学: 慢下来, 凸显人的决策

整个 AI 文献工具市场在往"自动化、几秒出综述、一键成稿"狂奔。本产品反向定位: **不追求自动化, 而是在判断节点上刻意放慢, 让人的决策成为产品本身。**

- **苦力活照样快**: 抽取、解析等机械工作仍让 AI 高速完成, "慢"只发生在判断节点。卖点不是"慢", 是"在该较真处帮我较真, 在不该浪费时间处别烦我"。
- **AI 提议, 人裁决**: 机会信号尤其危险——AI 极易生成"听起来对、其实是幻觉"的机会, 在生物医药里代价高昂。因此 AI **绝不**断言"这是一个新颖机会", 只能把**候选信号连同其在语料中的证据**摆出来, 由人判定真伪。产品的尊严在于它**拒绝**"魔法按钮"。
- **可见胜过自动**: 闭合语料天生有盲区(机会可能已被语料外的文献填补, 或因失败而无人发表)。产品对此**保持诚实**而非佯装全知。可追溯、可下钻、不静默吞掉任何东西——这是比"帮你找全"更经得起推敲的承诺。

### 机会信号(产品含金量所在)

机会发现不是让 AI"创造"机会, 而是**聚合人本来就会找、但靠人脑又慢又易漏的信号, 且每条可追溯回具体文献**。核心信号:
- **反复出现的局限性**: 多篇在 `limitations` 里承认同一短板 = 未满足需求。最不易幻觉(只是汇总作者亲口承认的话), 优先级最高。
- **矛盾点**: 两篇结论相反且各有数据 = 未决问题 = 高价值实验位置(技术最难, 详见独立功能设计文档)。
- **稀疏格 vs 拥挤格**: 矩阵中被反复做(红海) vs 几乎空白(候选白空间)的格子。空格是提示而非结论, 由人判断是机会还是死路。
- **方法迁移**: 方法 M 在问题 A 上有效, 而问题 B 有个 M 也许能解的局限——语料中没人这么做过即候选点子。

> 各信号的内部流水线(召回/裁决/UI/召回诚实度)属实现方案, 不写入本 SPEC, 见独立的《详细功能设计》文档。本 SPEC 仅锁定信号的**架构模式**(ADR-6)与其**数据地基**(§5.1 `claims` 表)。

---

## 核心架构决策（ADR）

> 本节是全项目的决策真相源。下列每条都满足"改动成本高、多模块依赖"的标准, 任何代码实现都不得与之冲突; 如需推翻, 先改本节并记录理由。每条标注 **状态**（已定 / 待验证 / 计划中）。

### ADR-1 · 长上下文 in-context 为主, 不建设独立向量 RAG 问答管线

**状态**: 已定

**决策**: 以 **≤50 篇** 为设计上限, 跨文献分析全程在长上下文里做 in-context 推理, **不**建设经典的"分块 + 向量库 + top-k 检索"问答管线。两种工作模式都装得下、都不需要检索:
- **广度模式(看全局)**: 把全部 ≤50 篇的**结构化摘要**(约 6-7 万 tokens, 每篇 ~1-1.5K)一次性入上下文, 用于机会矩阵、信号发现、跨文献综合。
- **深度模式(看精读)**: 把焦点的**少数几篇整篇全文**(单篇 8-15K, 5 篇约 6 万 tokens)入上下文, 用于单篇/数篇精读。

任何时刻只处于其中一种模式, **从不需要把 50 篇全文同时塞进一个上下文**。

**"检索"的受限定义(轻量, 非 RAG)**: 仅以下两种轻量调取, 均不构成 RAG 管线——
1. **按需调取相关全文**: 当问题超出摘要字段时, 先用摘要锁定相关的 3-4 篇, 再把这几篇**整篇全文**带上(定位 + 整篇, 不切片)。
2. **轻量语义搜索 / 聚类**: 用本地 embedding 对**摘要/论断记录**做相似度, 服务矩阵聚类与语义查找。这是给矩阵加语义维度, 不是替模型决定看什么。

**为什么这么定**:
- ≤50 篇摘要本就装得进 128K 窗口; 强行切片只会把"全局视野"打碎, 而本产品做的恰是最需要全局视野的活(找关联/矛盾/空白), RAG 在此是减分项。
- 精读时"整篇端上、注意力全扑一篇"质量高于"塞 50 篇再问细节"(规避长上下文"中间迷失")。哲学(一次一篇、完整、聚焦)与工程在此同向。
- 黑箱检索会静默截断模型视野、藏起"漏了什么", 与"可见胜过自动"的产品承诺正面冲突; 坏检索比无检索更糟。
- 重 RAG(向量库 + embedding + 调优)会增加桌面 app 打包体积与安装复杂度, 与"小而美、一键安装"相悖。

**非目标(明确禁止)**:
- 不建独立向量 RAG 问答管线; 不把全文切片做成 chunk 向量索引用于问答。
- `paper_pages` 必须完整保留全文, **任何"省空间删全文/只留切片"的优化被禁止**(全文是深度模式与按需调取的数据基础)。

**规模兜底(>50 篇, 非当前目标)**: 若语料超过设计上限, 正确解法**不是**经典 chunked RAG, 而是在透明的、结构化的摘要层做一次**可见的智能筛选**(产品告知用户"本问题聚焦于这 N 篇, 可调整"), 再在长上下文推理。筛选可见、可改, 仍遵循"可见"原则。

### ADR-2 · "提取完成（completed）"是一个质量契约, 而非"调用成功"

**状态**: 已定

**决策**: 文献状态置为 `completed` 当且仅当其结构化输出**通过 Pydantic schema 校验**, 且满足下列内容契约。下游所有跨文献分析信任此契约, 不再二次校验。

**completed 状态的保证**:
- 输出为合法 JSON 且能反序列化为 `ExtractedData` schema;
- 必填字段（research_question / sample_source / conclusion）非空;
- `key_data` 至少 1 条且每条含具体数值/指标（正则或模型自检);
- `limitations` 至少 1 条。

**提取的失败处理（区分两类失败）**:
- **调用失败**（网络 / 限流 / 超时）: 指数退避重试, 计入 `extraction_attempts`。
- **内容不合格**（JSON 非法 / 校验未过）: 走**修复循环**——把 Pydantic 的具体校验错误回灌给模型要求修正, 而非盲目重跑整次; JSON 括号/逗号类问题先经 `json-repair` 兜底。
- 两类合计达上限后置 `extract_failed`, 记 `last_error`。

**为什么这么定**: 便宜模型最大的失败模式不是"调不通", 而是"调通了但格式崩/字段敷衍/编造数值"。把"成功"等同于"调用返回 200"会让空洞结果污染整条价值链。质量契约把这个风险挡在提取这一关。

**对其他模块的约束**: 跨文献问答与综述（§4.2、§8.2）可直接信任 `completed` 文献的字段非空且 `key_data` 含数值, 无需防御式判空。

### ADR-3 · 批量提取是持久化的后台 Job, SSE 仅用于订阅进度

**状态**: 计划中（v1.1 内优先落地）

**决策**: 批量提取由后台 worker 执行, 任务状态持久化到 `extract_jobs` 表; SSE 连接只是"订阅"某个 job 的进度, **不再驱动任务执行**。连接断开/页面关闭/进程重启都不影响任务本身。

**为什么这么定**: 20-50 篇串行 + 每篇间隔 ≥1s + API 延迟, 一个批次可能耗时 10-30 分钟。把它挂在一个 HTTP/SSE 请求上, 用户切页面/断网/关窗就会让任务夭折, 并留下卡在 `extracting` 的僵尸文献。Job 化让"一次性处理几十篇"这一核心场景真正可靠。

**状态机规则（明文)**:
- 服务启动时, 扫描所有处于 `extracting` 的文献与未完成的 `extract_jobs`, 一律重置: 文献 `extracting → pending`, job `running → interrupted`, 等待用户恢复或自动续跑。
- 单篇并发用 per-paper 锁防重复扣费; job 内串行执行, 受 `BATCH_EXTRACT_CONCURRENCY` 控制。

**对其他模块的约束**: 见 §6.2 新增 `/jobs` 端点与 §9 改写后的 SSE 订阅规范; §5.1 新增 `extract_jobs` 表。

### ADR-4 · SQLite 并发基线: WAL + busy_timeout, DB 访问模型统一

**状态**: 已定

**决策**: SQLite 启用 **WAL 模式** 并设置 **busy_timeout**（建议 5s）。所有 DB 访问**统一策略**: 要么全程 sync 并经线程池（`asyncio.to_thread`）调用, 要么全程 async; **禁止在 async 端点里直接做 sync DB 调用**。

**为什么这么定**: FastAPI 是 async, 而批量提取写入、用户浏览查询、SSE 推送可能并发发生。SQLite 默认的写锁 + 在事件循环里跑 sync DB 调用, 极易触发 `database is locked` 与事件循环阻塞。WAL 允许读写并发, busy_timeout 让偶发写锁自动等待而非立即报错。

### ADR-5 · 成本可观测: 每次模型调用记录 token 与成本

**状态**: 计划中（v1.2）

**决策**: 每次模型调用（提取/问答/润色/翻译）记录 prompt/completion token 数、provider、model、估算成本, 写入 `token_usage` 表; 项目维度与全局维度可汇总展示。

**为什么这么定**: 产品以"便宜的大模型"为卖点, 用户分析 30 篇文献时理应看到花了多少钱、用了多少 token。没有成本可观测, "省钱"就只是口号。

### ADR-6 · 机会信号架构: 确定性预计算召回 + 聚焦模型逐对裁决 + 数据结构层出处

**状态**: 已定（地基随首个信号落地）

**决策**: 所有机会信号(局限聚类 / 矛盾点 / 稀疏格 / 方法迁移)统一遵循下述三段式架构, **不依赖巨型 prompt**:
1. **召回靠确定性代码**: 用结构化字段 + 本地 embedding 做穷举/聚类式的候选生成(故意宽进)。**"不漏"由这一确定性阶段扛, 不靠模型"愿不愿意找全"**。组合规模在**论断级、同主题簇内**配对, 不在论文级全连接, 故无组合爆炸。
2. **精度靠聚焦的模型调用**: 对每个候选, 一次只看极小输入(一两条带原句的论断)做边界清晰的判定。可并行、可按 hash 缓存、增量计算; 规避长上下文"中间迷失"。模型从不执行 O(n²) 搜索。
3. **出处靠数据结构, 不靠 prompt**: 论文/页码/**逐字原句**在抽取阶段就钉在每条原子论断上, 原样穿过整条流水线; 展示时引用早已在手, 模型无需"重构"出处(引用幻觉正发生于重构时)。AI 的**判断本身**也须落到证据片段上, 以便审计。

**为什么这么定**: 信号的可靠性活在结构里, 不活在 prompt 措辞里。一个再聪明的"把矛盾都找出来"巨型 prompt 也会漏配对; 召回买在确定性穷举里, 精度买在聚焦裁决里, 出处买在逐字原句里——没有一分钱花在"prompt 写得更巧"上。这也是为什么 prompt 设计是下游任务而非开发重点。

**对其他模块的约束**:
- 要求一个**论断级、带 direction/context/provenance 的抽取 schema**(见 §5.1 `claims` 表), 这是所有信号的共同地基, 必须趁早做对。
- 各信号的**内部流水线**(具体配对规则、裁决 prompt、UI、召回诚实度)属实现方案, **不写入本 SPEC**, 见独立《详细功能设计》文档。
- 产品承诺定为**"不静默吞掉任何东西、永远可下钻"**, 而非"找全所有信号": 论断池与候选对可浏览, 低置信/被否决项进"待复核"而非隐藏。

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
|    pdfplumber + 多Provider API + SQLite(WAL) + SSE      |
|    + 后台提取 Job worker + 本地 embedding 轻量语义搜索(非RAG)  |
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
│   │   ├── projects.py         # 项目管理
│   │   ├── batch_extract.py    # 批量提取逻辑
│   │   ├── jobs.py             # 提取 Job 端点(ADR-3)
│   │   ├── literature_crud.py  # 上传/解析/列表/详情/删除/标签
│   │   ├── literature_extract.py # 单篇 SSE 提取
│   │   ├── literature_chat.py  # 跨文献问答 + 单篇问答
│   │   ├── literature_translate.py # 摘要翻译
│   │   ├── chat_sessions.py    # 会话历史
│   │   ├── paper.py            # 论文撰写分块
│   │   ├── settings.py         # API Key / 模型配置 / 测试连接
│   │   └── data.py             # 数据库管理
│   ├── services/
│   │   ├── pdf_parser.py       # PDF 文本提取
│   │   ├── extract_job_worker.py # 后台批量提取 worker(ADR-3)
│   │   ├── kimi_client.py      # OpenAI 兼容 AI 客户端
│   │   ├── api_provider.py     # 多 Provider 解析
│   │   ├── secrets.py          # Fernet + keyring 密钥管理
│   │   ├── db.py               # SQLAlchemy 引擎
│   │   └── extract_prompt.py   # Prompt 模板（输出质量契约见 ADR-2）
│   ├── models/
│   │   ├── schemas.py          # Pydantic Schema
│   │   └── tables.py           # SQLAlchemy 表定义
│   └── tests/                  # 单元测试
│
├── frontend/                   # React + TypeScript
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Projects.tsx        # 项目列表/管理
│   │   │   ├── Literature.tsx      # 文献库
│   │   │   ├── PaperWrite.tsx      # 论文撰写
│   │   │   ├── ChatHistory.tsx     # 会话历史
│   │   │   └── Settings.tsx        # 设置(含多 Provider)
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

**提取要求（质量契约, 见 ADR-2）**:
- 每个字段必须基于原文, 禁止编造
- `key_data` 必须包含**具体数值/指标**, 禁止"显著增加"等模糊表述; 至少 1 条
- `limitations` 必须列出**至少 1 条**真实局限
- 输出必须是合法 JSON, 不要包含 markdown 代码块标记
- **输出经 Pydantic schema 校验后才置 `completed`**; 校验项: 合法 JSON、必填字段非空、`key_data` 含数值、`limitations` 非空
- **失败分两类处理**:
  - 调用失败(网络/限流/超时): 指数退避重试, 计入 `extraction_attempts`
  - 内容不合格(JSON 非法 / 校验未过): 走**修复循环**——把校验错误回灌模型要求修正(非盲目重跑), JSON 语法问题先经 `json-repair` 兜底
- 合计达上限后标记 `extract_failed`, 记 `last_error`

**批量提取（后台 Job, 见 ADR-3）**:
- `POST /projects/{project_id}/batch-extract` 创建一个 Job, 提取该项目全部 pending 文献; 立即返回 `job_id`
- 任务由**后台 worker** 执行, 状态持久化到 `extract_jobs`; 连接断开/进程重启不影响任务
- 前端通过 `GET /jobs/{job_id}/stream` (SSE) **订阅**进度, 而非由请求驱动执行
- 串行执行, 间隔 >= 1 秒(避免 API 限流), 受 `BATCH_EXTRACT_CONCURRENCY` 控制
- 支持暂停/继续/取消; 服务重启后中断的 Job 标 `interrupted`, 可恢复

**文献库管理**
- 列表视图: 标题 / 第一作者 / 年份 / 期刊 / 提取状态 / 所属项目
- 按项目、年份、期刊、标签、提取状态筛选
- 按年份/时间/标题排序
- FTS5 全文搜索(标题 + 摘要 + 关键词)
- 标签系统: 用户自定义标签, 多标签筛选

**机会矩阵与信号面板（核心, 见"产品定位"节与 ADR-6）**

这是本产品的招牌功能, 取代"自由问答"成为跨文献分析的中心。

- **文献矩阵**: 把项目内文献铺成"论文 × 维度(方法/样本/靶点/发现/局限/年份)"的可交互矩阵; AI 填格(来自 `claims`/`extracted_data`), 人读矩阵。支持排序、筛选、空格高亮。
- **信号面板**: 自动 surface 四类机会信号(局限聚类 / 矛盾点 / 稀疏格 / 方法迁移), 每条做成可追溯卡片(论断 + 逐字原句 + 页码 + 跳转 PDF)。
- **人的裁决一等公民**: 每条信号可 接受 / 否决(带理由) / 改判 / 批注(写下自己的假设); 所有判断落库、可追溯、直接喂给立项材料导出(见 4.3)。
- **架构**: 遵循 ADR-6(确定性召回 + 聚焦裁决 + 数据层出处); 各信号内部流水线见独立《详细功能设计》文档, 不在本 SPEC 展开。

**跨文献综合问答(辅助功能, 工程化 Prompt)**

> 自由问答保留为辅助手段(临时提问/追问), 但产品重心是上面的机会矩阵, 而非问答。

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
- **上下文构建（见 ADR-1）**: 广度问答仅拼接所选文献的结构化摘要(≤50 篇约 6-7 万 tokens, 长上下文直接装下)。当问题超出摘要字段时, 先用摘要锁定相关的 3-4 篇, 再把这几篇**整篇全文**带上(定位 + 整篇, **不切片、不向量检索**)。

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

### 4.3 立项材料导出（取代"论文撰写"）

> **重定位**: 本模块从"写一篇成稿论文"(backward-looking, 赛道拥挤)改为"导出研发立项材料"(forward-looking, 工作流的自然终点)。核心原则: **输出是人在机会矩阵上所做判断 + 所选证据链的投影, 不是 AI 另起炉灶的生成**(否则即"魔法按钮", 退回 slop)。

**输入来源(关键)**
- 人在信号面板上已确认的机会 + 批注的假设 + 勾选的支撑论断(带 `claims` 出处)。导出器从这些已完成的判断组装材料, 而非凭空生成。

**输出形态(同一份"判断 + 证据链"的不同投影)**
- proposal(研究/立项书): 背景(矛盾点/空白) → 假设 → 拟解决的局限 → 初步可行性
- proposal 性质 PPT: 同内容的演示版
- 可行性计划: 含人的风险判断
- 数据表: 矩阵/证据的结构化导出

**分块 Markdown 编辑器**(承载 proposal 草稿)
- 按项目维护(见 `paper_blocks.project_id`); 左输入右预览; 停止输入 3 秒自动保存

**学术润色**
- 选中段落调用润色 API; 方向: 学术化 / 中英互润 / 逻辑连贯; 支持接受/拒绝/对比

**参考文献格式化(P2)**
- 输入 DOI 或标题获取元数据, 输出 GB/T 7714 格式

> 各导出格式的模板与组装细节属实现方案, 见独立《详细功能设计》文档。

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

> **旧字段退场计划**: `background` / `methods` / `key_results` 为 v1.0.x 遗留列, 仅为兼容旧文献保留。新提取一律写新字段(research_question / sample_source / sample_size / key_methods / key_data / limitations)。收尾路径: 旧文献在下次重新提取时写入新字段; 当全库无文献依赖旧列时, 由一次 Alembic 迁移 DROP 旧列。**禁止新代码再读写旧列。**

#### `claims` -- 原子论断（ADR-6 地基, 机会信号的最小分析单元）
> 这是机会矩阵与所有信号(矛盾点/局限聚类/方法迁移)的共同数据地基。**论断级而非论文级**: 一篇文章抽出多条带出处、可比对的原子论断。Stage 0 一篇一篇地抽(close reading), 走 ADR-2 校验+回灌循环。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| paper_id | UUID FK | 关联 papers |
| claim_type | ENUM | `finding`(结果论断) / `limitation`(局限) / `method`(方法) 等 |
| subject | TEXT | 被测/被作用对象(如"EV 摄取"); 用于配对的主轴 |
| factor | TEXT | 被改变的因素(如"PC 处理") |
| direction | ENUM | `up` / `down` / `none`(无效应) / `nonmonotonic` / `na` |
| magnitude | TEXT | 效应大小 + 单位(如"2.3 倍") |
| stat | TEXT | 统计量(如"p<0.01") |
| context | JSON | **混杂轴**: 物种 / 样本来源 / 细胞类型 / 方法 / 剂量 / 时间点 / n 等 |
| page_number | INTEGER | 出处页码 |
| verbatim_quote | TEXT | **逐字原句**(反幻觉锚 + 钉回原文的根, 不可省) |
| confidence | FLOAT | 抽取置信度 |
| created_at | DATETIME | 抽取时间 |

> **不可将就项**: `claims` 的 schema 是后续一切信号的地基, 回头改极贵(字段前瞻性原则)。其余信号细节均可迭代, **唯独这张表的字段要趁早抠对**。`verbatim_quote` 与 `page_number` 必须随论断一同落库并贯穿全流水线, 出处可追溯由此在数据结构层得到保证, 而非靠模型重构。

#### `paper_blocks` -- 论文撰写分块
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| project_id | UUID FK | 关联 projects(每个项目一篇草稿) |
| block_name | VARCHAR(20) | `abstract` / `introduction` / `methods` / `results` / `discussion` |
| content | TEXT | Markdown 内容 |
| updated_at | DATETIME | 最后更新时间 |
| UNIQUE(project_id, block_name) | -- | 每个项目下每种分块唯一 |

> **设计说明**: 早期 `UNIQUE(block_name)` 假设全局只能写一篇论文, 与"同时推进多个课题"的产品定位矛盾。改为按 `project_id` 隔离, 每个项目维护独立草稿。

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

#### `extract_jobs` -- 批量提取任务（ADR-3）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | job 主键 |
| project_id | UUID FK | 关联 projects(NULL 表示全局 pending) |
| status | ENUM | `queued` / `running` / `paused` / `completed` / `failed` / `interrupted` / `cancelled` |
| total | INTEGER | 任务文献总数 |
| current | INTEGER | 已处理数 |
| succeeded | INTEGER | 成功数 |
| failed | INTEGER | 失败数 |
| current_paper_id | UUID FK | 当前正在处理的文献(可为 NULL) |
| error_summary | JSON | 失败文献 id 与原因列表 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 最后更新时间 |

> 服务启动时把 `running` 的 job 重置为 `interrupted`, 关联文献 `extracting → pending`(见 ADR-3 状态机)。

#### `token_usage` -- 调用成本记录（ADR-5, v1.2）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 主键 |
| project_id | UUID FK | 关联 projects(可为 NULL) |
| paper_id | UUID FK | 关联 papers(可为 NULL) |
| action | VARCHAR(30) | `extract` / `chat` / `polish` / `translate` |
| provider | VARCHAR | provider 名 |
| model | VARCHAR | 模型名 |
| prompt_tokens | INTEGER | 输入 token |
| completion_tokens | INTEGER | 输出 token |
| est_cost | FLOAT | 估算成本(按 provider 单价) |
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
- `paper_blocks`: `(project_id, block_name)` 联合唯一
- `extract_jobs`: `status`、`project_id` 索引
- `token_usage`: `project_id`、`created_at` 索引
- `claims`: `paper_id`、`claim_type`、`subject` 索引(配对召回用)
- 外键: ON DELETE CASCADE(删除文献时级联删除 pages、extracted_data、paper_tags、claims)
- **连接 PRAGMA(每连接执行, 见 ADR-4)**: `journal_mode=WAL`、`busy_timeout=5000`、`foreign_keys=ON`

### 5.4 数据迁移方案

> 迁移 1-3 已于 v1.1.0 落地（历史记录, 见 `项目日志.md`）; 迁移 4-6 为本目标架构待执行项。

**迁移 1：batches -> projects** ✅ 已完成（revision `b2c3d4e5f6a7`）
- 重命名 `batches` -> `projects`, 增加 `is_default`, 插入默认「未分类」, `papers.batch_id` -> `papers.project_id`

**迁移 2：extracted_data 字段扩展** ✅ 已完成（revision `b2c3d4e5f6a7`）
- 增加 research_question / sample_source / sample_size / key_methods / key_data / limitations; 旧列暂留兼容

**迁移 3：settings 表扩展** ✅ 已完成（revision `a1b2c3d4e5f6`）
- `api_provider`、`api_base_url`

**迁移 4：extract_jobs 表（ADR-3, 待执行）**
- 新建 `extract_jobs` 表 + 索引; 服务启动钩子重置中断 job

**迁移 5：paper_blocks 加 project_id（待执行）**
- 增加 `project_id` 列; 存量 block 归入默认项目; 改唯一约束为 `UNIQUE(project_id, block_name)`

**迁移 6：token_usage 表（ADR-5, v1.2）**
- 新建 `token_usage` 表 + 索引

**迁移 7：claims 表（ADR-6, 机会信号地基, 待执行）**
- 新建 `claims` 表 + 索引(paper_id / claim_type / subject)
- 论断由抽取阶段(Stage 0)写入; 存量已 completed 文献在下次重新提取时回填

**收尾迁移（无固定 revision, 全库新字段化后执行）**
- DROP `extracted_data` 旧列 background / methods / key_results（见 §5.1 退场计划）

---

## 6. API 接口

### 6.1 健康检查
| 方法 | 路径 | 说明 | 响应 |
|------|------|------|------|
| GET | `/health` | 健康检查 | `{"status": "ok", "version": config.VERSION}` |

### 6.2 项目模块 (`/api/v1/projects`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/` | 创建项目 | `{"name": "string(1-100)", "description?": "string"}` | `{"id", "name", "created_at"}` |
| GET | `/` | 获取项目列表 | query: page, page_size | `{"items": [{id, name, paper_count, updated_at}], total, page}` |
| GET | `/{id}` | 获取项目详情(含文献) | - | `{"id", "name", "papers": [...]}` |
| PUT | `/{id}` | 更新项目 | `{"name?", "description?"}` | `{"id", "name"}` |
| DELETE | `/{id}` | 删除项目(文献移入"未分类") | - | `{"success", "moved_count"}` |
| POST | `/{id}/batch-extract` | 为该项目 pending 文献**创建提取 Job** | - | `{"job_id", "total"}`(立即返回, 不阻塞) |
| POST | `/{id}/move-papers` | 批量移动文献到本项目 | `{"paper_ids": ["uuid"]}` | `{"success", "moved_count"}` |

### 6.2.1 提取任务 (`/api/v1/jobs`)（ADR-3）
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/` | Job 列表 | query: status, project_id, page | `{"items": [{id, project_id, status, current, total}], total}` |
| GET | `/{job_id}` | Job 详情 | - | `{id, status, current, total, succeeded, failed, error_summary}` |
| GET | `/{job_id}/stream` | **订阅**进度(SSE) | - | SSE 流: `progress` / `done` / `error` 事件(见 §9) |
| POST | `/{job_id}/pause` | 暂停 | - | `{"status": "paused"}` |
| POST | `/{job_id}/resume` | 继续(含恢复 interrupted) | - | `{"status": "running"}` |
| POST | `/{job_id}/cancel` | 取消 | - | `{"status": "cancelled"}` |

### 6.3 文献 CRUD (`/api/v1/literature`)

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

### 6.4 文献问答 (`/api/v1/literature`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/chat` | 跨文献问答 | `{"paper_ids[]?", "project_id?", "question", "session_id?"}` | SSE 流。`project_id` 与 `paper_ids` 二选一, project_id 自动展开为该项目全部文献 |
| POST | `/{id}/chat` | 单篇精读问答 | `{"question", "session_id?", "use_fulltext?"}` | SSE 流。`use_fulltext=true` 时调取全文, false 时仅用摘要, 默认 false |

### 6.5 会话历史 (`/api/v1/chat-sessions`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/` | 获取会话列表 | query: type, page | `{"items": [{id, title, session_type, created_at}], total, page}` |
| GET | `/{id}` | 获取会话详情 | - | `{"id", "title", "messages", "created_at"}` |
| DELETE | `/{id}` | 删除会话 | - | `{"success"}` |

### 6.6 论文撰写 (`/api/v1/paper`)
| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/blocks` | 获取某项目五个分块 | query: project_id | `{"abstract", "introduction", "methods", "results", "discussion"}` |
| PUT | `/blocks/{block_name}` | 保存分块 | `{"project_id", "content": "string"}` | `{"block_name", "updated_at"}` |
| POST | `/polish` | 润色段落 | `{"text", "direction"}` | `{"polished_text", "diff?"}` |
| POST | `/citation` | 格式化参考文献 | `{"doi?" or "title?"}` | `{"citation_gb7714"}` |

### 6.7 设置 (`/api/v1/settings`)
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

### 6.9 数据管理 (`/api/v1/data`)
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

## 8. Prompt 工程化

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

SSE 用于两类场景, 二者语义不同（见 ADR-3）:
- **问答/提取的内容流**（`/chat`、`/{id}/extract`）: 请求驱动, 连接断开即终止本次输出。
- **批量提取的进度订阅**（`/jobs/{job_id}/stream`）: **只读订阅**, 连接断开不影响后台 Job; 重连后从 Job 当前状态继续推送。

### 9.1 后端 SSE 规范
- Content-Type: `text/event-stream`
- 内容流消息: `data: {"type": "chunk", "content": "..."}\n\n`
- 进度事件(Job 订阅): `data: {"type": "progress", "job_id": "...", "current": 3, "total": 50, "paper_id": "...", "status": "extracting", "title": "..."}\n\n`
- 结束: `data: {"type": "done"}\n\n`
- 错误: `data: {"type": "error", "message": "..."}\n\n`
- **Job 订阅断开 != 任务结束**: 后端在断开时仅停止推送, **不回滚 Job 状态**; Job 由 worker 独立推进。

### 9.2 前端 useSSE Hook
使用 `fetch + ReadableStream`(EventSource 不支持 POST 请求体):

```typescript
// 实现要点:
// 1. fetch 请求, 获取 response.body ReadableStream
// 2. TextDecoder 逐块解码, 按 "\n\n" 分割 SSE 事件
// 3. 解析每行 "data: {...}" 格式, 提取 JSON
// 4. 事件分发: type='chunk' -> 累加文本; type='progress' -> 更新进度; type='done' -> 结束; type='error' -> 终止
// 5. 断线检测: reader.read() 抛异常时触发重连
// 6. 重连策略按场景区分:
//    - 内容流(chat): disableRetry, HTTP 4xx/5xx 与网络错误均不重连(防重复提交/重复扣费)
//    - Job 订阅: 网络错误时重连(最多 3 次, 间隔 1s/2s/4s), 重连后用 GET /jobs/{id} 对齐当前进度
// 7. 组件卸载时 abortController.abort() 关闭连接
// 8. 同一内容流禁止并发(per-url Lock); Job 订阅可断可续, 不锁
//
// P2 增强: progress 事件 seq 去重、断点续传
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

## 11. 开发阶段

### 11.0 目标架构实施路线（当前）

> v1.1.0 的 Step 1-6 已落地（见下方历史记录与 `项目日志.md`）。以下是从当前状态推进目标架构的路线, 按"先止血 → 再加固 → 后增强"排序。

**Phase 0 · 止血（最先做）**
- [ ] v1.1.0 安装包端到端回归（项目 CRUD / 上传 / 删除 / 提取 / 设置）
- [ ] 服务启动重置残留 `extracting → pending`（ADR-3 状态机, 十几行但必做）
- [ ] 修复测试 URL 不匹配, 冻结 `API_CONTRACT.md`

**Phase 1 · 加固提取（最高 ROI, ADR-2）**
- [ ] 提取输出接 Pydantic 校验 + 校验错误回灌的修复循环
- [ ] 引入 `json-repair` 兜底; 区分"调用失败"与"内容不合格"
- [ ] `completed` 仅在通过质量契约后置位

**Phase 2 · 批量提取 Job 化（ADR-3 + ADR-4）**
- [ ] 新建 `extract_jobs` 表 + 后台 worker; `/jobs` 端点（§6.2.1）
- [ ] SSE 退化为订阅（§9 改写）; SQLite 开 WAL + busy_timeout
- [ ] 启动钩子重置中断 Job

**Phase 3 · 清理结构性债**
- [ ] LLM 客户端重构为 provider 无关抽象（实现细节, 不入契约）
- [ ] `paper_count` 改实时 COUNT 或触发器
- [ ] `paper_blocks` 加 `project_id`（迁移 5）
- [ ] 规划 `extracted_data` 旧列退场

**Phase 4 · 能力增强**
- [ ] 本地 embedding **轻量语义搜索/聚类**（ADR-1, 非 RAG）: 服务矩阵聚类与配对召回
- [ ] `token_usage` 成本记录与展示（ADR-5）
- [ ] 跨文献分析改 map-reduce; 答案缓存

**Phase 5 · 机会信号(产品核心价值, ADR-6) — 纵切片驱动**
> 不一次全建。以"一个信号端到端立起一条纵切片"为节奏, 每个切片打通: claims 字段 → 抽取 → 确定性召回 → 聚焦裁决 → 可追溯 UI(accept/reject) → 喂给立项导出。
- [ ] **claims 表 schema 抠定并落库**（迁移 7; 唯一不可将就项, 趁早做对）
- [ ] **首个纵切片 = 局限聚类**(最不易幻觉、技术最简、直出"未满足需求"; 作热身)
- [ ] 第二切片 = 矛盾检测(技术最难, 含金量最高; 见独立《详细功能设计》)
- [ ] 矩阵视图 + 信号面板 + 人的裁决落库
- [ ] 立项材料导出: 从已确认的判断 + 证据链投影(§4.3)

---

### 历史记录 · v1.1.0 Step 1-6（已完成）


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
| **提取内容不合格(便宜模型敷衍/编造/JSON崩)** | **高** | **ADR-2 质量契约: Pydantic 校验 + 修复循环 + json-repair; 不合格不置 completed** |
| **批量 Job 中断(断网/关窗/重启)** | **高** | **ADR-3 Job 持久化 + 启动重置 + 可恢复; 不再挂在 SSE 连接上** |
| **SQLite 并发写锁(database is locked)** | **中** | **ADR-4 WAL + busy_timeout; DB 访问模型统一** |
| DeepSeek API 稳定性 | 中 | 备用 Moonshot 128K, 用户可切换 |
| 大 PDF 解析超时(>50MB 扫描版) | 中 | 文件上限 50MB; 扫描版标记后跳过 AI 提取 |
| Electron 打包体积大 | 低 | 预期 150-200MB, 可接受 |
| Windows Defender 误杀 | 中 | 首次启动可能触发 SmartScreen, README 说明 |
| 模型迭代适配 | 低 | 模型名配置化, 升级只改 config.py 一行 |
| SSE 断线 | 中 | 内容流终止本次; Job 订阅可重连对齐进度 |
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

### 架构契约（对应 ADR）
- [ ] **ADR-1**: 问"摘要未覆盖"的细节时, 系统调取相关的少数几篇**整篇全文**作答; 全程无向量切片/RAG 管线; `paper_pages` 全文完整保留
- [ ] **ADR-2**: 喂入格式错乱/字段敷衍的样例, 系统走修复循环且不把空洞结果置为 completed
- [ ] **ADR-3**: 批量提取进行中关闭页面/重连, Job 继续推进, 重连后进度对齐; 杀进程重启后残留 extracting 被重置且 Job 可恢复
- [ ] **ADR-4**: 批量提取同时浏览/查询, 不出现 database is locked
- [ ] **ADR-5**: 提取/问答后 token_usage 有记录, 项目维度可汇总成本
- [ ] **ADR-6**: 信号(以局限聚类为例)由确定性召回 + 聚焦裁决产出, 每条卡片可钉回逐字原句与页码; 低置信/被否决项进"待复核"而非被静默吞掉; 论断池可浏览

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
