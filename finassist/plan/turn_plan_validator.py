"""
意图校验：用确定性代码给 LLM 的结论「复核一遍」，挡掉幻觉。

    @Aythor:Bee
    @Time:2026/11/11
    @Desc:对 llm 意图识别结果进行校验

■ 它在哪
    plan/turn_planner.py 出 TurnPlan → **本文件 validate()**
      → 通过：engine 按方向分派
      → 不通过：engine 转 clarify/clarify_response.py 反问用户

■ 它在防什么（LLM 最常犯的四类错）

    | 模型的错                       | 这里怎么拦                  | 拦下后 reason |
    |--------------------------------|-----------------------------|---------------|
    | 三个方向一个都没给             | active_tracks 为空          | MISSING_TRACK |
    | 同时说要办业务又说要查知识     | active_tracks 长度 > 1      | MULTIPLE_TRACKS |
    | start_flow 编了个不存在的流程  | flow 不在 flow_catalog 里   | INVALID_TASK_COMMAND |
    | resume/cancel 编了个不存在任务 | task_id 不在 active/paused  | INVALID_TASK_COMMAND |

    ※ 这就是「LLM 负责理解，代码负责把关」的分工：
      模型擅长把模糊的人话变成结构，不擅长记住「到底有哪些流程」；
      而这些恰恰是代码用一行 in 判断就能百分百确定的事。

■ ※ 为什么校验失败不直接报错给用户
    因为「校验不过」往往不是用户说错了，而是模型没听懂。
    所以 engine 会转去澄清组件，让另一个提示词结合历史再问一句 ——
    对用户来说只是「客服又问了一遍」，体验是连续的。

■ 三条校验规则的口径（容易踩坑）
    · resume_task：只能在 paused 里找。active 里的任务本来就在跑，不需要 resume。
    · cancel_task：要在 paused + active 里一起找 —— 用户可能取消正在办的那单。
    · knowledge：目前只检查 intents 非空，**不检查** id 是不是真的存在。
      所以 knowledge_handler 里还得再兜一次（见那边的「模型编了字典里没有的意图」）。

■ 返回值
    TurnPlanValidationResult{valid, reason}，reason 是 ClarifyReason 枚举，
    由 clarify 模块负责翻成中文问句 —— 校验层不产生任何面向用户的文案。
"""
from finassist.domain.state import DialogueState
from finassist.plan.command import (
    StartFlowCommand, ResumeTaskCommand, CancelTaskCommand, SetSlotsCommand,
)
from finassist.prompts.models import (
    TurnPlan, TurnPlanValidationResult, ClarifyReason, TaskTurnPlan,
)
from finassist.task.flow.models import FlowCatalog


class TurnPlanValidator:

    def validate(self,
                 turn_plan: TurnPlan,
                 state: DialogueState,
                 flow_catalog: FlowCatalog) -> TurnPlanValidationResult:
        # 对意图识别校验：
        active_tracks: list[str] = []
        if turn_plan.task is not None:
            active_tracks.append("task")
        if turn_plan.knowledge is not None:
            active_tracks.append("knowledge")
        if turn_plan.chitchat is not None:
            active_tracks.append("chitchat")

        # 1 是否识别到内容
        if not active_tracks:
            return TurnPlanValidationResult(
                valid=False,
                reason=ClarifyReason.MISSING_TRACK,
            )

        # 2 是否识别到多个方向（三种能力互斥，只能走一条）
        if len(active_tracks) > 1:
            return TurnPlanValidationResult(
                valid=False,
                reason=ClarifyReason.MULTIPLE_TRACKS,
            )

        # 3 只识别到一个方向，按方向类型分别校验
        active_track = active_tracks[0]
        if active_track == "task":
            return self._validate_task(turn_plan.task, state, flow_catalog)
        if active_track == "knowledge":
            return self._validate_knowledge(turn_plan.knowledge)

        # chitchat 最简单，只要模型给了就放行
        return TurnPlanValidationResult(valid=True)

    # 任务流程校验
    def _validate_task(self,
                       task: TaskTurnPlan,
                       state: DialogueState,
                       flow_catalog: FlowCatalog) -> TurnPlanValidationResult:
        # 1 识别成任务了，但一个命令都没有，等于没说清楚
        if not task.commands:
            return TurnPlanValidationResult(
                valid=False,
                reason=ClarifyReason.MISSING_TASK_COMMANDS,
            )

        # 按命令顺序跟踪目标流程，只允许模型设置该流程真正收集的输入槽位。
        # 查询结果属于服务端事实，不能通过 set_slots 伪造。
        active_flow = state.tasks.active.flow_id if state.tasks.active else None
        for command in task.commands:
            if isinstance(command, StartFlowCommand):
                active_flow = command.flow
            elif isinstance(command, ResumeTaskCommand):
                target = next((item for item in state.tasks.paused if item.task_id == command.task_id), None)
                active_flow = target.flow_id if target else None
            elif isinstance(command, CancelTaskCommand):
                if state.tasks.active and command.task_id == state.tasks.active.task_id:
                    active_flow = None
            elif isinstance(command, SetSlotsCommand):
                flow = flow_catalog.flows.get(active_flow)
                allowed = {slot.name for slot in flow.slots} if flow else set()
                if not command.slots or not set(command.slots).issubset(allowed):
                    return TurnPlanValidationResult(valid=False, reason=ClarifyReason.INVALID_TASK_COMMAND)

        # 2 逐个命令校验
        for command in task.commands:
            # start_flow：flow_id 必须在 yaml 里存在
            if isinstance(command, StartFlowCommand):
                if command.flow not in flow_catalog.flows:
                    return TurnPlanValidationResult(
                        valid=False,
                        reason=ClarifyReason.INVALID_TASK_COMMAND,
                    )

            # resume_task：只能恢复"确实在暂停列表里"的任务
            if isinstance(command, ResumeTaskCommand):
                paused_task_id = [
                    paused_task.task_id
                    for paused_task in state.tasks.paused
                ]
                if command.task_id not in paused_task_id:
                    return TurnPlanValidationResult(
                        valid=False,
                        reason=ClarifyReason.INVALID_TASK_COMMAND,
                    )

            # cancel_task：暂停列表 + 当前活跃任务里都要找
            if isinstance(command, CancelTaskCommand):
                all_task_id = [
                    paused_task.task_id
                    for paused_task in state.tasks.paused
                ]
                if state.tasks.active:
                    all_task_id.append(state.tasks.active.task_id)

                if command.task_id not in all_task_id:
                    return TurnPlanValidationResult(
                        valid=False,
                        reason=ClarifyReason.INVALID_TASK_COMMAND,
                    )

        return TurnPlanValidationResult(valid=True)

    # 知识检索校验：目前没有意图清单，先放行
    def _validate_knowledge(self, knowledge) -> TurnPlanValidationResult:
        from finassist.knowledge.intents import KNOWLEDGE_INTENTS
        if knowledge and any(intent not in KNOWLEDGE_INTENTS for intent in knowledge.intents):
            return TurnPlanValidationResult(valid=False, reason=ClarifyReason.UNKNOWN_KNOWLEDGE_INTENT)
        if not knowledge or not knowledge.intents:
            return TurnPlanValidationResult(
                valid=False,
                reason=ClarifyReason.MISSING_KNOWLEDGE_INTENT,
            )
        return TurnPlanValidationResult(valid=True)
