"""
对话引擎：整条链路的「总调度台」。**读源码建议从这里开始第二遍。**

    @Aythor:Bee
    @Time:2026/11/13
    @Desc:消息处理总入口。
          文本消息：意图识别 → 校验 → 按方向分派（任务流程 / 知识检索 / 闲聊）
          对象消息：写 focused_object → 能填槽位就填 → 否则澄清

■ 它在哪
    api/chat_router.py → service/dialogue_service.py → **DialogueEngine.process_message()**
      → plan/turn_planner.py（猜意图）
      → plan/turn_plan_validator.py（检查猜得对不对）
      → task/task_handler.py 或 knowledge/ 或 chitchat/（真正干活）

■ 一句话总结它的工作
    「先判断用户说的是什么类型，再决定把这活派给谁，最后把这一轮记进历史。」

■ 五件依赖，各管一段（都在 engine/builder.py 里装配好传进来）

    | 依赖                | 职责                                        |
    |---------------------|---------------------------------------------|
    | turn_planner        | 调 LLM，把一句话变成结构化的 TurnPlan        |
    | turn_plan_validator | 用确定性规则复查 LLM 的结论，防幻觉          |
    | task_handler        | 多轮任务：改状态 + 推流程 + 出话术           |
    | knowledge_handler   | 单轮问答：查数据 + 让 LLM 组织语言           |
    | chit_chat           | 既不是任务也不是知识，就当聊天处理           |
    | clarify_response    | 上面都不成立时的兜底，反问用户               |

■ ※ 关键设计：三条分支是怎么分出来的
    LLM 只负责「分类」，不负责「执行」。它输出的 TurnPlan 里
    三个字段 task / knowledge / chitchat 最多只有一个非空，
    所以下面 4.1 / 4.2 / 4.3 是三个互斥的 if，最后一个直接 return 兜底。

    ※ 为什么要多一层 validator？
      模型会瞎编：编出不存在的 flow_id、编出没有的任务 id。
      与其在执行阶段到处判空，不如先集中校验一次，不合格就转澄清。

■ ※ 为什么对象消息不走 LLM
    用户在界面上点了一张商品卡片，消息里已经有 type/id 了，
    再让模型去猜「这是商品」纯属浪费，还可能猜错。
    所以 MessageType.OBJECT 走一条完全确定的规则分支（见文件末尾的
    _is_can_fill_slots：还得当前步骤正好在收这个槽位，才允许自动填）。

■ 状态是怎么被改的
    process_message 拿到的 state 是引用，全程「就地修改」：
    过期判断会改 session、任务分支会改 tasks、最后统一 append 一条 Turn。
    调用方（DialogueService）不需要接收返回值，它直接存这同一个对象就行。
"""
import time
import uuid
from dataclasses import asdict

from finassist.chitchat.chit_chat import ChitChatHandler
from finassist.clarify.clarify_response import ClarifyResponse
from finassist.domain.message import (
    UserMessage, ProcessResult, BotMessage, MessageType,
)
from finassist.domain.state import DialogueState, Turn, FocusedObject
from finassist.knowledge.knowledge_handler import KnowledgeHandler
from finassist.plan.command import SetSlotsCommand
from finassist.plan.turn_plan_validator import TurnPlanValidator
from finassist.plan.turn_planner import TurnPlanner
from finassist.prompts.models import (
    TurnPlan, TurnPlanValidationResult, ClarifyReason,
)
from finassist.task.flow.models import FlowCatalog
from finassist.task.flow.steps import CollectSlotStep
from finassist.task.flowexecutor.flow_executor import OBJECT_TYPE_TO_SLOT
from finassist.task.task_handler import TaskHandler


