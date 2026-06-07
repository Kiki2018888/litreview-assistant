"""ResearchAssistant 应用入口.

FastAPI 应用启动、CORS、生命周期管理、路由注册。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import VERSION, settings

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时确保目录/表存在，关闭时清理资源."""
    # 启动：确保 data/ 目录存在
    from backend.config import DATA_DIR, PDF_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("ResearchAssistant v%s 启动，数据目录 %s", VERSION, DATA_DIR)
    yield
    # 关闭：无额外清理
    logger.info("ResearchAssistant 关闭")


# ---------------------------------------------------------------------------
# 应用实例
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ResearchAssistant",
    version=VERSION,
    description="面向科研人员的本地 AI 文献精读与学术写作助手",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# CORS（Electron 本地开发需要）
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["app://."],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


@app.get("/health")
def health_check() -> dict:
    """简易健康检查，Electron 启动轮询此端点."""
    return {"status": "ok", "version": VERSION}


# ---------------------------------------------------------------------------
# 路由注册（固定路径 → 参数化路径，与 SPEC §6 一致）
# ---------------------------------------------------------------------------

from backend.api.v1.literature_crud import router as literature_router

app.include_router(literature_router)


# ---------------------------------------------------------------------------
# 直接运行入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
