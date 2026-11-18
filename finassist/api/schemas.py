"""
api/schemas.py —— 对外 HTTP 接口的请求/响应模型（Pydantic）

■ 它是什么
    前端看到的数据形状，和内部业务模型（domain/message.py）是**两套**。
    FastAPI 靠这些模型自动做三件事：请求体校验、生成 OpenAPI 文档、响应序列化。

        ChatObject    一个对象卡片（订单/商品）
        ChatRequest   请求：sender_id + 可选 text + 可选 object
        ChatResponse  响应：sender_id + message_id + 消息列表

■ 在调用链中的位置
    HTTP JSON  ──►  ChatRequest  ──► api/chat_router.py::_build_user_message()
                                          ▼
                                    UserMessage（内部模型）
    ... 引擎跑完 ...
    ProcessResult（内部）──► ChatResponse ──► HTTP JSON

  ※ 为什么要两套模型（这是本项目一个刻意的好设计）？
    对外字段要跟着前端变（比如前端想把 text 改名 content，加个 device 字段），
    对内模型要跟着业务稳（engine 里到处都写 message.text）。
    中间用两个 _build_* 函数做隔离，前端改字段时只动本文件 + 两个转换函数。

■ 校验要点
    · text 与 object 至少给一个 —— 具体判定在 router 里（谁都没有就当空文本处理）；
    · message_id 可空：前端不传时由 router 生成 uuid，方便做请求-响应配对。
"""
from pydantic import BaseModel


class ChatObject(BaseModel):
    type: str
    id: str
    title: str | None = None
    attributes: dict = {}

class ChatMessage(BaseModel):
    text: str | None = None
    object: ChatObject | None = None

# {sender_id: "u1001", text: "我想退单"}
# 封装请求数据
class ChatRequest(BaseModel):
    sender_id: str # 用户id
    text: str | None = None # 文本消息
    # 对象类型消息，比如发送订单
    object: ChatObject | None = None
    message_id: str | None = None # 消息唯一标识，需要自己生成 使用uuid

# 封装响应数据
class ChatResponse(BaseModel):
    sender_id: str
    message_id: str
    messages: list[ChatMessage]

###########################
class HistoryMessage(BaseModel):
    role: str # user/bot
    text: str | None = None
    object: ChatObject | None = None


class HistoryResponse(BaseModel):
    sender_id: str
    messages: list[HistoryMessage]


class NewSessionRequest(BaseModel):
    sender_id: str
