"""
api/dependencies.py —— FastAPI 依赖注入：把「全局单例」递给路由

■ 它是什么
    提供一串 Depends 可用的函数，由 FastAPI 按参数类型自动串起来：
        get_session()          → 每次请求开一个 AsyncSession，请求结束自动关闭
        get_repository()       → 用上面的 session 造一个 DialogueRepository
        get_engine()           → 返回全局 DialogueEngine（整个进程只有一个）
        get_dialogue_service() → 把 repository + engine 组装成 DialogueService

    ※ 注意这是在「组装一棵依赖树」：路由只要声明一个 DialogueService 参数，
      FastAPI 会自动递归地把 session、repository、engine 全部造好递进来。

■ 在调用链中的位置
    api/chat_router.py::chat(..., service: DialogueService = Depends(get_dialogue_service))
        ↓ FastAPI 自动调用本文件里的函数把参数填好
    路由函数体只拿到「成品」，不关心怎么构造

■ 为什么要模块级变量 _dialogue_engine
    ※ 引擎里装着 FlowCatalog（启动时解析好的 YAML）、ActionRegistry、
      各种 Handler —— 每个都是无状态的、可复用的。
      如果每个请求都 new 一遍，就要重复解析 YAML、重复扫描 action 包，纯浪费。
      所以进程启动时建一次（见 api/app.py 的 lifespan → engine/builder.py），
      之后所有请求共用。

    ※ 它不是「请求时懒加载」：真正创建发生在 api/app.py 的 lifespan 里
      （init_dialogue_engine → build_engine）。get_engine 只负责取，取不到就抛错。
      这样做的好处是：YAML 解析错误、action 注册错误会在**进程启动时**炸出来，
      而不是等第一个用户来访问才发现。

■ get_session 的事务边界
    用 async with 开 session：正常结束自动归还连接，异常时回滚。
    ※ commit 不在这里做，而是由 save_state 显式提交（见 repository/dialogue_repository.py），
      这样「读状态」和「写状态」能在同一个事务里完成。
      换句话说：一个 HTTP 请求 = 一个数据库事务。
"""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.engine.builder import build_engine
from finassist.engine.dialogue_engine import DialogueEngine
from finassist.repository.dialogue_repository import DialogueRepository
from finassist.service.dialogue_service import DialogueService
from finassist.utils import db


# 创建获取数据库操作session对象方法
async def get_session():
    async with db.async_session() as session:
        yield session

# 创建repository对象
async def get_repository(session:AsyncSession=Depends(get_session)):
    return DialogueRepository(
        session=session,
    )


# engine 是"重"对象：要解析 yaml、建一堆无状态组件，
# 所以放在 lifespan 里建一次，全局复用（day05 从"每请求现造"改成这个）
_dialogue_engine: DialogueEngine | None = None


def init_dialogue_engine():
    global _dialogue_engine
    _dialogue_engine = build_engine()


async def get_engine() -> DialogueEngine:
    if _dialogue_engine is None:
        # 说明 lifespan 没跑到（比如直接 new 了 app 却没走 startup）
        raise RuntimeError("DialogueEngine 还没初始化，检查 api.app 的 lifespan 有没有调用 init_dialogue_engine()")
    return _dialogue_engine


async def get_dialogue_service(
        repository:DialogueRepository=Depends(get_repository),
        engine:DialogueEngine=Depends(get_engine)):
    return DialogueService(
        repository=repository,
        engine=engine,
    )
