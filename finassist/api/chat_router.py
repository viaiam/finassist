"""
HTTP 接口层：把「HTTP 世界」翻译成「python 对象世界」。

■ 它在哪
    最外层。浏览器/前端 → **本文件** → service/dialogue_service.py → engine/

■ 提供两个接口

    | 方法 | 路径                 | 作用                       |
    |------|----------------------|----------------------------|
    | POST | /api/chat            | 发一条消息，拿回客服回复   |
    | GET  | /api/chat/history    | 拉某个用户的历史对话       |

■ ※ 本文件最核心的一件事：两套模型互相转换
    api/schemas.py 定义的是「对外的」模型（ChatRequest/ChatResponse），
    domain/message.py 定义的是「对内的」模型（UserMessage/ProcessResult）。

    为什么要分两套？
      对外模型跟着接口走：前端要什么字段就给什么字段，将来改接口不影响业务逻辑；
      对内模型跟着业务走：可以自由重构，不担心破坏接口契约。
      代价就是要写转换函数 —— 也就是下面那三个下划线开头的 _build_xxx。

        请求方向：ChatRequest  --_build_user_message-->  UserMessage
        响应方向：ProcessResult --_build_response_message--> ChatResponse
        对象字段：MessageObject --> ChatObject（_build_chat_object）

■ ※ 为什么路由函数这么薄
    它不写任何业务判断，只做「转换 → 转发 → 转换」。
    ※ 好处：想给接口加鉴权、限流、日志，都只动这一层；
      业务逻辑一行不用碰。这也是分层最实在的收益。

■ 依赖注入
    参数写 dialogue_service: DialogueService = Depends(get_dialogue_service)，
    FastAPI 会去 api/dependencies.py 里把这棵依赖树（session → repository → service）
    自动造好递进来。路由里因此看不到任何 new 对象的代码。
"""
import uuid
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends

from finassist.api.dependencies import get_dialogue_service, get_repository
from finassist.api.schemas import (ChatRequest, ChatResponse, ChatMessage, ChatObject,
                                            HistoryMessage, HistoryResponse, NewSessionRequest)
from finassist.domain.message import UserMessage, ProcessResult, MessageType, MessageObject
from finassist.domain.state import DialogueState
from finassist.repository.dialogue_repository import DialogueRepository
from finassist.service.dialogue_service import DialogueService

chat_router = APIRouter()


@chat_router.post("/api/chat")
async def chat(chat_request:ChatRequest,
       dialogue_service:DialogueService=Depends(get_dialogue_service)
                                    )->ChatResponse:
    # 参数 chat_request: 由 FastAPI 自动把请求体 JSON 解析成 ChatRequest
    # 参数 dialogue_service: 由 Depends 自动注入（见 api/dependencies.py）

    # 1 数据模型转换：api 层 ChatRequest --> 对内 UserMessage
    user_message:UserMessage = _build_user_message(chat_request)

    # 2 调用service方法实现
    process_result:ProcessResult = await dialogue_service.run(user_message)

    # 3 把service层返回数据 ProcessResult --> api层类型 ChatResponse
    chat_response:ChatResponse = _build_response_message(process_result)
    return chat_response

@chat_router.get("/api/chat/history")
async def chat_history(sender_id:str,
        session_id: str | None = None,
        repository:DialogueRepository=Depends(get_repository)
                                )->HistoryResponse:
    """获取指定用户的聊天历史（课件 02 §3.1.2）

    从 dialogue_states 表读回该用户的状态，把它保存的所有 session/turn
    展开成 user / bot 交替的消息列表返回。
    """
    state:DialogueState = await repository.load_state(sender_id)

    messages:list[HistoryMessage]=[]
    sessions = state.shared.sessions
    if session_id:
        sessions = [session for session in sessions if session.session_id == session_id]
    for session in sessions:
        for turn in session.turns:
            # 一轮对话：先用户提问，再客服回复（可能多条）
            messages.append(HistoryMessage(
                role="user",
                text=turn.user_message.text,
                object=_build_chat_object(turn.user_message.object),
            ))
            for bot_message in turn.bot_message:
                messages.append(HistoryMessage(
                    role="bot",
                    text=bot_message.text,
                    object=_build_chat_object(bot_message.object),
                ))

    return HistoryResponse(sender_id=sender_id, messages=messages)


