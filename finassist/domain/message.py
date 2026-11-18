"""
domain/message.py —— 消息模型（全项目最底层的「名词表」）

■ 它是什么
    定义「一条消息」长什么样。整套系统只认两种输入：
      · 文本消息  text="我想退单"        → MessageType.TEXT
      · 对象消息  object={订单 A1001}    → MessageType.OBJECT

■ 在调用链中的位置
    api/schemas.py 的 ChatRequest / ChatResponse（对外 HTTP 模型）
        ↓  api/chat_router.py 里 _build_user_message / _build_response_message 做转换
    本文件的 UserMessage / BotMessage / ProcessResult（对内业务模型）
        ↓
    domain/state.py 把它们按「轮次」存进 Session.turns
        ↓
    repository/dialogue_repository.py 整体序列化成 JSON 落 MySQL

  ※ 为什么要分两套模型（api 层一套、domain 层一套）？
    对外接口跟着前端走（字段名、是否必填由前端定）；
    对内业务跟着引擎走（引擎不关心 HTTP，单测时也不想依赖 FastAPI）。
    两套之间只有 router 里那两个 _build_* 函数做桥接，
    将来前端改字段，只动 schemas.py 加两个转换函数，engine 一行不用改。

■ 关键概念
    sender_id  用户唯一标识，本项目的「会话主键」——一个 sender 对应库里一条状态记录
    message_id 单条消息的唯一标识，前端没传就由后端生成 uuid
    object     对象类型消息的载体，「我这一单」「这个商品」的指代全靠它落地
"""
from dataclasses import dataclass, field
from enum import Enum

# ==========================================================================
# 对象类型消息
# ==========================================================================
@dataclass
class MessageObject:
    """前端发过来的「一张卡片」：账户、交易、贷款或金融产品卡片。

    示例（用户点了一下订单卡片，前端就发这个）：
        {"type": "order", "id": "A1001", "title": "人体工学办公椅 x1",
         "attributes": {"order_number": "A1001", "amount": "299.00"}}

    ※ type 只有 order / product 两种，且必须和
      task/flowexecutor/flow_executor.py 里的 OBJECT_TYPE_TO_SLOT 对上：
          order   → order_number 槽位
          product → product_id   槽位
      对不上的对象只会被记进 focused_object，不会拿去填槽。
    """
    type: str            # "order" 或 "product"
    id: str              # 订单号 / 商品 id
    title: str | None = None
    attributes: dict = field(default_factory=dict)
    # ※ 上面这行是 dataclass 的经典坑，务必记牢：
    #   写成 attributes: dict = {} 是**错的** —— 默认值在类定义时就创建了一次，
    #   于是所有实例共享同一个 dict，改一个全变。
    #   field(default_factory=dict) 的含义是「每次构造实例时现调一次 dict()」，
    #   保证每个实例拿到各自独立的新字典。list 同理要写 default_factory=list。


# ==========================================================================
# 消息类型枚举
# ==========================================================================
class MessageType(Enum):
    """引擎靠它做第一层分派：文本走意图识别，对象走 focused_object 填槽。

    见 engine/dialogue_engine.py::process_message()：
        type == TEXT   → _execute_text_message()   模型判意图
        type == OBJECT → _execute_object_message() 直接拿卡片填槽
    ※ 前端传什么字符串，router 就映射成哪个枚举值 —— 判断逻辑只有 router 一处。
    """
    TEXT = "text"
    OBJECT = "object"

# ==========================================================================
# 用户输入（api 层 → engine 层的载体）
# ==========================================================================
@dataclass
class UserMessage:
    """一条用户消息。text 与 object 二者必有一个非空（由 router 保证）。

    router 里的判定规则（api/chat_router.py::_build_user_message）：
        传了 text → TEXT；否则 → OBJECT
    ※ 所以「既没 text 也没 object」这类脏请求会在 router 层就被拦掉或当成空文本，
      引擎里不用到处判空。
    """
    sender_id: str
    message_id: str
    # 消息类型： 文本 和 对象
    type: MessageType
    text: str | None = None
    object: MessageObject | None = None

# ==========================================================================
# 客服回复
# ==========================================================================
@dataclass
class BotMessage:
    """一条客服回复（一句话，或一句话 + 一个卡片）。

    ※ 为什么「一轮回复」是 list[BotMessage] 而不是单个？
      一轮里可能说两句：先「好的，现在开始执行订单状态查询」（任务事件话术），
      再「请告诉我你的订单号」（流程推进一步后的追问）。
      见 task/task_handler.py::handle() 最后 messages.extend(flow_messages)。
    """
    text: str | None = None
    object: MessageObject | None = None

# ==========================================================================
# 一轮处理的结果（engine → service → api 层的载体）
# ==========================================================================
@dataclass
class ProcessResult:
    """engine.process_message() 的返回值。

    sender_id / message_id 是把请求里的值原样带回来 ——
    前端靠 message_id 做请求-响应配对（同一用户可能连发多条，靠它区分）。
    """
    sender_id: str
    message_id: str
    messages: list[BotMessage]
