#!/usr/bin/env python3
"""
FinAssist 业务中台服务启动脚本
"""
from __future__ import annotations

import ctypes
import sys

import uvicorn

from app.config import settings


def _enable_utf8_console() -> None:
    """把 Windows 控制台切到 UTF-8（代码页 65001），emoji 才打印得出来。

    Windows 控制台默认代码页是 936(GBK)，gbk 编不出 🚀📍📚 这类字符，
    直接 print 会抛 UnicodeEncodeError 把服务启动打断。
    """
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    # 输出流也固定成 utf-8，避免输出被重定向到文件/管道时又回退到 gbk
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    """启动 FastAPI 应用"""
    _enable_utf8_console()
    print(f"🚀 正在启动 FinAssist 业务中台服务...", flush=True)
    print(f"📍 地址: http://{settings.app_host}:{settings.app_port}", flush=True)
    print(f"📚 API 文档: http://{settings.app_host}:{settings.app_port}/docs", flush=True)
    
    uvicorn.run(
        "app.app:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,  # 开发模式自动重载
        log_level="info"
    )


if __name__ == "__main__":
    main()
