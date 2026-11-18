"""
共享的异步 HTTP 客户端：用来调「商城中台」的接口。

■ 它在哪
    api/app.py 的 lifespan 启动时 init_http_client()，关机时 close_http_client()；
    knowledge/provider.py 里的 ApiProductProvider 用它去请求
    business_api_base_url 对应的真实/模拟商城接口。

■ ※ 为什么不在每次请求里 new 一个 AsyncClient？
    AsyncClient 内部维护连接池。每次 new 一个再关掉，等于每次都重新做 TCP 握手
    + TLS 握手，高并发下延迟和端口占用都会很难看。
    全局一个客户端 = 连接复用。这也是官方文档推荐的做法。

■ timeout=10.0
    10 秒超时。※ 一定要设：不设的话对方接口挂住，你的请求会一直等着，
    最后把整个 FastAPI 的 worker 拖死。

■ 谁负责关它？
    只有 lifespan 里的 close_http_client()。业务代码里**不要**调 aclose()，
    否则下一个请求会拿到一个已经关闭的客户端，报 "Cannot send a request,
    as the client has been closed."

■ 顺带一提
    文件里注释掉的 requests 是同步库，放进 async 函数里会阻塞事件循环，
    所以这里必须用 httpx 的异步版本。
"""
import asyncio

from httpx import AsyncClient

## 第一种 使用python内置模块requests
# import requests
# requests.get()

# 异步操作方便
## 第二种 httpx实现
http_client: AsyncClient | None = None

# 创建http_client方法
def init_http_client():
    global http_client
    http_client = AsyncClient(timeout=10.0)

# 关闭http_client方法
async def close_http_client():
    await http_client.aclose()

# 测试方法
async def test():
    init_http_client()
    result = await http_client.get(
        "http://127.0.0.1:18081/orders/A20260408002/status")
    print(result.json())
    await close_http_client()

if __name__ == "__main__":
    asyncio.run(test())