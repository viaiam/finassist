"""
任务方向的对外入口：一次「任务类」的用户输入在这里被处理完。

    @Aythor:Bee
    @Time:2026/11/13
    @Desc:TaskHandler —— 任务流程方向的对外入口，把三个组件串起来：
          commandProcessor：按 commands 更新 state（active / paused / slots）
          tasklifecycle   ：把状态变化翻成中文提示
          flowExecutor    ：从 active 指向的步骤开始往下推进
          最后把两段话合并成一个 list[BotMessage] 返回给 engine

■ 它在哪
    engine/dialogue_engine.py 的 4.1 分支 → **TaskHandler.handle()**
      → task/command/command_processor.py（改状态，产出事件）
      → task/tasklifecycle/task_lifecycle.py（事件 → 中文提示语）
      → task/flowexecutor/flow_executor.py（推流程，产出真正的回答）

■ 「命令 → 事件 → 话术」三段式（本项目最值得学的设计）
    第 1 段：只认命令，只改数据   —— CommandProcessor，绝不 print 任何中文
    第 2 段：只认事件，只出话术   —— TaskLifecycleResponder，绝不改数据
    第 3 段：只认步骤，只推流程   —— FlowExecutor，只管「下一步问什么」

    ※ 为什么要拆这么细？
      如果一边改状态一边拼话术，等你以后想换一种说法（或换语言、换渠道），
      就得回头去动业务逻辑，很容易顺手把状态改坏。
      拆开之后「发生了什么」（事件）和「怎么说」（话术）是两个独立可替换的零件。

■ ※ 为什么先执行命令、再推流程（顺序不能反）
    command 把 active 换成新的 flow 之后，flowExecutor 才知道该从哪一步开始。
    反过来的话，它推的还是上一个任务的步骤。

■ 返回值的拼接顺序有讲究
    先放 lifecycle 的提示（「好的，帮你查订单」），再放流程产生的正文
    （「请提供订单号」），这样用户读到的话是通顺的。
"""
from finassist.domain.message import BotMessage, UserMessage
from finassist.domain.state import DialogueState
from finassist.lifecycle.models import TaskEvent
from finassist.plan.command import Command
from finassist.task.command.command_processor import CommandProcessor
from finassist.task.flow.models import FlowCatalog
from finassist.task.flowexecutor.flow_executor import FlowExecutor
from finassist.task.tasklifecycle.task_lifecycle import TaskLifecycleResponder


class TaskHandler:

    def __init__(self,
                 command_processor: CommandProcessor,
                 task_lifecycle: TaskLifecycleResponder,
                 flow_executor: FlowExecutor,
                 flow_catalog: FlowCatalog):
        self.command_processor = command_processor
        self.task_lifecycle = task_lifecycle
        self.flow_executor = flow_executor
        self.flow_catalog = flow_catalog

    # 入口方法
    async def handle(self,
                     commands: list[Command],
                     state: DialogueState,
                     user_message: UserMessage) -> list[BotMessage]:
        # 1 先改状态：start_flow / set_slots / resume_task / cancel_task
        events: list[TaskEvent] = await self.command_processor.process_command(
            commands=commands,
            state=state,
            flow_catalog=self.flow_catalog,
        )

        # 2 状态变化翻成人话（"好的，现在开始执行订单状态查询"）
        messages: list[BotMessage] = await self.task_lifecycle.respond(events=events)

        # 3 再推流程：从 active 的 step 开始往下走，
        #   走到要用户输入（collect 缺槽位）或者流程结束（end）为止
        flow_messages: list[BotMessage] = await self.flow_executor.execute(
            state=state,
            user_message=user_message,
            flow_catalog=self.flow_catalog,
        )

        # 4 两段话合并：先"我开始办了"，再"请提供订单号"
        messages.extend(flow_messages)
        return messages
