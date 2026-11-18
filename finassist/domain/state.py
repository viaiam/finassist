"""
domain/state.py —— 对话状态（整个项目的「记忆体」，最核心的数据结构）

■ 它是什么
    一个用户 = 一条 DialogueState，里面装着他所有聊天记录 + 所有任务进度。
    每轮对话的固定三步（见 service/dialogue_service.py::run）：
        repository.load_state(sender_id)  →  反序列化成 DialogueState 对象
                    ↓  engine 在对象上增删改（加 turn、填槽、推步骤）
        repository.save_state(state)      →  序列化成 JSON 写回 MySQL

■ 结构速查（记住这棵树，后面所有代码都在操作它）
    DialogueState
    ├─ sender_id : str                        用户 id
    ├─ shared    : SharedState                ← 跨任务共享，任务切换/取消都不清空
    │   ├─ focused_object : FocusedObject|None     「我这一单」指的就是它
    │   └─ sessions       : list[Session]          会话们（60 分钟不活跃就切新会话）
    │       └─ turns      : list[Turn]             一轮轮的问答
    │           ├─ user_message : UserMessage
    │           └─ bot_message  : list[BotMessage]
    └─ tasks     : TaskState                  ← 任务流程专属
        ├─ active : TaskInstance|None              当前在办的任务
        └─ paused : list[TaskInstance]             被插队压下去的暂停任务

■ 三个最容易踩的坑（正文里都标了 ※）
    1) 「当前会话」永远是 sessions[-1]，列表空时直接下标会 IndexError；
    2) active 可能是 None，任何 state.tasks.active.xxx 之前都要先判空；
    3) slots 里存的是字符串，jinja2 模板直接 {{ slots.xxx }} 取用。
"""
import time
import uuid
from dataclasses import dataclass, field
from finassist.domain.message import UserMessage, BotMessage
from finassist.lifecycle.models import (
    TaskEvent, TaskRef, TaskStarted, TaskSwitched, TaskResumed, TaskCanceled,
)

# 一轮对话，一个问题对应一个或者多个回答
@dataclass
class Turn:
    turn_id: str
    # 用户提问
    user_message: UserMessage
    # 客服回复
    bot_message: list[BotMessage]=field(default_factory=list)

# 会话对象
@dataclass
class Session:
    # session的id，区别不同session
    session_id: str
    # session创建时间戳
    started_at: float
    # session最后一次活跃时间
    last_activity_at: float
    # 关闭时间
    closed_at: float | None = None
    # 每个session会话多轮对话
    turns:list[Turn]=field(default_factory=list)

# 对象类型消息
@dataclass
class FocusedObject:
    type:str #  order   product
    id:str
    title:str | None=None
    attributes:dict=field(default_factory=dict)

# 三种能力都有数据：任务流程、知识问答、闲聊
@dataclass
class SharedState:
    # 对象类型消息
    focused_object: FocusedObject | None = None
    # 多个会话数据
    sessions: list[Session] = field(default_factory=list)

    # ------------------------------------------------------------------
    # 新建会话：追加到列表末尾（所以 sessions[-1] 永远是「当前会话」）
    # ------------------------------------------------------------------
    def create_session(self):
        now = time.time()
        session = Session(
            session_id=str(uuid.uuid4()),
            started_at=now,
            last_activity_at=now
        )
        #放到sessions列表
        self.sessions.append(session)


# 某个任务流程步骤相关数据
@dataclass
class TaskInstance:
    # 流程id，对应yaml文件  refund_request
    flow_id: str
    # 步骤id ,比如 start
    step_id: str | None = None
    # 当前任务id
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # task_id: str | None = None
    # 槽位数据字典  {order_number : a10098765}
    slots: dict= field(default_factory=dict)

    # 转成对外（事件里）使用的轻量引用，只带 id，不带槽位
    # ------------------------------------------------------------------
    # 转成对外事件用的轻量引用（只带 id，不带槽位）
    # 对应 lifecycle/models.py 的 TaskRef，见那里「为什么分两种」的说明
    # ------------------------------------------------------------------
    def get_task_ref(self) -> TaskRef:
        return TaskRef(
            task_id=self.task_id,
            flow_id=self.flow_id,
        )