class DialogueEngine:

    MALICIOUS_INTENT_RESPONSE = (
        '我不能协助伤害他人或策划暴力行为。请远离可能造成伤害的物品，'
        '并立即联系当地紧急服务或可信任的人。'
    )

    def __init__(self,
                 turn_planner: TurnPlanner,
                 turn_plan_validator: TurnPlanValidator,
                 task_handler: TaskHandler,
                 chit_chat: ChitChatHandler,
                 clarify_response: ClarifyResponse,
                 knowledge_handler: KnowledgeHandler,
                 flow_catalog: FlowCatalog):
        self.turn_planner = turn_planner
        self.turn_plan_validator = turn_plan_validator
        # 任务流程方向的所有活都交给 TaskHandler（command → lifecycle → flowExecutor）
        self.task_handler = task_handler
        # 闲聊
        self.chit_chat = chit_chat
        # 校验失败 / 对象消息对不上时，统一走澄清
        self.clarify_response = clarify_response
        # 知识检索（查商品 / 订单 / 政策）
        self.knowledge_handler = knowledge_handler
        # yaml 解析结果，builder 里建好传进来；对象消息判断槽位要用到它
        self.flow_catalog = flow_catalog

    async def process_message(self,
                              state: DialogueState,
                              user_message: UserMessage) -> ProcessResult:
        # 1 准备当前 session（没有就建，过期就关旧的建新的）
        self._prepare_current_session(state)

        # 2 按消息类型分派
        if user_message.type == MessageType.TEXT:
            messages: list[BotMessage] = await self._execute_text_message(state, user_message)
        else:
            messages: list[BotMessage] = await self._execute_object_message(state, user_message)

        # 3 提交本轮对象（放进去的 bot_message 就是刚才生成的那几条）
        turn = Turn(
            turn_id=str(uuid.uuid4()),
            user_message=user_message,
            bot_message=messages,
        )
        state.shared.sessions[-1].turns.append(turn)

        # 4 封装处理结果，返回给 service
        return ProcessResult(
            sender_id=user_message.sender_id,
            message_id=user_message.message_id,
            messages=messages,
        )

    # 准备当前 session
    def _prepare_current_session(self, state: DialogueState):
        now = time.time()

        # 1 一个 session 都没有：直接建，后面的过期判断没得判断
        if not state.shared.sessions:
            state.shared.create_session()
            return

        # 2 取最近一个 session，判断是否过期（60 分钟不活跃）
        current_session = state.shared.sessions[-1]
        if now - current_session.last_activity_at > 60 * 60:
            # 过期：标记关闭时间、清空任务数据（含 focused_object）、开新会话
            current_session.closed_at = now
            state.clear_task()
            state.shared.create_session()
        else:
            # 没过期：续一下活跃时间
            current_session.last_activity_at = now

    # 文本类型消息处理
    async def _execute_text_message(self,
                                    state: DialogueState,
                                    user_message: UserMessage) -> list[BotMessage]:
        # 1 意图识别
        turn_plan: TurnPlan = await self.turn_planner.plan(
            state=state,
            user_message=user_message,
            flow_catalog=self.flow_catalog,
        )

        # 安全分类命中时直接拒绝，确保不会继续查询金融数据或执行任务。
        if turn_plan.malicious_intent:
            return [BotMessage(text=self.MALICIOUS_INTENT_RESPONSE)]

        # 2 校验
        validation: TurnPlanValidationResult = self.turn_plan_validator.validate(
            turn_plan=turn_plan,
            state=state,
            flow_catalog=self.flow_catalog,
        )

        # 3 校验不过：走澄清组件（LLM 结合历史说一句"你要办什么"）
        if not validation.valid:
            return await self.clarify_response.response(
                reason=validation.reason,
                state=state,
                user_message=user_message,
            )

        # 4 校验通过，按识别到的方向分派
        ## 4.1 任务流程
        if turn_plan.task is not None:
            return await self.task_handler.handle(
                commands=turn_plan.task.commands,
                state=state,
                user_message=user_message,
            )

        ## 4.2 知识检索：查商品 / 订单 / 政策，取数 + 让 LLM 组织话术
        if turn_plan.knowledge is not None:
            return await self.knowledge_handler.handle(
                knowledge_intents=turn_plan.knowledge.intents,
                state=state,
                user_message=user_message,
            )

        ## 4.3 闲聊
        return await self.chit_chat.chit_chat(
            state=state,
            user_message=user_message,
        )

    # 对象类型消息处理
    async def _execute_object_message(self,
                                      state: DialogueState,
                                      user_message: UserMessage) -> list[BotMessage]:
        # 1 对象信息先落到 focused_object（"我这一单" 的指代就靠它）
        if user_message.object is None:
            return await self.clarify_response.response(
                reason=ClarifyReason.MISSING_FOCUSED_OBJECT,
                state=state,
                user_message=user_message,
            )
        state.shared.focused_object = FocusedObject(**asdict(user_message.object))

        # 2 当前任务正好缺这个槽位：补一条 set_slots，让流程继续往下走
        slot_name = self._object_slot_for_current_step(state)
        if slot_name:
            value = user_message.object.attributes.get(slot_name) or user_message.object.id
            return await self.task_handler.handle(
                commands=[SetSlotsCommand(
                    command="set_slots",
                    slots={slot_name: value},
                )],
                state=state,
                user_message=user_message,
            )

        # 3 对不上（没活跃任务 / 类型不匹配 / 槽位已经填过）：告诉用户接下来能干嘛
        return await self.clarify_response.response(
            reason=ClarifyReason.OBJECT_REQUIRES_INTENT,
            state=state,
            user_message=user_message,
        )

    # 判断"这个对象"能不能给当前任务填空
    def _is_can_fill_slots(self, state: DialogueState) -> bool:
        # 保留旧方法名，统一复用当前步骤的对象槽位判断。
        return self._object_slot_for_current_step(state) is not None

    def _object_slot_for_current_step(self, state: DialogueState) -> str | None:
        """按当前 collect 步骤选择对象槽位；交易卡片可填账户或关联流水。"""
        if state.tasks.active is None or state.shared.focused_object is None:
            return None
        focused_object = state.shared.focused_object
        flow = self.flow_catalog.get_flow_by_id(state.tasks.active.flow_id)
        step = flow.get_step_by_id(state.tasks.active.step_id)
        if not isinstance(step, CollectSlotStep) or state.tasks.active.slots.get(step.slot_name):
            return None
        if focused_object.type == 'transaction':
            if step.slot_name in ('account_no', 'related_transaction_no'):
                return step.slot_name
            return None
        return step.slot_name if OBJECT_TYPE_TO_SLOT.get(focused_object.type) == step.slot_name else None
