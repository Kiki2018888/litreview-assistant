"""ResearchAssistant 应用入口.

FastAPI 应用启动、CORS、生命周期管理、路由注册。
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

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


# ---------------------------------------------------------------------------
# 数据库迁移（首次运行自动建表）
# ---------------------------------------------------------------------------


def _get_alembic_cfg_path() -> Path:
    """定位 alembic.ini：生产模式在 sys._MEIPASS，开发模式在 backend/ 目录."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent  # backend/
    return base / "alembic.ini"


def _run_migrations() -> None:
    """执行 Alembic 迁移，确保数据库结构为最新版本."""
    try:
        from alembic import command
        from alembic.config import Config

        ini_path = _get_alembic_cfg_path()
        if not ini_path.exists():
            logger.warning("alembic.ini 未找到，跳过数据库迁移")
            return

        alembic_cfg = Config(str(ini_path))

        # 生产模式下 script_location 指向 _MEIPASS/alembic/
        if getattr(sys, "frozen", False):
            alembic_scripts = Path(sys._MEIPASS) / "alembic"  # type: ignore[attr-defined]
            alembic_cfg.set_main_option("script_location", str(alembic_scripts))

        command.upgrade(alembic_cfg, "head")
        logger.info("数据库迁移完成（Alembic）")
    except Exception:
        logger.exception("Alembic 迁移失败，尝试 fallback（create_all + FTS5）")
        try:
            from backend.services.db import init_db
            init_db()
            logger.info("已通过 create_all 创建数据表（fallback）")

            # 补齐 FTS5 虚拟表与触发器（init_db 不创建 FTS5）
            from backend.api.v1.data import _init_fts5
            _init_fts5()
            logger.info("FTS5 虚拟表和触发器已创建（fallback）")
        except Exception:
            logger.exception("数据库初始化完全失败，终止启动")
            sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时确保目录/表存在，关闭时清理资源."""
    # 启动：确保 data/ 与 logs/ 目录存在
    from backend.config import DATA_DIR, PDF_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    logger.info("ResearchAssistant v%s 启动，数据目录 %s", VERSION, DATA_DIR)

    # 首次运行自动建表
    _run_migrations()

    # 启动重置：将异常中断卡在 extracting 的文献回退到 pending
    from backend.models.tables import Paper, PaperStatus
    from backend.services.db import SessionLocal

    with SessionLocal() as db:
        zombies = db.query(Paper).filter(Paper.status == PaperStatus.EXTRACTING.value).all()
        for p in zombies:
            p.status = PaperStatus.PENDING.value
            p.last_error = "服务重启，提取中断"
        if zombies:
            db.commit()
            logger.info("启动重置：%d 篇 extracting → pending", len(zombies))

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
    allow_origins=[
        "app://.",           # Electron 开发模式
        "null",              # file:// 协议首页 Origin
    ],
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
from backend.api.v1.literature_chat import router as literature_chat_router
from backend.api.v1.literature_extract import router as literature_extract_router
from backend.api.v1.literature_translate import router as literature_translate_router
from backend.api.v1.projects import router as projects_router
# from backend.api.v1.batches import router as batches_router  # v1.1.0 已废弃
# from backend.api.v1.batch_extract import router as batch_extract_router  # 已迁至 projects
from backend.api.v1.settings import router as settings_router
from backend.api.v1.data import router as data_router
from backend.api.v1.chat_sessions import router as chat_sessions_router
from backend.api.v1.paper import router as paper_router

# 固定路径路由器先注册：POST /chat 优先于 /{paper_id}
app.include_router(literature_chat_router)
app.include_router(literature_translate_router)
app.include_router(literature_extract_router)
app.include_router(literature_router)
# /api/v1/projects — 项目管理 + 批量提取
app.include_router(projects_router)
# 独立前缀路由
app.include_router(settings_router)
app.include_router(data_router)
app.include_router(chat_sessions_router)
app.include_router(paper_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# 直接运行入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    from backend.config import DATA_DIR

    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)

    frozen = getattr(sys, "frozen", False)
    uvicorn.run(
        app if frozen else "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug and not frozen,
        log_config=None,  # PyInstaller console=False 时 sys.stderr 为 None，禁用 ColoredFormatter
        access_log=False,
    )