# 任务流程特有数据，流程步骤数据
@dataclass
class TaskState:
    # 当前正在运行（活跃）的任务
    active: TaskInstance | None = None
    # 中断（暂停）的任务
    paused: list[TaskInstance] = field(default_factory=list)

    # {"command": "start_flow", "flow": "<flow_id>"}
    ## 判断当前是否有 active，如果没有直接放
    ## 如果有，把当前任务暂停，把新任务放到 active 里面
    # ======================================================================
    # 【命令 1】start_flow —— 开始一个新任务
    #   手上空着       → TaskStarted
    #   手上有活在办   → 旧的压进 paused + TaskSwitched
    # 调用方：task/command/command_processor.py::_execute_command()
    #         （处理 {"command": "start_flow", "flow": "<flow_id>"} 时）
    # ======================================================================
    def start_task(self, task: TaskInstance) -> TaskEvent:
        if self.active:
            # 先记下旧的 active 引用，再把旧任务压栈
            previous = self.active.get_task_ref()
            self.paused.append(self.active)
            self.active = task
            return TaskSwitched(
                previous=previous,
                current=self.active.get_task_ref(),
            )
        # 没有活跃任务
        self.active = task
        return TaskStarted(task=self.active.get_task_ref())

    # 恢复任务
    ## {"command": "resume_task", "task_id": "<task_id>"}
    # ======================================================================
    # 【命令 2】resume_task —— 恢复一个被暂停的任务（按 task_id 从 paused 里摘）
    # ※ 恢复时如果手上还有活，照样把旧任务压栈（走 TaskSwitched），
    #   以此保证「任何时刻最多一个 active」这个不变量不被破坏。
    # ======================================================================
    def resume_task(self, task_id: str) -> TaskEvent:
        target_task = None
        # 1 从暂停列表里把要恢复的任务摘出来
        for index, task in enumerate(self.paused):
            if task.task_id == task_id:
                target_task = self.paused.pop(index)
                break

        # 2 没找到说明 task_id 不合法
        if target_task is None:
            raise Exception(f"Task not found in paused tasks: {task_id}")

        # 3 找到了：当前有活跃任务就先把它压进 paused
        if self.active:
            previous = self.active.get_task_ref()
            self.paused.append(self.active)
            self.active = target_task
            return TaskSwitched(
                previous=previous,
                current=target_task.get_task_ref(),
            )
        self.active = target_task
        return TaskResumed(task=target_task.get_task_ref())

    # 取消任务
    ## {"command": "cancel_task", "task_id": "<task_id>"}
    ## 先在 active 里找，再在 paused 里找，找到就从列表里摘掉
    # ======================================================================
    # 【命令 3】cancel_task —— 取消任务
    # ※ active 和 paused 都要找：用户完全可能说「把刚才那个退款取消掉」，
    #   而那个退款正躺在 paused 里。
    # ======================================================================
    def cancel_task(self, task_id: str) -> TaskEvent:
        # 1 活跃任务
        if self.active and self.active.task_id == task_id:
            task_ref = self.active.get_task_ref()
            self.active = None
            return TaskCanceled(task=task_ref)

        # 2 暂停任务
        for index, task in enumerate(self.paused):
            if task.task_id == task_id:
                self.paused.pop(index)
                return TaskCanceled(task=task.get_task_ref())

        # 3 都没找到
        raise Exception(f"Task not found: {task_id}")


@dataclass
class DialogueState:
    # 用户id
    sender_id: str
    # 三种能力都有数据：任务流程、知识问答、闲聊
    shared: SharedState=field(default_factory=SharedState)
    # 任务流程特有数据，流程步骤数据
    tasks: TaskState=field(default_factory=TaskState)
    # 清空任务数据
    # ------------------------------------------------------------------
    # 清空任务相关数据（会话过期时调用）
    # ※ 连 focused_object 一起清 —— 会话都换了，还留着「上次那个订单」
    #   只会让新会话莫名其妙地查起旧订单。
    # 调用方：engine/dialogue_engine.py::_prepare_current_session()
    # ------------------------------------------------------------------
    def clear_task(self):
        self.tasks.active = None
        self.tasks.paused.clear()
        self.shared.focused_object = None
