"""可选 FastAPI HTTP 封装；缺少 FastAPI 时不影响核心后台命令行运行。"""

from __future__ import annotations

from pathlib import Path

from ..bootstrap import build_application
from .schemas import analysis_request_from_json


def create_app(config_path: str | Path):
    try:
        from fastapi import FastAPI
    except ImportError as exc:
        raise RuntimeError("启动HTTP API需要安装 fastapi 和 uvicorn") from exc
    application = build_application(config_path)
    app = FastAPI(title="标准知识服务工具", version="0.1.0")
    try:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    except ImportError:
        pass

    from .routes import register_routes
    register_routes(app, application)
    return app
