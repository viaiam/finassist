"""
命令执行器：把「要干什么」翻译成「state 怎么变」。

    @Aythor:Bee
    @Time:2026/11/11
    @Desc:根据意图识别结果 commands 更新 state 数据

■ 它在哪
    engine → task/task_handler.py 第 1 步 → **CommandProcessor.process_command()**
      → 返回 list[TaskEvent] → task/tasklifecycle/task_lifecycle.py 翻成中文提示

■ 四种命令，四种改法

    | 命令        | 改 state 的哪里                | 产出事件                     |
    |-------------|--------------------------------|------------------------------|
    | start_flow  | tasks.active（旧任务进 paused）| TaskStarted 或 TaskSwitched  |
    | set_slots   | tasks.active.slots             | 无（返回 None）              |
    | resume_task | paused → active                | TaskResumed                  |
    | cancel_task | 从 active/paused 里删掉        | TaskCanceled                 |

■ ※ 核心约定：这里只改数据，一个字的中文都不产生
    它返回的是「事件」（TaskStarted 这种类型化对象），
    由下一个环节 TaskLifecycleResponder 决定怎么说。
    这样「发生了什么」和「怎么表达」可以各自演化。

■ ※ 为什么 set_slots 特殊（没有事件）
    填槽位不是「任务状态变化」，用户不需要听到「好的，我把订单号记下来了」。
    它只是让流程能继续往下走，所以返回 None，lifecycle 环节自动跳过。

■ ※ start_flow 时新任务从哪一步开始
    不是写死 "start"，而是 flow.get_start_step().id ——
    去 yaml 里找 type=start 的那一步。这样 yaml 里改了入口步骤也不用动代码。
    同时 start_task 内部会处理「原来有任务」的情况：
    把旧任务连同它的 slots 一起压进 paused，之后还能 resume 回来。

■ 一个防御
    set_slots 前判断 active 是否为空。
    ※ 不判就是 AttributeError: 'NoneType' object has no attribute 'slots'，
      而模型完全可能在没开任务时凭空调一个 set_slots。
"""
import uuid

from finassist.domain.state import DialogueState, TaskInstance
from finassist.lifecycle.models import TaskEvent
from finassist.plan.command import (
    Command, StartFlowCommand, SetSlotsCommand, ResumeTaskCommand, CancelTaskCommand,
)
from finassist.task.flow.models import FlowCatalog, Flow
from finassist.task.flow.steps import FlowStep


class CommandProcessor:

    # 第一步 执行 commands，修改任务状态
    ## 修改 state 里面任务状态数据 active 或者 paused
    ## commands: list[Command]，意图识别结果列表
    async def process_command(self,
                              commands: list[Command],
                              state: DialogueState,
                              flow_catalog: FlowCatalog) -> list[TaskEvent]:
        events: list[TaskEvent] = []
        for command in commands:
            event: TaskEvent = self._execute_command(command, state, flow_catalog)
            if event:
                events.append(event)
        return events

    # 处理每一个 command，根据类型做不同数据 state 更新
    def _execute_command(self,
                         command: Command,
                         state: DialogueState,
                         flow_catalog: FlowCatalog) -> TaskEvent:
        # {"command": "start_flow", "flow": "<flow_id>"}
        if isinstance(command, StartFlowCommand):
            # 原则：向 state 里面 active 设置数据
            # 新任务，创建 TaskInstance 对象，放到 active 里面
            flow_id = command.flow
            # 根据流程 id 获取流程对象，再取 start 类型步骤的 id
            flow: Flow = flow_catalog.get_flow_by_id(flow_id)
            start_step: FlowStep = flow.get_start_step()
            step_id = start_step.id

            # 创建 TaskInstance 对象
            task = TaskInstance(
                flow_id=flow_id,
                step_id=step_id,
                task_id=str(uuid.uuid4()),
            )

            # 把创建的 task 放到 state 的 active 里面
            ## 当前有 active：先把旧任务压进 paused，再让新任务变成 active
            ## 当前没有 active：直接变成 active
            event: TaskEvent = state.tasks.start_task(task)
            return event

        # {"command": "set_slots", "slots": {"<slot_name>": "<value>"}}
        # 设置槽位数据，没有任务状态变化（返回 None）
        if isinstance(command, SetSlotsCommand):
            # 没有活跃任务时无处可写，直接跳过
            # （参考版这里是 state.tasks.active.slots.update(...)，active 为 None 会 AttributeError）
            if state.tasks.active is None:
                return None
            state.tasks.active.slots.update(command.slots)
            return None

        # {"command": "resume_task", "task_id": "<task_id>"}
        if isinstance(command, ResumeTaskCommand):
            return state.tasks.resume_task(command.task_id)

        # {"command": "cancel_task", "task_id": "<task_id>"}
        if isinstance(command, CancelTaskCommand):
            return state.tasks.cancel_task(command.task_id)

        # 未知 command：validator 已经拦过，这里再兜一层
        return None
