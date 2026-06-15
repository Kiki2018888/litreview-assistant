# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 将 Python 后端打包为 onedir 可执行文件.

用法：
    cd backend
    pyinstaller backend.spec --distpath ../dist --workpath ../dist/build-backend

输出结构：
    ../dist/backend/          (COLLECT 输出，完整应用目录)
      backend.exe             (薄启动器 + PYZ)
      _internal/              (Python 运行时与所有依赖)
      alembic/                (数据库迁移脚本)
      alembic.ini             (Alembic 配置)
"""

import os
import sys

# ---------------------------------------------------------------------------
# 将项目根目录加入 sys.path，确保 "from backend.xxx import yyy" 可解析
# ---------------------------------------------------------------------------
_project_root = os.path.dirname(SPECPATH)  # backend/ → 项目根
sys.path.insert(0, _project_root)

# ---------------------------------------------------------------------------
# 隐藏导入
# ---------------------------------------------------------------------------
hidden_imports = [
    # uvicorn
    'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio',
    'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan.on', 'uvicorn.lifespan.off',
    # SQLAlchemy
    'sqlalchemy.ext.baked', 'sqlalchemy.sql.default_comparator',
    # multipart 上传（POST /upload 依赖；pip 包名 python-multipart，模块名 multipart）
    'multipart',
    'starlette.formparsers', 'starlette.requests',
    # pymupdf / pdfplumber
    'fitz', 'pymupdf', 'pdfplumber', 'pdfplumber._typing',
    # PIL（pdfplumber 图像处理）
    'PIL', 'PIL._imaging',
    # cryptography / keyring
    'cryptography', 'cryptography.hazmat.backends',
    'keyring', 'keyring.backends', 'keyring.backends.Windows',
    'keyring.backends.chainer',
    # pydantic
    'pydantic', 'pydantic.deprecated.decorator',
    # Alembic 迁移
    'alembic.runtime.migration', 'alembic.command', 'alembic.config',
    # Kimi API
    'openai', 'httpx',
    # json_repair（AI 输出 JSON 修复；PyInstaller 隐藏导入）
    'json_repair',
    # 其他
    'aiofiles', 'email_validator', 'jose', 'pypdfium2',
]

# ---------------------------------------------------------------------------
# 数据文件
# ---------------------------------------------------------------------------
datas = [
    ('alembic', 'alembic'),
    ('alembic.ini', '.'),
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['main.py'],
    pathex=['..', '.'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'scipy',
        'pandas', 'PIL.ImageQt', 'IPython',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# EXE（COLLECT 的前置步骤）
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,  # 关键：排除二进制文件，标准 onedir 写法
    name='backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# ---------------------------------------------------------------------------
# COLLECT（--onedir 模式，生成完整应用目录）
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='backend',
)
