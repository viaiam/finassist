"""
命令模型：LLM 输出的「要干什么」的结构化表达。

■ 它在哪
    plan/turn_planner.py 让模型输出 JSON → prompts/models.py 的 TaskTurnPlan
    → TurnPlanValidator 校验 → engine/dialogue_engine.py 把 plan.command
    （还是个 dict）交给 Command.from_dict 变成下面这些对象
    → task/command/command_processor.py 按类型分派执行。

■ ※ 为什么要「dict → 带类型的子类」这一步？
    如果全程用 dict，写错 key 只能运行时才发现（command["flwo"]）。
    转成 dataclass 后，字段名写错 IDE 立刻报红，而且能按类型分派：
    isinstance(cmd, SetSlotsCommand) 比 cmd["command"] == "set_slots" 安全得多。

■ 四种命令（YAML/提示词里的完整形态）

    | command     | 完整形态                                                      | 作用                  |
    |-------------|---------------------------------------------------------------|-----------------------|
    | start_flow  | {"command": "start_flow",  "flow": "<flow_id>"}                | 启动指定流程          |
    | set_slots   | {"command": "set_slots",   "slots": {"<槽位名>": "<值>"}}      | 往当前任务写槽位      |
    | cancel_task | {"command": "cancel_task", "task_id": "<task_id>"}             | 取消指定任务          |
    | resume_task | {"command": "resume_task", "task_id": "<task_id>"}             | 恢复之前挂起的任务    |

■ 一个典型场景（对应 README 里的例子）
    用户先说「我的订单号 1101，我想退单」，中途又说「算了，我想看物流」：
    模型会输出 start_flow(flow=logistics_tracking) ——
    旧任务不是被删掉，而是被「切走」放进 paused，之后还能 resume_task 回来。

■ ※ 注意 from_dict 是「按图索骥」的
    它拿 command_data["command"] 去 COMMAND_NAME_TO_CLASS 里查类，再 clz(**command_data)。
    所以：
    1) 多出来的键会直接 TypeError（比如模型幻觉出 "reason" 字段）；
    2) command 名字对不上会 KeyError。
    对 LLM 的输出，这两种情况都不罕见 —— 调用方必须能兜住（见 dialogue_engine.py）。
"""
from dataclasses import dataclass
from typing import Any

# 数据模型，封装意图识别组件返回数据
@dataclass
class Command:
    command: str
    # 把dict转换不同任务对应的对象
    # 前向引用
    # `{"command": "start_flow", "flow": "<flow_id>"}`
    @classmethod
    def from_dict(cls,command_data: dict) -> "Command":
        # clz  StartFlowCommand
        clz = COMMAND_NAME_TO_CLASS[command_data["command"]]
        return clz(**command_data)


# start_flow
@dataclass
class StartFlowCommand(Command):
    flow: str

# set_slots
@dataclass
class SetSlotsCommand(Command):
    slots: dict[str, Any]

# cancel_task
@dataclass
class CancelTaskCommand(Command):
    task_id: str

# resume_task
@dataclass
class ResumeTaskCommand(Command):
    task_id: str


COMMAND_NAME_TO_CLASS: dict[str, type[Command]] = {
    "start_flow": StartFlowCommand,
    "set_slots": SetSlotsCommand,
    "cancel_task": CancelTaskCommand,
    "resume_task": ResumeTaskCommand,
}
