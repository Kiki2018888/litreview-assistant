# ResearchAssistant — 本地优先的 AI 科研文献分析工具

> 面向科研人员的本地优先（local-first）文献精读助手：上传 PDF，自动产出结构化摘要、抽取原子论断（claims），并支持单篇精读问答与摘要翻译。数据全部存于本地，AI 推理通过你自己的 API Key 调用。

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](./LICENSE)

---

## ✨ 主要功能

- **文献管理**：上传 PDF，自动解析元数据，按项目分组管理。
- **结构化摘要**：调用大模型产出研究问题 / 样本来源 / 关键数据 / 结论 / 局限等字段；不完美摘要也会以「部分成功」入库，不轻易判废。
- **原子论断（Claims）抽取**：把文献正文拆解为可核对的原子论断，支持批量提取，结果在文献库列表与详情中可见。
- **单篇精读问答**：基于单篇文献的多轮对话，流式输出。
- **跨文献问答**：在项目范围内跨多篇文献提问。
- **摘要翻译**：一键中文学术化翻译。
- **本地与隐私**：所有文献、数据库存于本地；API Key 经 Fernet 加密存于本地 SQLite。

### 🚧 开发中（敬请期待）

以下「信号发现 / 机会矩阵」模块尚在开发中，当前版本入口已统一占位为「敬请期待」，不会触发请求：

- 分析局限 / 局限聚类
- 裁决面板（候选信号的人工裁决）
- 矛盾点 / 稀疏格 / 方法迁移

---

## 🧱 技术栈

| 层 | 技术 |
|---|------|
| 桌面壳 | Electron 35 |
| 前端 | React 19 + TypeScript + Tailwind CSS 4 + Vite 8 |
| 后端 | Python + FastAPI + SQLite（SQLAlchemy ORM + FTS5 全文检索） |
| AI | DeepSeek API（默认，OpenAI 兼容）；同时支持 Moonshot / Kimi 等 OpenAI 兼容 Provider |
| 打包 | PyInstaller（onedir）+ electron-builder（NSIS） |

---

## 🚀 安装与运行

### 方式一：下载安装包（Windows）

前往本仓库的 [Releases](../../releases) 下载 `ResearchAssistant Setup x.y.z.exe`，双击安装；启动后在「设置」页填入你自己的 DeepSeek API Key 即可使用。

### 方式二：从源码运行（开发模式）

前置：Node.js 18+、Python 3.12。

```bash
# 1. 克隆
git clone https://github.com/Kiki2018888/litreview-assistant.git
cd litreview-assistant

# 2. 安装依赖
cd frontend && npm install && cd ..
pip install -r requirements.txt

# 3. 启动后端（终端 1）
cd backend && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 4. 启动前端（终端 2）
cd frontend && npm run dev

# 5. 启动 Electron 壳（终端 3，加载 localhost:5173）
npm run electron:dev
```

### 构建安装包

```bash
npm run electron:build   # 前端 build + PyInstaller + electron-builder
```

产物位于 `release/` 目录（该目录已被 git 忽略）。

---

## 🔑 配置 API Key

本应用**不内置任何密钥**，你需要使用自己的 DeepSeek API Key（在 <https://platform.deepseek.com> 申请）。

两种配置途径：

1. **应用内（推荐）**：启动后在「设置」页填入 API Key、选择 Provider 与模型。密钥经 Fernet 加密存于本地 SQLite，不写入任何明文文件。
2. **环境变量（开发 / CLI 脚本）**：复制 `.env.example` 为 `.env.local` 并填入你的 Key：

   ```bash
   cp .env.example .env.local
   ```

   ```dotenv
   DEEPSEEK_API_KEY=your-key-here
   DEEPSEEK_BASE_URL=https://api.deepseek.com
   DEEPSEEK_MODEL=deepseek-v4-flash
   ```

> ⚠️ `.env` / `.env.local` 已被 `.gitignore` 忽略，**切勿把真实 API Key 提交到仓库**。

---

## 📂 目录结构（简）

```
backend/      FastAPI 后端（API、服务、SQLAlchemy 模型、Alembic 迁移）
frontend/     React + Vite 前端
electron/     Electron 主进程
docs/         API 契约 / 错误处理 / 已知问题 / 安全说明
```

---

## 🗺️ 版本历史

详见 `项目日志.md`。近期：

- **1.2.1** 模型默认值修复（问答/翻译统一走 DeepSeek flash）
- **1.2.2** 提取流水线可靠性整治（摘要校验放宽、失败不锁死、任务自愈、claims 可见、保守并发、上传项目归属修复）
- **1.2.3** 信号发现入口统一占位「敬请期待」，先发布基础功能

---

## 📄 许可证

本项目采用 **GNU Affero General Public License v3.0 (AGPLv3)**，完整条款见 [LICENSE](./LICENSE)。

简言之：你可以自由使用、修改、分发本软件，但**衍生作品须以相同协议（AGPLv3）开源**；若你通过网络提供本软件的服务，也须向用户提供对应的源代码。

```
Copyright (C) 2026  XQ

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.
```

---

## 👤 作者 / 联系方式

**XQ**  ·  📧 loishier@vip.qq.com