@chat_router.get('/api/chat/status')
async def chat_status(sender_id: str,
        repository: DialogueRepository = Depends(get_repository)):
    """返回当前会话及正在等待/已暂停的任务摘要，不泄露槽位内容。"""
    state = await repository.load_state(sender_id)
    session = state.shared.sessions[-1] if state.shared.sessions else None

    def task_summary(task):
        if task is None:
            return None
        return {
            'task_id': task.task_id,
            'flow_id': task.flow_id,
            'step_id': task.step_id,
            'collected_slots': sorted(task.slots),
        }

    return {
        'sender_id': sender_id,
        'session': ({'session_id': session.session_id,
                     'started_at': session.started_at,
                     'last_activity_at': session.last_activity_at}
                    if session else None),
        'active_task': task_summary(state.tasks.active),
        'paused_tasks': [task_summary(task) for task in state.tasks.paused],
        'resume_hint': '可以发送“继续刚才的任务”恢复最近暂停的任务。'
            if state.tasks.paused else None,
    }


@chat_router.post('/api/chat/sessions')
async def create_chat_session(request: NewSessionRequest,
        repository: DialogueRepository = Depends(get_repository)):
    """结束当前会话并开启新会话，同时清除旧任务上下文。"""
    state = await repository.load_state(request.sender_id)
    if state.shared.sessions and state.shared.sessions[-1].closed_at is None:
        state.shared.sessions[-1].closed_at = time.time()
    state.clear_task()
    state.shared.create_session()
    await repository.save_state(state)
    session = state.shared.sessions[-1]
    return {'sender_id': request.sender_id,
            'session_id': session.session_id,
            'started_at': session.started_at}


@chat_router.get('/api/chat/sessions')
async def list_chat_sessions(sender_id: str,
        repository: DialogueRepository = Depends(get_repository)):
    """按最近活跃时间倒序返回会话摘要，供前端浏览历史会话。"""
    state = await repository.load_state(sender_id)
    sessions = []
    for _, session in sorted(
            enumerate(state.shared.sessions),
            key=lambda pair: (pair[1].last_activity_at, pair[0]),
            reverse=True):
        message_count = sum(1 + len(turn.bot_message) for turn in session.turns)
        first_turn = session.turns[0] if session.turns else None
        preview = (first_turn.user_message.text or
                   (first_turn.user_message.object.title
                    if first_turn.user_message.object else None)) if first_turn else None
        sessions.append({
            'session_id': session.session_id,
            'started_at': session.started_at,
            'last_activity_at': session.last_activity_at,
            'message_count': message_count,
            'preview': preview,
            'has_messages': bool(session.turns),
        })
    return {'sender_id': sender_id, 'sessions': sessions}


def _build_chat_object(obj:MessageObject | None)->ChatObject | None:
    """domain 层 MessageObject --> api 层 ChatObject"""
    return ChatObject(**asdict(obj)) if obj else None


# ChatRequest --> UserMessage（api 层 → 对内）
def _build_user_message(chat_request:ChatRequest)->UserMessage:
    return UserMessage(
        sender_id=chat_request.sender_id,
        # 消息id，判断存在使用，不存在生成
        message_id=chat_request.message_id
               if chat_request.message_id else str(uuid.uuid4()),
        type=MessageType.TEXT if chat_request.text
                              else MessageType.OBJECT,
        text=chat_request.text,
        object=MessageObject(
            id=chat_request.object.id,
            type=chat_request.object.type,
            title=chat_request.object.title,
            attributes=chat_request.object.attributes,
        ) if chat_request.object else None
    )


# ProcessResult --> ChatResponse（对内 → api 层）
def _build_response_message(process_result:ProcessResult)->ChatResponse:
    # list[BotMessage] --》 list[ChatMessage]
    return ChatResponse(
        sender_id=process_result.sender_id,
        message_id=process_result.message_id,
        messages=[
            # ChatMessage对象
            ChatMessage(
                text=bot_message.text,
                object=ChatObject(
                    **asdict(bot_message.object)
                ) if bot_message.object else None
            )
            for bot_message in process_result.messages
        ]
    )
