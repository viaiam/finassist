"""
流程执行器：把 user_flows.yml 画的那张图，真正「走」一遍。

    @Aythor:Bee
    @Time:2026/11/13
    @Desc:任务流程执行器。state 里 active 指向哪个步骤，就从这个步骤开始往下推，
          一直推到"需要用户输入"（collect 没拿到槽位）或者"流程结束"（end）为止。

■ 它在哪
    engine/dialogue_engine.py → task/task_handler.py → **FlowExecutor.execute()**
    它是「任务方向」的最后一环：命令已经改完状态，这里负责把剩下的步骤跑完。

■ 核心思想：状态机 + 断点续跑
    DialogueState 里的 tasks.active 就是「程序计数器」：
        active.flow_id  走哪张图
        active.step_id  停在哪一步
        active.slots    已经攒到哪些数据

    每一轮对话只做两件事：
        1) 从 active.step_id 开始往下走，
        2) 走到「必须等用户说话」或者「图走完了」就停下，把 step_id 存回去。

    ※ 这就是为什么多轮对话能接上：机器人不记得上下文，但数据库里的 step_id 记得。
      下一次用户再说话，同一个 step_id 接着跑。

■ 五类步骤各自干什么（对应 task/flow/steps.py）

    | type     | 做什么                              | 会不会产生回复 |
    |----------|-------------------------------------|----------------|
    | start    | 占位，只是一个入口标记              | 否             |
    | response | 用模板渲染一句话                    | 是             |
    | collect  | 要一个槽位；要不到就反问并停住      | 要到了不产生，要不到才反问 |
    | action   | 调中台接口，把结果写进 slots        | 否             |
    | end      | 清掉 active，任务结束               | 否             |

■ 一次完整走查（以 order_status_query 为例，看 yaml 会更好懂）

    用户说「我要查订单状态」
      → engine 识别出 start_flow，CommandProcessor 把 active 设成
         (order_status_query, start)，slots 为空
      → 进入本文件循环：
         第 1 圈 step=start                → 推进到 ask_order_number
         第 2 圈 step=collect(order_number) → slots 里没有 → 渲染模板
                                            「请告诉我你的订单号。」→ return
         本轮结束，active.step_id 仍是 ask_order_number，已存库

    用户接着说「A1001」
      → 模型输出 set_slots(order_number=A1001)，slots 被写上
      → 进入本文件循环，从 ask_order_number 开始：
         第 1 圈 step=collect(order_number) → 这次有值了 → 推进到 lookup_order_status
         第 2 圈 step=action               → 调中台，把 order_status/order_summary 写进 slots
                                          → 推进到 show_order_status
         第 3 圈 step=response             → 渲染出「订单 A1001 当前状态是：已发货…」
                                          → 推进到 end
         第 4 圈 step=end                  → active = None → return
      → 任务结束，之后再说话就是新的一轮

■ ※ 为什么每圈都要重新取 flow / step
    因为 action 步骤可能改 slots、_run_next_step 会改 step_id，
    每一圈看到的都可能是新状态，缓存下来必错。

■ 三个防御
    MAX_STEPS_PER_TURN = 100   → 防 yaml 写出环（A→B→A）把请求卡死
    active is None 的二次判断   → 上一步可能是 end，把 active 清掉了
    _get_next_value 返回 None   → 条件都不成立又没写 else，直接报错而不是静默结束
"""
from finassist.domain.message import BotMessage, UserMessage
from finassist.domain.state import DialogueState
from finassist.task.action.action_runner import ActionRunner
from finassist.task.action.base import ActionCall, ActionResult
from finassist.task.flow.links import FlowStepLink, ConditionalLink, FallbackLink
from finassist.task.flow.models import FlowCatalog, Flow
from finassist.task.flow.steps import (
    FlowStep, StartFlowStep, ResponseFlowStep, CollectSlotStep,
    ActionFlowStep, EndFlowStep,
)
from finassist.task.response.response_render import ResponseRender


# 对象类型消息的 type 能和哪些槽位对上（订单对象 → order_number 槽位）
OBJECT_TYPE_TO_SLOT = {
    "order": "order_number",
    "product": "product_id",
    # 金融卡片沿用原对象填槽机制，不改变执行器。
    "account": "account_no",
    "loan": "loan_no",
    # 交易卡片主要用于投诉流程填写关联流水号。
    "transaction": "account_no",
}


