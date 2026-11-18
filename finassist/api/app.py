"""
api/app.py —— 创建 FastAPI 应用对象 + 管理全局资源的生命周期

■ 它是什么
    1) 创建 app（挂上路由）
    2) 用 lifespan 管理「进程级资源」的创建与释放

■ lifespan 里依次做三件事（顺序有讲究）
    init_db_engine()     建数据库连接池
    init_http_client()   建共享的 httpx.AsyncClient（连接复用，别每次请求都新建）
    init_dialogue_engine()  装配对话引擎（会解析 YAML、扫描 action 包）

    ※ 为什么引擎放在最后？
      它依赖前两者吗？其实不直接依赖，但它是三者里最重的（要读配置、扫包），
      放最后能让启动失败的报错顺序更符合直觉：先确认 IO 资源可用，再谈业务。

    ※ 为什么必须 yield 而不是直接建？
      lifespan 的写法是「yield 之前 = 启动，yield 之后 = 关闭」。
      没有 yield 的清理逻辑，进程退出时连接池和 HTTP 客户端不会被优雅关闭，
      在开发环境反复重启时容易看到连接泄漏的告警。

■ 关闭顺序
    await close_db_engine()      先放掉数据库连接池
    await close_http_client()    再关共享的 HTTP 客户端
    ※ 严格说这两者谁先谁后影响不大（都是释放连接），
      但一定要有 —— 缺了它们，uvicorn 热重载时会不断泄漏连接，
      表现为 MySQL 端 max_connections 被占满。

■ 路由挂载
    app.include_router(chat_router) —— 所有接口都在 /api 前缀下，见 chat_router.py。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from finassist.api.chat_router import chat_router
from finassist.api.dependencies import init_dialogue_engine
from finassist.utils.db import init_db_engine, close_db_engine
from finassist.utils.httpx_client import init_http_client, close_http_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 数据库使用对象初始化操作
    init_db_engine()
    # 远程调用对象初始化操作
    init_http_client()
    # 对话引擎初始化：解析 yaml、组装 TaskHandler 那套组件（只做一次）
    init_dialogue_engine()
    yield
    await close_db_engine()
    await close_http_client()

app = FastAPI(title="融知 FinAssist 客服服务", version="0.1.0", lifespan=lifespan)
app.include_router(chat_router)