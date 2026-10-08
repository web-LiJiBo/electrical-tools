from __future__ import annotations

import argparse
import json
from pathlib import Path

from .api.app import create_app
from .bootstrap import build_application
from .contracts import AnalysisRequest


def main() -> int:
    parser = argparse.ArgumentParser(description="机器可读标准知识服务后台")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[2] / "configs" / "settings.example.yaml"))
    parser.add_argument("--query", default="")
    parser.add_argument("--scenario", default="")
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if args.serve:
        try:
            import uvicorn
        except ImportError as exc:
            raise SystemExit("启动服务需要安装 uvicorn") from exc
        uvicorn.run(create_app(args.config), host="127.0.0.1", port=8000)
        return 0
    if not args.query:
        parser.error("命令行分析需要--query；启动API使用--serve")
    app = build_application(args.config)
    result = app.facade.analyze(AnalysisRequest(args.query, args.scenario))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
