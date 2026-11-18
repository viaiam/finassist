"""
数据库连接资源：创建、取出 session、关闭。

■ 它在哪
    api/app.py 的 lifespan 启动时调 init_db_engine()，关机时调 close_db_engine()；
    api/dependencies.py 的 get_session() 用这里导出的 async_session 工厂产 session。

■ 两个全局变量，分工不同（※ 这是最容易混的地方）
    engine        引擎：真正持有连接池的对象。全进程一个，进程活着它就在。
    async_session 会话工厂：不是 session 本身，是「造 session 的函数」。
                  每次请求调 async_session() 得到一个新的 AsyncSession。

    一句话：engine 管连接池，async_session 管「借还连接」。

■ 为什么用 global 声明？
    init_db_engine 要给模块级变量重新赋值，不写 global 的话 python 会认为
    你在函数里新建了局部变量，外面的 engine 永远是 None。

■ 为什么是同步函数 init_db_engine，却是异步函数 close_db_engine？
    create_async_engine 只是构造对象、不真的连数据库（懒连接），所以不用 await；
    dispose() 要真的去关连接池里的连接，是 IO，所以必须 await。

■ echo=True 的代价
    会把每条 SQL 打到控制台。学习阶段非常有用（能看清 ORM 生成了什么 SQL），
    生产环境要关掉，否则日志量爆炸。
"""
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from finassist.conf.config import settings

# 1 定义两个变量
# 引擎对象，执行操作对象
engine: AsyncEngine | None = None
# session会话对象
# sqlalchemy创建数据库会话对象以工厂形式创建
async_session: async_sessionmaker[AsyncSession]

# 2 创建两个方法
# 1 创建上面两个对象
# 异步
def init_db_engine():
    global engine, async_session
    # 创建引擎对象
    engine = create_async_engine(
        # 数据库路径，必须要有
        settings.database_url,
        # 可选 输出底层sql语句
        echo=False,  # 金融会话含金额和对象信息，默认不输出 SQL 参数。
    )
    # session会话对象  以工厂形式创建
    async_session = async_sessionmaker(
        engine,
    )

# 2 关闭资源
async def close_db_engine():
    await engine.dispose()

# 测试方法
async def test():
    init_db_engine()
    # 写法特殊：固定的
    async with async_session() as session:
        result = await session.execute(text("select 1"))
        print(result.fetchone())
    await close_db_engine()

if __name__ == '__main__':
    asyncio.run(test())


