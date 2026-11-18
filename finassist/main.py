"""
finassist/main.py —— 进程入口

■ 它做什么
    只做一件事：用 uvicorn 把 api/app.py 里的 app 跑起来，host/port 从 .env 读。

■ 为什么这么薄
    ※ 真正的初始化（数据库引擎、HTTP 客户端、对话引擎）都放在 FastAPI 的
      lifespan 里（api/app.py），而不是放在这里。
      区别是：lifespan 里的代码在**应用启动事件**里执行，
      用 uvicorn 命令行启动、用 gunicorn 多 worker 启动、或在测试里用
      TestClient 启动，都会走同一条初始化路径；
      写在这里就只对「python -m finassist.main」这一种启动方式有效。

■ 启动方式
    python -m finassist.main
    或   uvicorn finassist.api.app:app --reload
"""
import uvicorn

from finassist.conf.config import settings


def main():
    # 引擎/数据库/httpx 的初始化都在 api.app 的 lifespan 里，
    # 这里再 init 一次是重复的；而且开了 reload 时，父进程里 init 出来的对象
    # 在子进程里根本不生效（子进程重新 import 模块，拿不到父进程的全局变量）
    uvicorn.run('finassist.api.app:app',
                host=settings.app_host,
                port=settings.app_port,
                )


if __name__ == '__main__':
    main()
