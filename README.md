# ResearchAssistant — 本地 AI 文献精读助手

面向科研人员的本地化 AI 文献精读与学术写作助手。基于 Electron + Python FastAPI 构建，整合 Kimi 大模型，支持 PDF 上传、自动摘要提取、多轮问答和学术撰写。

## 系统要求

- Windows 10+ (x64)
- 无需安装 Python 环境（已内嵌）
- Kimi API Key（[免费获取](https://platform.moonshot.cn)）

## 安装

1. 下载 `ResearchAssistant Setup 1.0.0.exe`
2. 双击安装，可选择安装目录
3. 安装完成后桌面自动创建快捷方式
4. 启动应用，在设置页填入 Kimi API Key 即可使用

## 功能

- **文献管理**：上传 PDF，自动提取元数据和摘要
- **全文检索**：FTS5 搜索引擎，快速定位关键段落
- **AI 问答**：基于文献全文的多轮对话，支持流式输出
- **学术撰写**：引用文献辅助论文/综述写作
- **数据安全**：所有数据本地存储，API Key 加密（Fernet）

## 技术栈

| 层 | 技术 |
|---|------|
| 桌面壳 | Electron 35 |
| 前端 | React 19 + TypeScript + Tailwind CSS 4 + Vite 8 |
| 后端 | Python FastAPI + SQLite (SQLAlchemy ORM + FTS5) |
| AI | Kimi API（兼容 OpenAI SDK） |
| 打包 | PyInstaller (onedir) + electron-builder (NSIS) |
| 更新 | electron-updater（GitHub Releases） |

## 开发

```bash
# 安装前端依赖
cd frontend && npm install

# 安装后端依赖
pip install -r requirements.txt

# 启动开发模式
# 终端1: 后端
cd backend && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# 终端2: 前端
cd frontend && npm run dev
# 终端3: Electron (加载 localhost:5173)
npm run electron:dev
```

## 构建

```bash
npm run electron:build
```

构建产物位于 `release/` 目录。

## License

MIT