class FlowExecutor:

    # 一轮最多推多少步：yaml 写出环时靠它兜底，别让请求死循环
    MAX_STEPS_PER_TURN = 100

    def __init__(self, response_render: ResponseRender, action_runner: ActionRunner):
        self.response_render = response_render
        self.action_runner = action_runner

    async def execute(self,
                      state: DialogueState,
                      user_message: UserMessage,
                      flow_catalog: FlowCatalog) -> list[BotMessage]:
        bot_messages: list[BotMessage] = []

        # 没有活跃任务，什么都不用推
        if not state.tasks.active:
            return bot_messages

        for _ in range(self.MAX_STEPS_PER_TURN):
            active = state.tasks.active
            # 上一步可能把 active 清掉了（end 步骤），这里再兜一次
            if active is None:
                return bot_messages

            flow: Flow = flow_catalog.get_flow_by_id(active.flow_id)
            step: FlowStep = flow.get_step_by_id(active.step_id)

            # start：本身不做业务，直接推进
            if isinstance(step, StartFlowStep):
                self._run_next_step(step, state)
                continue

            # response：渲染话术给用户，然后推进
            if isinstance(step, ResponseFlowStep):
                bot_messages.append(await self.response_render.render(
                    template=step.template,
                    state=state,
                    user_message=user_message,
                ))
                self._run_next_step(step, state)
                continue

            # collect：拿槽位。拿到就推进，拿不到就把话权交回用户
            if isinstance(step, CollectSlotStep):
                is_collect = await self._get_collect_data(
                    step, state, user_message, bot_messages,
                )
                if is_collect:
                    self._run_next_step(step, state)
                    continue
                return bot_messages

            # action：调中台接口，把返回的槽位写回 active，再推进
            if isinstance(step, ActionFlowStep):
                # yaml 里 action 字段是个字符串，先包成 ActionCall 交给 ActionRunner
                action_call = ActionCall(action_name=step.action)
                action_result: ActionResult = await self.action_runner.run(
                    action_call=action_call,
                    state=state,
                )
                # 结果只更新槽位，不改流程；下一步 response 就能渲染到真实数据了
                state.tasks.active.slots.update(action_result.slots_update)
                self._run_next_step(step, state)
                continue

            # end：流程结束，清掉 active
            if isinstance(step, EndFlowStep):
                state.tasks.active = None
                return bot_messages

            raise ValueError(f"未知的步骤类型：{step.id} -> {type(step).__name__}")

        # 100 步还没走完，说明 yaml 里大概率有环
        raise ValueError(
            f"流程 {state.tasks.active.flow_id} 超过 {self.MAX_STEPS_PER_TURN} 步仍未结束，请检查 yaml 是否有环"
        )

    # 1 推进到下一步
    def _run_next_step(self, step: FlowStep, state: DialogueState):
        next_step_id = self._get_next_value(step.next, state)
        if next_step_id is None:
            # 条件都不成立又没有 else：这是 yaml 写错了，早点炸出来比默默结束强
            raise ValueError(f"步骤 {step.id} 没有匹配到任何跳转分支（缺 else？）")
        state.tasks.active.step_id = next_step_id

    # 2 取当前步骤的 next 值：无条件 / 条件跳转
    def _get_next_value(self, next_links: list[FlowStepLink], state: DialogueState) -> str | None:
        # 只有一条且不是条件/兜底，就是静态跳转
        if len(next_links) == 1 and isinstance(next_links[0], ConditionalLink) is False:
            return next_links[0].target

        for link in next_links:
            # ConditionalLink 是 if-then
            if isinstance(link, ConditionalLink):
                result = bool(eval(
                    link.condition,
                    {"__builtins__": {}},
                    {"slots": state.tasks.active.slots},
                ))
                if result:
                    return link.target
                continue
            # FallbackLink 是 else
            if isinstance(link, FallbackLink):
                return link.target
        return None

    # 3 收集槽位数据，返回 bool：True 表示有数据可以推进，False 表示要等用户输入
    async def _get_collect_data(self,
                                step: CollectSlotStep,
                                state: DialogueState,
                                user_message: UserMessage,
                                bot_messages: list[BotMessage]) -> bool:
        # 1 先从 state 的 active 里找
        slots: dict = state.tasks.active.slots
        slot_value = slots.get(step.slot_name)

        # 2 找不到，再看这一轮有没有带对象类型消息（"我这一单" 指代）
        if not slot_value:
            self.get_slot_data_from_object_message(step, state)

        # 3 还是没有：渲染 collect 的提示语，等用户回答
        slot_value = state.tasks.active.slots.get(step.slot_name)
        if not slot_value:
            bot_messages.append(await self.response_render.render(
                template=step.template,
                state=state,
                user_message=user_message,
            ))
            return False

        # 4 拿到了
        return True

    # 从对象类型消息（focused_object）里取槽位，取到就写进 active.slots
    def get_slot_data_from_object_message(self, step: CollectSlotStep, state: DialogueState):
        focused_object = state.shared.focused_object
        if focused_object is None:
            return
        # 类型对不上就不管了（订单对象填不了 product_id）
        if OBJECT_TYPE_TO_SLOT.get(focused_object.type) != step.slot_name:
            # 交易卡片可用于投诉关联流水，也可用于交易查询的账户填槽。
            if not (focused_object.type == 'transaction'
                    and step.slot_name in ('account_no', 'related_transaction_no')):
                return
        # 优先用 attributes 里的同名字段，没有就用 id
        value = focused_object.attributes.get(step.slot_name)
        if not value and focused_object.type == 'transaction':
            source_field = ('transaction_no' if step.slot_name == 'related_transaction_no'
                            else 'account_no')
            value = focused_object.attributes.get(source_field)
        value = value or focused_object.id
        if value:
            state.tasks.active.slots[step.slot_name] = value
