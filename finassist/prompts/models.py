"""
prompts/models.py —— 意图识别的结果模型（TurnPlan 家族）

■ 它是什么
    定义「大模型让我们干哪件事」的数据结构。一轮对话模型只回一个 JSON，
    反序列化后就变成这里的 TurnPlan：

        TurnPlan
        ├─ task      : TaskTurnPlan      | None   要我操作业务任务（启停任务、填槽）
        ├─ knowledge : KnowledgeTurnPlan | None   要我查知识库（订单/商品/政策）
        └─ chitchat  : ChitchatTurnPlan  | None   纯闲聊，直接寒暄

    ※ 三者**互斥**，最多一个非 None —— 这是 turn_plan.jinja2 里明确要求的，
      判断顺序是「任务优先」：用户说「我要退款，顺便问下你们几点上班」，
      先启动退款流程，业务问题这轮先不答。
      校验规则见 plan/turn_plan_validator.py。

■ 在调用链中的位置
    prompts/jinja2/turn_plan.jinja2（提示词模板）
        ↓  plan/turn_planner.py::TurnPlanner.plan()  调 LLM 拿 JSON
    TurnPlan.from_dict()  ← 你在这里
        ↓  plan/turn_plan_validator.py::TurnPlanValidator.validate()
    TurnPlanValidationResult
        ↓  engine/dialogue_engine.py::_execute_text_message() 按分支分派
    TaskHandler / KnowledgeHandler / ChitChatHandler

■ 为什么这几个模型在 prompts 包里？
    按职责它们更像 plan 包的产物，但课程跟着课件把它们放在 prompts 下，
    阅读时知道「prompts 包负责提示词 + 提示词产物的建模」即可。

■ 关键概念
    Command        单条业务指令，定义在 plan/command.py（start_flow / set_slots 等）
    intents        知识意图 id 列表，取值见 knowledge/intents.py 的 KNOWLEDGE_INTENTS
    ClarifyReason  校验不通过时，为什么要反问用户 —— 决定反问的话术
"""
from dataclasses import dataclass, field
from enum import Enum

from finassist.plan.command import Command


# ==========================================================================
# 任务型计划：一串命令，按顺序执行
# ==========================================================================
@dataclass
class TaskTurnPlan:
    """形如 {"task": {"commands": [{"command": "start_flow", "flow": "..."}]}}。

    ※ commands 是**有序列表**，CommandProcessor 按顺序逐条执行；
      所以「先启动流程再填槽」这种顺序，是模型在 JSON 里排好的。
    """
    commands: list[Command] = field(default_factory=list)

    @classmethod
    def from_dict(cls, task_data: dict) -> "TaskTurnPlan":
        """把 LLM 返回的 dict 转成对象。这里不做任何容错校验 ——
        字段缺失会直接 KeyError，校验统一交给 TurnPlanValidator。"""
        return cls(commands=[Command.from_dict(command_data)
                             for command_data in task_data['commands']])


# ==========================================================================
# 知识型计划：一串意图 id
# ==========================================================================
@dataclass
class KnowledgeTurnPlan:
    """形如 {"knowledge": {"intents": ["order_info", "refund_policy"]}}。

    ※ 为什么是列表不是单个？
      用户可能一句话问两件事：「这个多少钱，能退吗」。知识处理器会把
      多个意图的结果合并成一次回答（去重顺序见 knowledge/knowledge_handler.py）。
    """
    intents: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, knowledge_data: dict) -> "KnowledgeTurnPlan":
        return KnowledgeTurnPlan(knowledge_data['intents'])


# ==========================================================================
# 闲聊型计划：没有参数
# ==========================================================================
@dataclass
class ChitchatTurnPlan:
    """纯闲聊。之所以留一个空类而不是用 None 表示，
    是为了和「task/knowledge 为 None」保持对称，分派时写起来更整齐。"""
    pass


# ==========================================================================
# 一轮的总计划
# ==========================================================================
@dataclass
class TurnPlan:
    """三个分支最多只有一个非 None（互斥），由提示词约束 + validator 兜底。"""
    task: TaskTurnPlan | None = None
    knowledge: KnowledgeTurnPlan | None = None
    chitchat: ChitchatTurnPlan | None = None

    @classmethod
    def from_dict(cls, plan_data: dict) -> "TurnPlan":
        """按 key 是否存在（非 None）逐个构造。

        ※ 这里的判断写成 plan_data['task'] is not None，
          所以 LLM 少给某个 key 会 KeyError；给了 null 才是「这条分支没选中」。
          turn_plan.jinja2 的输出结构里三个 key 都是必填的（可以为 null）。
        """
        return cls(
            task=TaskTurnPlan.from_dict(plan_data['task'])
                if plan_data['task'] is not None else None,

            knowledge=KnowledgeTurnPlan.from_dict(plan_data['knowledge'])
                         if plan_data['knowledge'] is not None else None,

            chitchat=ChitchatTurnPlan()
                       if plan_data['chitchat'] is not None else None
        )


# ==========================================================================
# 反问答疑：为什么要问用户
# ==========================================================================
class ClarifyReason(Enum):
    """校验失败的原因枚举。每个值都在 clarify/clarify_response.py::build_reason
    里对应一句中文反问。想加新话术，就往这里加枚举 + 在那里加 case。

    下面逐个说明「什么情况下会用到它」：
    """
    # 既没有正在进行的任务，也识别不出要启动哪个流程 ——「您想办理什么业务？」
    MISSING_TRACK = "missing_track"
    # 同时命中多条流程，无法确定走哪条 ——「您是想查订单还是查物流？」
    MULTIPLE_TRACKS = "multiple_tracks"
    # 归类成任务型，但 commands 是空的 ——「您具体想办理什么？」
    MISSING_TASK_COMMANDS = "missing_task_commands"
    # 归类成知识型，但 intents 是空的 ——「您想问什么？」
    MISSING_KNOWLEDGE_INTENT = "missing_knowledge_intent"
    # 该意图要求先有聚焦对象（如 order_info 要求先点一张订单卡片）
    MISSING_FOCUSED_OBJECT = "missing_focused_object"
    # 收到对象消息，但没说明想干什么（只看卡片不说话，不知道是要查还是退款）
    OBJECT_REQUIRES_INTENT = "object_requires_intent"
    # 命令本身不合法：命令名不认识、flow_id 不存在、task_id 不在 paused 里
    INVALID_TASK_COMMAND = "invalid_task_command"
    # 意图 id 不在 KNOWLEDGE_INTENTS 里
    UNKNOWN_KNOWLEDGE_INTENT = (
        "unknown_knowledge_intent"
    )


# ==========================================================================
# 校验结果
# ==========================================================================
@dataclass
class TurnPlanValidationResult:
    """valid=False 时 reason 必有值，engine 拿它去生成反问话术。

    见 plan/turn_plan_validator.py（产出）与
       engine/dialogue_engine.py（消费：走 ClarifyResponse.response）。
    """
    valid: bool
    reason: ClarifyReason | None = None
